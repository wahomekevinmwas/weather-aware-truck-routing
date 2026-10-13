import unittest

from planner.core.risk import Risk, classify, rain_level, snow_level, wind_level


class ThresholdTests(unittest.TestCase):
    def test_wind_boundaries(self):
        cases = [(0, Risk.LOW), (24.9, Risk.LOW), (25, Risk.MODERATE), (34.9, Risk.MODERATE),
                 (35, Risk.HIGH), (44.9, Risk.HIGH), (45, Risk.SEVERE), (54.9, Risk.SEVERE),
                 (55, Risk.NO_TRAVEL), (80, Risk.NO_TRAVEL)]
        for mph, expected in cases:
            self.assertEqual(wind_level(mph), expected, f"wind {mph}")

    def test_rain_boundaries(self):
        cases = [(0, Risk.LOW), (0.09, Risk.LOW), (0.10, Risk.MODERATE), (0.24, Risk.MODERATE),
                 (0.25, Risk.HIGH), (0.49, Risk.HIGH), (0.50, Risk.SEVERE), (1.00, Risk.SEVERE),
                 (1.01, Risk.NO_TRAVEL)]
        for v, expected in cases:
            self.assertEqual(rain_level(v), expected, f"rain {v}")

    def test_snow_boundaries(self):
        cases = [(0, Risk.LOW), (0.49, Risk.LOW), (0.5, Risk.MODERATE), (0.99, Risk.MODERATE),
                 (1.0, Risk.HIGH), (1.99, Risk.HIGH), (2.0, Risk.SEVERE), (3.0, Risk.SEVERE),
                 (3.01, Risk.NO_TRAVEL)]
        for v, expected in cases:
            self.assertEqual(snow_level(v), expected, f"snow {v}")


class LoadRuleTests(unittest.TestCase):
    def level(self, wind, load, rain=0, snow=0):
        return classify(wind, rain, snow, load).level

    def test_55_mph_is_no_travel_for_any_load(self):
        self.assertEqual(self.level(55, 0), Risk.NO_TRAVEL)
        self.assertEqual(self.level(60, 1000), Risk.NO_TRAVEL)

    def test_45_to_54_with_heavy_load_is_no_travel(self):
        self.assertEqual(self.level(50, 30000), Risk.SEVERE)       # exactly 30,000 is not over
        self.assertEqual(self.level(50, 30001), Risk.NO_TRAVEL)
        self.assertEqual(self.level(45, 45000), Risk.NO_TRAVEL)
        self.assertEqual(self.level(54.9, 45000), Risk.NO_TRAVEL)

    def test_35_to_44_with_very_heavy_load_is_severe(self):
        self.assertEqual(self.level(40, 40000), Risk.HIGH)         # exactly 40,000 is not over
        self.assertEqual(self.level(40, 40001), Risk.SEVERE)
        self.assertEqual(self.level(35, 60000), Risk.SEVERE)
        self.assertEqual(self.level(44.9, 60000), Risk.SEVERE)

    def test_load_does_not_change_lighter_wind(self):
        self.assertEqual(self.level(30, 80000), Risk.MODERATE)
        self.assertEqual(self.level(10, 80000), Risk.LOW)

    def test_load_rules_never_lower_a_risk(self):
        # heavy rain stays No Travel even though the wind rule alone would say Severe
        self.assertEqual(self.level(40, 50000, rain=1.5), Risk.NO_TRAVEL)


class CombinationTests(unittest.TestCase):
    def test_worst_of_wind_rain_snow(self):
        a = classify(10, 0.3, 0.6, 20000)
        self.assertEqual((a.wind, a.rain, a.snow, a.level), (Risk.LOW, Risk.HIGH, Risk.MODERATE, Risk.HIGH))

    def test_reasons_explain_the_decision(self):
        a = classify(50, 0.0, 0.0, 35000)
        self.assertEqual(a.level, Risk.NO_TRAVEL)
        self.assertTrue(any("30,000" in r for r in a.reasons))
        self.assertEqual(classify(5, 0, 0, 10000).reasons, [])

    def test_bad_input_is_rejected(self):
        for args in [(-1, 0, 0, 0), (0, None, 0, 0), (0, 0, 0, -5)]:
            with self.assertRaises(ValueError):
                classify(*args)


if __name__ == "__main__":
    unittest.main()
