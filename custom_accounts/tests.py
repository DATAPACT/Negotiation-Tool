from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import clear_script_prefix, get_script_prefix

from custom_accounts.base_path import AppBasePathMiddleware


class AppBasePathMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def tearDown(self):
        clear_script_prefix()

    @override_settings(
        APP_BASE_PATH="/negotiation",
        APP_REQUEST_PREFIXES=("/negotiation",),
    )
    def test_default_path_is_stripped(self):
        request = self.factory.get("/negotiation/organization/home")

        middleware = AppBasePathMiddleware(lambda req: HttpResponse("ok"))
        middleware(request)

        self.assertEqual(request.path_info, "/organization/home")
        self.assertEqual(request.path, "/negotiation/organization/home")
        self.assertEqual(request.META["SCRIPT_NAME"], "/negotiation")
        self.assertEqual(get_script_prefix(), "/negotiation/")

    @override_settings(
        APP_BASE_PATH="/datapact/negotiation",
        APP_REQUEST_PREFIXES=("/datapact/negotiation", "/negotiation"),
    )
    def test_project_prefixed_browser_path_is_stripped(self):
        request = self.factory.get("/datapact/negotiation/organization/home")

        middleware = AppBasePathMiddleware(lambda req: HttpResponse("ok"))
        middleware(request)

        self.assertEqual(request.path_info, "/organization/home")
        self.assertEqual(request.path, "/datapact/negotiation/organization/home")
        self.assertEqual(request.META["SCRIPT_NAME"], "/datapact/negotiation")
        self.assertEqual(get_script_prefix(), "/datapact/negotiation/")

    @override_settings(
        APP_BASE_PATH="/datapact/negotiation",
        APP_REQUEST_PREFIXES=("/datapact/negotiation", "/negotiation"),
    )
    def test_rewritten_upstream_path_is_accepted(self):
        request = self.factory.get("/negotiation/organization/home")

        middleware = AppBasePathMiddleware(lambda req: HttpResponse("ok"))
        middleware(request)

        self.assertEqual(request.path_info, "/organization/home")
        self.assertEqual(request.path, "/datapact/negotiation/organization/home")
        self.assertEqual(request.META["SCRIPT_NAME"], "/datapact/negotiation")
        self.assertEqual(get_script_prefix(), "/datapact/negotiation/")

    @override_settings(
        APP_BASE_PATH="/upcast/negotiation",
        APP_REQUEST_PREFIXES=("/upcast/negotiation", "/negotiation"),
    )
    def test_root_path_keeps_external_prefix(self):
        request = self.factory.get("/negotiation")

        middleware = AppBasePathMiddleware(lambda req: HttpResponse("ok"))
        middleware(request)

        self.assertEqual(request.path_info, "/")
        self.assertEqual(request.path, "/upcast/negotiation/")
        self.assertEqual(request.META["PATH_INFO"], "/")
        self.assertEqual(request.META["SCRIPT_NAME"], "/upcast/negotiation")
        self.assertEqual(get_script_prefix(), "/upcast/negotiation/")
