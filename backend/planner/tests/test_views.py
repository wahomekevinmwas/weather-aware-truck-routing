import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

from django.test import RequestFactory  # noqa: E402

from planner import views  # noqa: E402
from planner.services.plan import PlanError  # noqa: E402


class FakeService:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.payloads = result, error, []

    def plan(self, payload):
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return self.result


class PlanViewTests(unittest.TestCase):
    def post(self, body, service):
        request = RequestFactory().post("/api/plan", data=body, content_type="application/json")
        with patch.object(views, "get_service", return_value=service):
            return views.plan_view(request)

    def test_success_returns_the_service_result(self):
        service = FakeService(result={"ok": True})
        response = self.post(json.dumps({"origin": "A"}), service)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {"ok": True})
        self.assertEqual(service.payloads, [{"origin": "A"}])

    def test_get_is_not_allowed(self):
        self.assertEqual(views.plan_view(RequestFactory().get("/api/plan")).status_code, 405)

    def test_invalid_json(self):
        response = self.post("{nope", FakeService())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["error"]["code"], "invalid_json")

    def test_json_must_be_an_object(self):
        response = self.post("[1, 2]", FakeService())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["error"]["code"], "invalid_input")

    def test_plan_error_maps_to_status_and_body(self):
        service = FakeService(error=PlanError("Enter an origin.", field="origin"))
        response = self.post("{}", service)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["error"],
                         {"code": "invalid_input", "message": "Enter an origin.", "field": "origin"})

    def test_unexpected_error_becomes_a_json_500_without_details(self):
        service = FakeService(error=RuntimeError("boom"))
        with self.assertLogs("planner.views", level="ERROR"):
            response = self.post("{}", service)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(json.loads(response.content)["error"]["code"], "internal_error")
        self.assertNotIn(b"boom", response.content)


if __name__ == "__main__":
    unittest.main()
