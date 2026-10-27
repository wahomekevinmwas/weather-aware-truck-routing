<#
Live smoke test for the deployed Weather-Aware Truck Routing app.
It calls the public API and checks: the page loads, plans have a sane structure, numbers add up,
the load weight never lowers risk, spacing is raised when needed, and bad input gives clear errors.

Usage (from the repo root):
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\live_smoke_test.ps1
Optional:
  -BaseUrl https://your-host.onrender.com
#>
param([string]$BaseUrl = "https://weather-aware-truck-routing-ssmj.onrender.com")

$ErrorActionPreference = "Continue"
$BaseUrl = $BaseUrl.TrimEnd("/")
$inv = [System.Globalization.CultureInfo]::InvariantCulture
$results = New-Object System.Collections.ArrayList

function Add-Result($name, $ok, $detail) {
  $label = "FAIL"
  if ($ok) { $label = "PASS" }
  [void]$results.Add([pscustomobject]@{ Test = $name; Result = $label; Detail = $detail })
}

function Invoke-Api($method, $path, $body) {
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $status = 0
  $text = ""
  try {
    if ($method -eq "GET") {
      $resp = Invoke-WebRequest -UseBasicParsing -Uri ($BaseUrl + $path) -TimeoutSec 180
    } else {
      $resp = Invoke-WebRequest -UseBasicParsing -Method Post -Uri ($BaseUrl + $path) -ContentType "application/json" -Body $body -TimeoutSec 180
    }
    $status = [int]$resp.StatusCode
    $text = $resp.Content
  } catch {
    $r = $_.Exception.Response
    if ($r) {
      $status = [int]$r.StatusCode
      try {
        $sr = New-Object System.IO.StreamReader($r.GetResponseStream())
        $text = $sr.ReadToEnd()
      } catch { $text = "" }
    } else {
      $status = -1
      $text = $_.Exception.Message
    }
  }
  $sw.Stop()
  return [pscustomobject]@{ Status = $status; Seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1); Text = $text }
}

function Plan($origin, $dest, $dep, $load, $spacing) {
  $payload = @{ origin = $origin; destination = $dest; departure = $dep; load_lb = $load; spacing = $spacing } | ConvertTo-Json
  return Invoke-Api "POST" "/api/plan" $payload
}

function Parse-Json($text) {
  try { return ($text | ConvertFrom-Json) } catch { return $null }
}

# Structure and arithmetic checks on a successful plan. Returns a list of problems (empty = fine).
function Check-Plan($d) {
  $problems = @()
  if (@($d.routes).Count -lt 1) { $problems += "no routes" }
  $recommended = @($d.routes | Where-Object { $_.recommended }).Count
  if ($recommended -ne 1) { $problems += "recommended routes = $recommended, expected 1" }
  if ($d.heat.hours -ne 48) { $problems += "heat.hours = $($d.heat.hours), expected 48" }
  foreach ($rt in $d.routes) {
    $label = "route " + ($rt.index + 1)
    $n = @($rt.checkpoints).Count
    $rows = @($rt.heat_levels).Count
    if ($rows -ne $n) {
      $problems += "$label heat rows $rows vs checkpoints $n"
    } elseif ($n -gt 0 -and @($rt.heat_levels[0]).Count -ne 49) {
      $problems += "$label heat row length $(@($rt.heat_levels[0]).Count), expected 49"
    }
    $sum = 0.0
    foreach ($p in $rt.stats.miles_by_level.PSObject.Properties) { $sum += [double]$p.Value }
    if ([math]::Abs($sum - [double]$rt.distance_miles) -gt 1.0) {
      $problems += "$label miles by level $([math]::Round($sum, 1)) vs distance $($rt.distance_miles)"
    }
    $prev = $null
    foreach ($cp in $rt.checkpoints) {
      $t = [datetimeoffset]::Parse([string]$cp.eta_utc, $inv)
      if ($prev -and $t -lt $prev) { $problems += "$label ETAs not increasing"; break }
      $prev = $t
    }
  }
  return $problems
}

