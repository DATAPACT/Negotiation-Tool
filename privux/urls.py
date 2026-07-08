"""
URL configuration for privux project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import re

from django.conf import settings
from django.contrib import admin
from django.contrib.staticfiles.views import serve as staticfiles_serve
from django.urls import path, include, re_path
from django.views.static import serve as media_serve

urlpatterns = [
    path("", include("custom_accounts.urls")),
    path("superadmin", admin.site.urls),
    # path("policy_editor/", include('django_policy_editor_app.urls')),
]

if settings.DEBUG:
    app_base_path = re.escape(settings.APP_BASE_PATH.strip("/"))
    urlpatterns += [
        re_path(r"^static/(?P<path>.*)$", staticfiles_serve),
        re_path(r"^media/(?P<path>.*)$", media_serve, {"document_root": settings.MEDIA_ROOT}),
    ]
    if app_base_path:
        urlpatterns += [
            re_path(rf"^{app_base_path}/static/(?P<path>.*)$", staticfiles_serve),
            re_path(rf"^{app_base_path}/media/(?P<path>.*)$", media_serve, {"document_root": settings.MEDIA_ROOT}),
        ]
