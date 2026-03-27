import json
from django.conf import settings


def sso_config(request):
    """Injects SSO trusted origins and auth state into all template contexts."""
    return {
        "SSO_TRUSTED_ORIGINS_JSON": json.dumps(settings.FRAME_ANCESTORS),
        "is_sso": request.session.get("is_sso", False),
    }