function Summarize($r, $d) {
  $kb = [math]::Round($r.Text.Length / 1024)
  $rec = "n/a"
  if ($d -and $d.routes) { $rec = "Route " + ($d.recommended_index + 1) }
  return ("HTTP {0}, {1} s, {2} KB, {3} routes, recommended {4}, {5} notes" -f $r.Status, $r.Seconds, $kb, @($d.routes).Count, $rec, @($d.notes).Count)
}

function Test-PlanCase($name, $r, $extra) {
  $d = Parse-Json $r.Text
  $problems = @()
  if ($r.Status -ne 200) {
    $problems += ("HTTP " + $r.Status)
  } elseif (-not $d) {
    $problems += "response is not JSON"
  } else {
    $problems += Check-Plan $d
    if ($extra) { $problems += (& $extra $d) }
  }
  if ($problems.Count -eq 0) {
    Add-Result $name $true (Summarize $r $d)
  } else {
    Add-Result $name $false ((Summarize $r $d) + " | " + ($problems -join "; "))
  }
  return $d
}

function Test-ErrorCase($name, $r, $wantStatus, $wantField, $wantCode) {
  $d = Parse-Json $r.Text
  $problems = @()
  if ($r.Status -ne $wantStatus) { $problems += "HTTP $($r.Status), expected $wantStatus" }
  $msg = ""
  if ($wantStatus -ne 405) {
    if (-not $d -or -not $d.error) {
      $problems += "no error object in the response"
    } else {
      $msg = [string]$d.error.message
      if ($wantField -and $d.error.field -ne $wantField) { $problems += "field '$($d.error.field)', expected '$wantField'" }
      if ($wantCode -and $d.error.code -ne $wantCode) { $problems += "code '$($d.error.code)', expected '$wantCode'" }
    }
  }
  if ($msg.Length -gt 70) { $msg = $msg.Substring(0, 70) + "..." }
  $detail = ("HTTP {0}, {1} s {2}" -f $r.Status, $r.Seconds, $msg)
  if ($problems.Count -eq 0) { Add-Result $name $true $detail } else { Add-Result $name $false ($detail + " | " + ($problems -join "; ")) }
}

$utc = [datetime]::UtcNow
$tomorrow = $utc.AddDays(1).ToString("yyyy-MM-dd", $inv) + "T08:00"
$past = $utc.AddDays(-2).ToString("yyyy-MM-dd", $inv) + "T08:00"
$farFuture = $utc.AddDays(25).ToString("yyyy-MM-dd", $inv) + "T08:00"

Write-Host "Testing $BaseUrl (departure $tomorrow). This takes a few minutes; the first call may be slow if the server was asleep." -ForegroundColor Cyan

# 1. Page load (also shows cold-start time if the server was idle)
$r = Invoke-Api "GET" "/" $null
Add-Result "Home page loads" ($r.Status -eq 200 -and $r.Text.Contains("<script")) ("HTTP {0}, {1} s" -f $r.Status, $r.Seconds)

# 2. Main trip
$r = Plan "Chicago, IL" "Dallas, TX" $tomorrow 42000 25
$dallas = Test-PlanCase "Chicago -> Dallas, 42,000 lb, 25 mi" $r $null

# 3. Spacing is raised on long routes when 10 miles is requested
$r = Plan "Chicago, IL" "New York, NY" $tomorrow 42000 10
$null = Test-PlanCase "Chicago -> New York at 10 mi (spacing raised)" $r {
  param($d)
  $out = @()
  if ($d.spacing.requested -ne 10 -or $d.spacing.used -ne 25) { $out += "spacing requested/used = $($d.spacing.requested)/$($d.spacing.used), expected 10/25" }
  if (-not (@($d.notes) -match "raised")) { $out += "no spacing-raised note" }
  return $out
}

