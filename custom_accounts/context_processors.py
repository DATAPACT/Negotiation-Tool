import json

from django.conf import settings


def sso_config(request):
    """Expose SSO settings and auth state to all templates."""
    return {
        "APP_BASE_PATH": settings.APP_BASE_PATH,
        "SSO_TRUSTED_ORIGINS_JSON": json.dumps(settings.FRAME_ANCESTORS),
        "is_sso": request.session.get("is_sso", False),
    }
