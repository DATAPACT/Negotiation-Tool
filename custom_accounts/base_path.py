from django.conf import settings
from django.urls import set_script_prefix


class AppBasePathMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.app_base_path = (getattr(settings, "APP_BASE_PATH", "") or "").rstrip("/")
        configured_prefixes = getattr(settings, "APP_REQUEST_PREFIXES", ()) or ()
        unique_prefixes = {
            (prefix or "").rstrip("/")
            for prefix in configured_prefixes
            if (prefix or "").strip("/")
        }
        if self.app_base_path:
            unique_prefixes.add(self.app_base_path)
        self.request_prefixes = sorted(unique_prefixes, key=len, reverse=True)
        self.script_prefix = f"{self.app_base_path}/" if self.app_base_path else "/"

    def __call__(self, request):
        if self.app_base_path:
            original_path = request.path_info or "/"
            stripped_path = None

            forwarded_prefix = (request.META.get("HTTP_X_FORWARDED_PREFIX") or "").strip().rstrip("/")
            request_prefixes = list(self.request_prefixes)
            if forwarded_prefix:
                normalized_forwarded_prefix = "/" + forwarded_prefix.strip("/")
                if normalized_forwarded_prefix not in request_prefixes:
                    request_prefixes.insert(0, normalized_forwarded_prefix)

            for prefix in request_prefixes:
                prefix_with_slash = f"{prefix}/"
                if original_path == prefix:
                    stripped_path = "/"
                    break
                if original_path.startswith(prefix_with_slash):
                    stripped_path = original_path[len(prefix):] or "/"
                    break

            if stripped_path is not None:
                request.path_info = stripped_path
                request.META["PATH_INFO"] = stripped_path
                if stripped_path == "/":
                    request.path = self.script_prefix
                else:
                    request.path = f"{self.app_base_path}{stripped_path}"

            request.META["SCRIPT_NAME"] = self.app_base_path
            set_script_prefix(self.script_prefix)

        return self.get_response(request)