# 4. Short trip keeps 10 mile spacing
$r = Plan "Denver, CO" "Colorado Springs, CO" $tomorrow 42000 10
$null = Test-PlanCase "Denver -> Colorado Springs at 10 mi (spacing kept)" $r {
  param($d)
  if ($d.spacing.used -ne 10) { return @("spacing used $($d.spacing.used), expected 10") }
  return @()
}

# 5. Coordinates as input
$r = Plan "41.8781,-87.6298" "32.7767,-96.7970" $tomorrow 42000 25
$null = Test-PlanCase "Coordinates as origin and destination" $r $null

# 6. A heavier load must never lower risk on the same trip
$light = Plan "Chicago, IL" "Dallas, TX" $tomorrow 10000 25
$heavy = Plan "Chicago, IL" "Dallas, TX" $tomorrow 80000 25
$dl = Parse-Json $light.Text
$dh = Parse-Json $heavy.Text
if ($dl -and $dh -and $light.Status -eq 200 -and $heavy.Status -eq 200) {
  $bad = @()
  $pairs = @()
  $count = [math]::Min(@($dl.routes).Count, @($dh.routes).Count)
  for ($i = 0; $i -lt $count; $i++) {
    $a = [double]$dl.routes[$i].stats.average_risk
    $b = [double]$dh.routes[$i].stats.average_risk
    $pairs += ("R{0} {1:N2}->{2:N2}" -f ($i + 1), $a, $b)
    if ($b -lt $a - 0.011) { $bad += "route $($i + 1) average risk fell with the heavier load" }
  }
  $detail = "avg risk 10,000 lb -> 80,000 lb: " + ($pairs -join ", ")
  if ($bad.Count -eq 0) { Add-Result "Heavier load never lowers risk" $true $detail } else { Add-Result "Heavier load never lowers risk" $false ($detail + " | " + ($bad -join "; ")) }
} else {
  Add-Result "Heavier load never lowers risk" $false ("HTTP {0} and {1}" -f $light.Status, $heavy.Status)
}

# 7. Error handling
Test-ErrorCase "Unknown origin" (Plan "zzzzqqqq nowhere" "Dallas, TX" $tomorrow 42000 25) 400 "origin" $null
Test-ErrorCase "Same origin and destination" (Plan "Chicago, IL" "Chicago, IL" $tomorrow 42000 25) 400 "destination" $null
Test-ErrorCase "Empty origin" (Plan "" "Dallas, TX" $tomorrow 42000 25) 400 "origin" $null
Test-ErrorCase "Departure in the past" (Plan "Chicago, IL" "Dallas, TX" $past 42000 25) 400 "departure" $null
Test-ErrorCase "Departure beyond the forecast window" (Plan "Chicago, IL" "Dallas, TX" $farFuture 42000 25) 400 "departure" $null
Test-ErrorCase "Load above 200,000 lb" (Plan "Chicago, IL" "Dallas, TX" $tomorrow 250000 25) 400 "load_lb" $null
Test-ErrorCase "Spacing of 15 miles" (Plan "Chicago, IL" "Dallas, TX" $tomorrow 42000 15) 400 "spacing" $null
Test-ErrorCase "Invalid JSON body" (Invoke-Api "POST" "/api/plan" "not json") 400 $null "invalid_json"
Test-ErrorCase "GET is not allowed" (Invoke-Api "GET" "/api/plan" $null) 405 $null $null

Write-Host ""
$results | Format-Table -AutoSize -Wrap
if ($dallas) { Write-Host ("Explanation (Chicago -> Dallas): " + $dallas.explanation) }
$failed = @($results | Where-Object { $_.Result -eq "FAIL" }).Count
$color = "Green"
if ($failed -gt 0) { $color = "Red" }
Write-Host ("{0} checks, {1} failed." -f $results.Count, $failed) -ForegroundColor $color
Write-Host "Note: if a plan shows many Unknown miles or 'weather' notes, the free weather API may have rate-limited the run; wait a few minutes and retry." -ForegroundColor DarkGray
