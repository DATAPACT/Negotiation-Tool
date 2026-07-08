from django.conf import settings
from django.urls import set_script_prefix


class AppBasePathMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.app_base_path = (getattr(settings, "APP_BASE_PATH", "") or "").rstrip("/")

    def __call__(self, request):
        if self.app_base_path:
            original_path = request.path_info or "/"
            prefix_with_slash = f"{self.app_base_path}/"

            if original_path == self.app_base_path:
                request.path_info = "/"
                request.path = self.app_base_path
            elif original_path.startswith(prefix_with_slash):
                stripped = original_path[len(self.app_base_path):]
                request.path_info = stripped or "/"
                request.path = f"{self.app_base_path}{request.path_info}"

            request.META["SCRIPT_NAME"] = self.app_base_path
            set_script_prefix(f"{self.app_base_path}/")

        return self.get_response(request)
