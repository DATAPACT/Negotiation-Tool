# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------


from django.shortcuts import redirect
from django.urls import reverse


class UserRedirectMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # One-time configuration and initialization.

    def __call__(self, request):
        if request.user.is_authenticated and request.path == reverse("index"):
            if request.user.role == "DATACONTROLLER_PROCESSOR":
                return redirect("datacontrollernegotiation")
            elif request.user.role == "DATA_PROVIDER":
                return redirect("datacontrollernegotiation")

        response = self.get_response(request)

        return response
