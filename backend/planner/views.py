"""POST /api/plan: a thin JSON wrapper around PlanService."""
import json
import logging
import threading

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services.geocoding import GeocodingClient
from .services.plan import PlanError, PlanService
from .services.routing import OsrmClient
from .services.weather import WeatherClient

logger = logging.getLogger(__name__)
_service = None
_lock = threading.Lock()


def get_service():
    """One shared service, so the geocoding, routing and weather caches persist across requests."""
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = PlanService(GeocodingClient(), OsrmClient(), WeatherClient())
    return _service


def _error(code, message, status, field=None):
    body = {"code": code, "message": message}
    if field:
        body["field"] = field
    return JsonResponse({"error": body}, status=status)


@csrf_exempt          # stateless JSON API: no cookies or sessions to protect
@require_POST
def plan_view(request):
    try:
        payload = json.loads(request.body)
    except ValueError:
        return _error("invalid_json", "The request body must be valid JSON.", 400)
    if not isinstance(payload, dict):
        return _error("invalid_input", "Send the trip as a JSON object.", 400)
    try:
        result = get_service().plan(payload)
    except PlanError as exc:
        return _error(exc.code, exc.message, exc.status, exc.field)
    except Exception:
        logger.exception("Unexpected error while planning a trip")
        return _error("internal_error", "Something went wrong while planning this trip. Please try again.", 500)
    return JsonResponse(result)
