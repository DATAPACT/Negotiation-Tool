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
import difflib
import html
import json
import os
import re
import textwrap
import unicodedata
from copy import deepcopy
from datetime import datetime
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup
from django.contrib import messages
# because of the custom user model
from django.contrib.auth import get_user_model
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from dotenv import load_dotenv
from typing import List, Dict, Optional, Any

from PolicyEngine.Parsers import ODRLParser
from PolicyEngine.Translators import LogicTranslator
from constract_service.contract_service import ContractAPIService
# contract service
from custom_accounts.ajax_ontology import (
    get_rules_from_odrl,
    get_dataset_titles_and_uris,
    get_constraints_types_from_odrl,
    get_operators_from_odrl,
    get_fields_from_datasets, convert_list_to_odrl_jsonld_no_user, get_properties_of_a_class,
    populate_graph, get_action_hierarchy_from_odrl, get_actor_hierarchy_from_dpv,
    get_purpose_hierarchy_from_dpv, get_constraints_for_instances,
    normalize_odrl_graph,
    custom_convert_odrl_policy,
    process_rule,
)
from privux import settings
import uuid

load_dotenv()

API_BASE_URL = os.environ.get("API_BASE_URL")
if not API_BASE_URL:
    raise ValueError("API_BASE_URL environment variable is not set.")

API_AUTHENTICATION_URL = os.environ.get("API_AUTHENTICATION_URL")
if not API_AUTHENTICATION_URL:
    raise ValueError("API_AUTHENTICATION_URL environment variable is not set.")

DJANGO_BASE_URL = os.environ.get("DJANGO_BASE_URL")
if not DJANGO_BASE_URL:
    raise ValueError("DJANGO_BASE_URL environment variable is not set.")

User = get_user_model()


def index(request):
    return render(request, "common/index.html")


def auto_login(request):
    return render(request, "register_login/auto-login.html",
                  {"django_base_url": DJANGO_BASE_URL})


@csrf_exempt
def set_auto_login_session(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid method"}, status=405)

    try:
        data = json.loads(request.body)
        token = data.get("token")
        if not token:
            return JsonResponse({"error": "Missing token"}, status=400)

        # Call the dedicated authentication service to verify the token.
        # Old code:
        # verify_url = f"{API_BASE_URL}/user/verify-token/"
        verify_url = f"{API_AUTHENTICATION_URL}/user/verify-token/"
        verify_res = requests.post(verify_url, data=token, headers={"Content-Type": "text/plain"})

        if verify_res.status_code != 200:
            return JsonResponse({"error": "Token verification failed"}, status=401)

        verified_data = verify_res.json()
        user = verified_data.get("user")

        if not user:
            return JsonResponse({"error": "Invalid response from verification"}, status=500)

        # Save in session
        request.session["access_token"] = token
        request.session["user_id"] = user.get("id")
        request.session["user_type"] = user.get("type")

        return JsonResponse({"success": True})

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def signin(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        print("\n\n\n username", username)
        print("password", password)
        if not username or not password:
            messages.error(request, "Please enter both username and password.")
            return redirect("login")

        # Login must go to the authentication service, not the negotiation API.
        # Old code:
        # url = f"{API_BASE_URL}/user/login/"
        url = f"{API_AUTHENTICATION_URL}/user/login/"
        print(f'Attempting to log in to {url} with username: {username}')
        data = {
            "username": username,
            "password": password,
        }

        try:
            response = requests.post(url, data=data)
            print(f"Response status code: {response.status_code}")
            print(f"Response content: {response.content}")
        except requests.RequestException as e:
            messages.error(request, "Login service is unavailable. Please try again later.")
            return redirect("login")

        if response.status_code == 200:
            resp_data = response.json()
            # Save token and user info in session
            try:
                # Rotate session to avoid stale cached baselines across logins
                request.session.cycle_key()
            except Exception:
                pass
            request.session["access_token"] = resp_data.get("access_token")
            request.session["user_id"] = resp_data.get("user_id")
            request.session["user_type"] = resp_data.get("user_type")
            return redirect("datacontrollernegotiation")
        else:
            # Extract API error message if any, or default message
            try:
                detail = response.json().get("detail", "Invalid username or password.")
            except Exception:
                detail = "Invalid username or password."

            messages.error(request, detail)
            return redirect("login")

    # For GET requests, just render login page
    return render(request, "register_login/login.html")


# def send_activation_email(register_user, email_host_user, request):
#     # Email Address Confirmation Email
#     current_site = get_current_site(request)
#     subject = "Confirm your Email Privacy Preference UI - UPCAST Project"
#     message = render_to_string(
#         "register_login/confirmation_email.html",
#         {
#             "name": register_user.first_name,
#             "domain": current_site.domain,
#             "uid": urlsafe_base64_encode(force_bytes(register_user.pk)),
#             "token": generate_token.make_token(register_user),
#         },
#     )
#     email = EmailMessage(
#         subject,
#         message,
#         settings.EMAIL_HOST_USER,
#         [register_user.email],
#     )
#     email.fail_silently = True
#     email.send()

def register(request):
    if request.method == "POST":
        print("Registering user...")
        user_name = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirmpassword")
        user_type = request.POST.get("user_type")  # Default to 'consumer' if not provided
        organization = request.POST.get("organization")
        # distinctive_title = request.POST.get("distinctive_title")
        incorporation = request.POST.get("incorporation")
        address = request.POST.get("address")
        vat_no = request.POST.get("vat_no")
        # legal_representative = request.POST.get("legal_representative")
        # contact_person = request.POST.get("contact_person")
        position_title = request.POST.get("position_title")
        phone = request.POST.get("phone")

        data = {
            "name": user_name,
            "type": user_type,
            "username_email": email,
            "password": password,
            "organization": organization,
            # "distinctive_title": distinctive_title,
            "incorporation": incorporation,
            "address": address,
            "vat_no": vat_no,
            "position_title": position_title,
            "phone": phone,
        }

        master_password = os.getenv("MASTER_PASSWORD", "master_password")

        if user_name is None or user_name == "":
            messages.error(request, "Username cannot be empty.")
            return redirect("register")

        if len(user_name) < 4 or len(user_name) > 20:
            messages.error(request, "Username should be between 4 and 20 charcters.")
            return redirect("register")

        if password != confirm_password:
            messages.error(request, "The confirmation password does not match.")
            return redirect("register")

        # Registration is handled by the external authentication service.
        # Old code:
        # endpoint_url = f"{API_BASE_URL}/user/register/"
        endpoint_url = f"{API_AUTHENTICATION_URL}/user/register/"

        try:
            response = requests.post(f"{endpoint_url}?master_password_input={master_password}",
                                     json=data)
            if response.status_code in [200, 201]:
                response_data = response.json()
                print(f"User registered successfully: {response_data}")
                messages.success(request, "Account created successfully! Please log in.")
                return redirect("login")
            else:
                # Handle errors returned from FastAPI
                try:
                    error_message = response.json().get("detail", "Registration failed.")
                except ValueError:
                    error_message = "Unexpected response from the registration service."

                messages.error(request, error_message)
                return redirect("register")

        except requests.RequestException:
            messages.error(request, "Registration service is unavailable. Please try again later.")
            return redirect("register")

    return render(request, "register_login/sign-up.html")


# def activate(request, uidb64, token):
#     try:
#         uid = force_str(urlsafe_base64_decode(uidb64))
#         registered_user = User.objects.get(pk=uid)
#     except (TypeError, ValueError, OverflowError, User.DoesNotExist):
#         registered_user = None

#     if registered_user is not None and generate_token.check_token(
#         registered_user, token
#     ):
#         registered_user.is_active = True
#         registered_user.save()
#         messages.success(request, "Your Account has been activated!!")
#         return redirect("login")
#     else:
#         # go back to home page
#         return render(request, "common/index.html")


def datacontrollerhome(request):
    return render(request, "admin_organization/index.html")


def signout(request):
    # Ensure user is authenticated via token in session
    token = request.session.get("access_token")
    user_id = request.session.get("user_id")
    user_type = request.session.get("user_type")

    # Logout must invalidate the token in the authentication service.
    # Old code:
    # endpoint_url = f"{API_BASE_URL}/user/logout/"
    endpoint_url = f"{API_AUTHENTICATION_URL}/user/logout/"

    headers = {
        "Authorization": f"Bearer {token}",
        "user-id": user_id
    }

    try:
        response = requests.post(endpoint_url, headers=headers)
        response.raise_for_status()  # Raise an error for bad responses

        return redirect("login")

    except Exception as e:
        print(f"Error logging out: {e}")
        return JsonResponse({'error': 'Error logging out'}, status=500)


####################policy editor###########################################

def ajax_get_properties_from_properties_file(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            uri = data.get("uri")
            fields = get_properties_of_a_class(uri)
            return JsonResponse({"fields": fields}, status=200)
        except BaseException as e:
            return JsonResponse({"error": str(e)}, status=400)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)


def ajax_get_fields_from_datasets(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            dataset = data.get("uri")
            fields = get_fields_from_datasets(dataset)
            res = 200
            # res = _fetch_valid_status(odrl)
            return JsonResponse({"fields": fields})
        except BaseException as b:
            print("The error response from get_fields_from_datasets is " + str(b));
            return b


def ajax_get_properties_of_a_class(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            uri = data.get("uri")
            print('uri', uri)
            fields = get_properties_of_a_class(uri)
            return JsonResponse({"fields": fields}, status=200)
        except BaseException as e:
            return JsonResponse({"error": str(e)}, status=400)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)


def ajax_get_constraints_for_instances(request):
    print('calling ajax_get_constraints_for_instances')
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            # print('data', data)
            uri = data.get("uri")
            # print('uri', uri)
            fields = get_constraints_for_instances(uri)
            # print('fields', fields)
            return JsonResponse({"fields": fields}, status=200)
        except BaseException as e:
            return JsonResponse({"error": str(e)}, status=400)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)


####################policy editor ends###########################################

def negotiation(request):
    # Ensure user is authenticated via token in session
    # Check URL parameters first (priority over session to allow fresh login)
    url_token = request.GET.get("access_token")
    url_user_id = request.GET.get("user_id")
    url_user_type = request.GET.get("user_type")

    # If URL parameters provided, verify token and override session
    if url_token and url_user_id:
        try:
            # Verify the incoming token with the dedicated authentication service.
            # Old code:
            # verify_url = f"{API_BASE_URL}/user/verify-token/"
            verify_url = f"{API_AUTHENTICATION_URL}/user/verify-token/"
            verify_res = requests.post(verify_url, data=url_token, headers={"Content-Type": "text/plain"})

            if verify_res.status_code == 200:
                # Token is valid, override session with new credentials
                request.session["access_token"] = url_token
                request.session["user_id"] = url_user_id
                request.session["user_type"] = url_user_type or "provider"
                print(f"✅ Session updated from URL parameters for user {url_user_id}")
                token = url_token
                user_id = url_user_id
                user_type = url_user_type or "provider"
            else:
                print(f"❌ Token verification failed: {verify_res.status_code}")
                return redirect("login")
        except Exception as e:
            print(f"❌ Error verifying token: {e}")
            return redirect("login")
    else:
        # Fallback to session
        token = request.session.get("access_token")
        user_id = request.session.get("user_id")
        user_type = request.session.get("user_type")

    if not token or not user_id:
        return redirect("login")

    selected_negotiation_id = request.GET.get("negotiation_id", None)

    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/ODRL_DPV.rdf")), "xml")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/Datasets.ttl")), "turtle")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/Datasets_with_metadata.ttl")), "turtle")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/AdditionalProperties.ttl")), "turtle")
    # populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/CactusOntology.rdf")),"xml")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/CactusOntology.ttl")), "ttl")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/foaf.rdf")), "xml")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/mdatOntology.owl")), "xml")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/nhrf.owl")), "xml")

    # Prepare data for context
    rules = get_rules_from_odrl()
    actors = get_actor_hierarchy_from_dpv()
    actions = get_action_hierarchy_from_odrl()
    constraints = get_constraints_types_from_odrl()
    purposes = get_purpose_hierarchy_from_dpv()
    operators = get_operators_from_odrl()
    rules.append({"label": "Obligation", "uri": "http://www.w3.org/ns/odrl/2/Obligation"})

    # Call FastAPI to get negotiations
    headers = {
        "Authorization": f"Bearer {token}",
        "user-id": user_id
    }

    print(f'Negotiation API headers: {headers}')

    negotiations_url = f"{API_BASE_URL}/negotiation"
    offers_url = f"{API_BASE_URL}/consumer/offer"

    try:
        negotiations_res = requests.get(negotiations_url, headers=headers)
        negotiations_res.raise_for_status()  # Raise an error for bad responses
        # print(f"Negotiations response: {negotiations_res.status_code}")
        # print(f"Negotiations response content: {negotiations_res.text}")
        negotiations = negotiations_res.json()
        # print(f"Negotiations data: {negotiations}")
        negotiations = [{"id": d.pop("_id"), **d} if "_id" in d else d for d in negotiations]
        # print(f"Processed negotiations: {negotiations}")
    except Exception as e:
        print(f"Error fetching negotiations: {e}")
        negotiations = []

    try:
        offers_res = requests.get(offers_url, headers=headers)
        offers = offers_res.json()
        offers = [{"id": d.pop("_id"), **d} if "_id" in d else d for d in offers]
        filtered_offers = [
            offer for offer in offers
            if str(offer.get("consumer_id")) == str(user_id)
        ]
    except Exception as e:
        print(f"Error fetching offers: {e}")
        offers = []
        filtered_offers = []

    context = {
        "datarequestedby": user_id,
        "rules": rules,
        "actors": actors[0:1],
        "actions": actions,
        "targets": [],
        "constraints": constraints,
        "operators": operators,
        "purposes": purposes,
        "negotiations": [],
        "offers": filtered_offers,
        "user": user_id,
        "user_type": user_type,
        "selected_negotiation_id": selected_negotiation_id,
    }
    return render(request, "admin_organization/configure.html", context=context)


def get_negotiations(request):
    # Ensure user is authenticated via token in session
    token = request.session.get("access_token")
    print(f"Token from session: {token}")
    user_id = request.session.get("user_id")
    print(f"User ID from session: {user_id}")
    user_type = request.session.get("user_type")
    print(f"User Type from session: {user_type}")

    # Construct API endpoint URL for fetching all negotiations
    negotiations_url = f"{API_BASE_URL}/negotiation"

    headers = {
        "Authorization": f"Bearer {token}"
    }

    # print(f'Negotiation API headers: {headers}')

    try:
        negotiations_res = requests.get(negotiations_url, headers=headers)
        negotiations_res.raise_for_status()  # Raise an error for bad responses
        # print(f"Negotiations response: {negotiations_res.status_code}")
        # print(f"Negotiations response content: {negotiations_res.text}")
        data = negotiations_res.json()
        # print(f"Negotiations data: {data}")

        return JsonResponse({"negotiations": data})

    except Exception as e:
        print(f"Error fetching negotiations: {e}")
        negotiations = []
        return JsonResponse({'error': 'Error fetching negotiations'}, status=500)


def get_offer(request):
    print('calling get_offer')
    offer_id = request.GET["offer_id"]

    # Ensure user is authenticated via token in session
    token = request.session.get("access_token")
    user_id = request.session.get("user_id")
    user_type = request.session.get("user_type")

    # Construct API endpoint URL
    endpoint_url = f"{API_BASE_URL}/provider/offer/{offer_id}"
    print(f"Endpoint URL: {endpoint_url}")

    headers = {
        "Authorization": f"Bearer {token}",
        "user-id": user_id
    }

    try:
        response = requests.get(endpoint_url, headers=headers)
        response.raise_for_status()  # Raise an error for bad responses
        print(f"Offers response: {response.status_code}")
        # print(f"Offers response content: {response.text}")
        data = response.json()

        odrl_policy = data.get("odrl_policy")
        if odrl_policy and "data" in odrl_policy:
            print(f'data from get_offer: {odrl_policy["data"]}')
        else:
            print(f'no data element in odrl of offer {offer_id}')

            if "odrl" in odrl_policy:
                # create data element if it does not exist
                output = custom_convert_odrl_policy(odrl_policy["odrl"])

            else:
                # create data element if it does not exist
                output = custom_convert_odrl_policy(odrl_policy)

            # insert into odrl_policy
            data["odrl_policy"]["data"] = output

        return JsonResponse(data)

    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        # You can log the error or handle it as needed
        print(f'Error fetching offer {offer_id}: {e}')
        return None


def get_negotiation_last_policy(request, negotiation_id=None, return_json=True):
    """
    Retrieve the last policy diff for a negotiation.
    When called via Django URLs we default to returning JsonResponse,
    but internal callers (e.g. gather_agreement_inputs) can request the raw dict.
    """
    print('calling get_negotiation_last_policy')
    negotiation_id = negotiation_id or request.GET.get("negotiation_id") or request.headers.get("negotiationid")

    if not negotiation_id:
        error_payload = {"error": "Missing negotiation_id"}
        return JsonResponse(error_payload, status=400) if return_json else error_payload
    # Construct API endpoint URL
    endpoint_url = f"{API_BASE_URL}/negotiation/{negotiation_id}/last-policy-diff"

    # Ensure user is authenticated via token in session
    token = request.session.get("access_token")
    user_id = request.session.get("user_id")
    user_type = request.session.get("user_type")

    headers = {
        "Authorization": f"Bearer {token}",
        "user-id": user_id,
    }

    try:
        # Make GET request to the API
        response = requests.get(endpoint_url, headers=headers)
        response.raise_for_status()  # Raise exception for HTTP errors

        # Parse JSON response
        data = response.json()
        last_policy = data.get("last_policy", {})
        odrl_policy = last_policy.get("odrl_policy")
        if odrl_policy and "data" in odrl_policy:
            print(f'data from get_offer: {odrl_policy["data"]}')
            # odrl_policy["data"] = filter_dicts_with_none_values(odrl_policy["data"])
        else:
            if "odrl" in odrl_policy:
                # create data element if it does not exist
                output = custom_convert_odrl_policy(odrl_policy["odrl"])
            else:
                output = custom_convert_odrl_policy(odrl_policy)
            # output = filter_dicts_with_none_values(output)
            # insert into odrl_policy
            data["last_policy"]["odrl_policy"]["data"] = output

        # print("\n \n get_negotiation_last_policy ====================\n",
        #       json.dumps(data["changes"], indent=2))

        if return_json:
            return JsonResponse(data)
        return data

    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        # You can log the error or handle it as needed
        print(f'Error fetching negotiation {negotiation_id}: {e}')
        return None


def get_penultimate_policy(request):
    negotiation_id = request.GET.get("negotiation_id")
    if not negotiation_id:
        return JsonResponse({"error": "negotiation_id query parameter is required"}, status=400)

    endpoint_url = f"{API_BASE_URL}/negotiation/{negotiation_id}/penultimate-policy"

    token = request.session.get("access_token")
    user_id = request.session.get("user_id")

    headers = {
        "Authorization": f"Bearer {token}",
        "user-id": user_id,
    }

    try:
        response = requests.get(endpoint_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        return JsonResponse(data, safe=False)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching penultimate policy for negotiation {negotiation_id}: {e}")
        status_code = getattr(e.response, "status_code", 500)
        try:
            error_payload = e.response.json()
        except Exception:
            error_payload = {"error": "Failed to retrieve penultimate policy"}
        return JsonResponse(error_payload, status=status_code)


def get_penultimate_policy_diff(request):
    negotiation_id = request.GET.get("negotiation_id")
    if not negotiation_id:
        return JsonResponse({"error": "negotiation_id query parameter is required"}, status=400)

    endpoint_url = f"{API_BASE_URL}/negotiation/{negotiation_id}/last-second-policy-diff"

    token = request.session.get("access_token")
    user_id = request.session.get("user_id")

    headers = {
        "Authorization": f"Bearer {token}",
        "user-id": user_id,
    }

    try:
        response = requests.get(endpoint_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        return JsonResponse(data, safe=False)
    except requests.exceptions.RequestException as e:
        print(f"Error fetching penultimate diff for negotiation {negotiation_id}: {e}")
        status_code = getattr(e.response, "status_code", 500)
        try:
            error_payload = e.response.json()
        except Exception:
            error_payload = {"error": "Failed to retrieve penultimate policy diff"}
        return JsonResponse(error_payload, status=status_code)


def update_policy(request):
    print('calling update_policy')

    # Ensure user is authenticated via token in session
    token = request.session.get("access_token")
    user_id = request.session.get("user_id")
    user_type = request.session.get("user_type")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Extract policy object from request body
    try:
        policy = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON in request body"}, status=400)

    print(f'Policy received: {policy.get("_id")}')
    policy_id = policy.get("_id")
    if not policy_id:
        return JsonResponse({"error": "Policy ID is required"}, status=400)

    negotiation_id = request.headers.get("negotiationid", "")

    if (policy["negotiation_id"] == ''):
        policy["negotiation_id"] = negotiation_id
    type = policy["type"]

    print(f'Type: {type}')

    translator = LogicTranslator()
    response = json.loads(request.body)
    # print(f'response["odrl_policy"]: {response["odrl_policy"]}')

    response_odrl_policy = response["odrl_policy"]

    # filtered_response = filter_dicts_with_none_values(response_odrl_policy)

    odrl = convert_list_to_odrl_jsonld_no_user(response_odrl_policy)
    print(f'odrl: {odrl}')

    try:
        odrl_parser = ODRLParser()
        policies = odrl_parser.parse_list([odrl])
        logic = translator.translate_policy(policies)
        policy["odrl_policy"] = {"odrl": odrl,
                                 "formal_logic": logic,
                                 "data": response_odrl_policy,
                                 # Add new section
                                 "custom_arrangement_section": policy.get("custom_arrangement_section", {}),
                                 "definitions": policy.get("definitions_section", {}),
                                 "custom_definitions": policy.get("custom_definitions_section", {}),
                                 }

        policy.pop("custom_arrangement_section")  # remove custom_arrangement_section session


    except BaseException as b:
        policy["odrl_policy"] = {"odrl": odrl}

    api_url = f"{API_BASE_URL}/provider/offer"

    try:

        # Make POST request to the API
        response = requests.put(api_url, json=policy, headers=headers)
        response.raise_for_status()  # Raise exception for HTTP errors

        # Parse JSON response
        api_response = response.json()

        try:
            _update_contract_if_present(policy, api_response)
        except Exception as exc:
            return JsonResponse(
                {"error": "Failed to update contract", "details": str(exc)},
                status=502
            )

        return JsonResponse(api_response)

    except requests.exceptions.HTTPError as e:
        print(f"HTTP error from API: {response.status_code} - {response.text}")
        return JsonResponse({"error": f"API error: {response.text}"}, status=response.status_code)

    except requests.exceptions.RequestException as e:
        print(f"Connection error: {e}")
        return JsonResponse({"error": "Failed to connect to API"}, status=500)


#
def create_policy(request):
    # negotiation_id = request.headers.get("negotiationid")
    # print(f'Negotiation ID: {negotiation_id}')

    type = request.headers.get("type")
    # print(f'Type: {type}')
    # policy = json.loads(request.body)
    # policy["negotiation_id"]=negotiation_id

    negotiation_id = request.headers.get("negotiationid")

    if negotiation_id == '':
        type = "request"

    policy_id = request.headers.get("policyid")
    policy = json.loads(request.body)

    policy["negotiation_id"] = negotiation_id

    translator = LogicTranslator()
    response = json.loads(request.body)

    filtered_response = response["odrl_policy"]
    filtered_response = filter_dicts_with_none_values(filtered_response)
    odrl = convert_list_to_odrl_jsonld_no_user(filtered_response)

    try:
        odrl_parser = ODRLParser()
        policies = odrl_parser.parse_list([odrl])
        logic = translator.translate_policy(policies)
        policy["odrl_policy"] = {"odrl": odrl,
                                 "formal_logic": logic,
                                 "data": filtered_response,
                                 # Add new section
                                 "custom_arrangement_section": policy.get("custom_arrangement_section", {}),
                                 "definitions": policy.get("definitions_section", {}),
                                 "custom_definitions": policy.get("custom_definitions_section", {})
                                 }

        policy.pop("custom_arrangement_section")  # remove custom_arrangement_section session
        # policy.pop("custom_definitions_section")  # remove

    except BaseException as b:
        print(b)
        policy["odrl_policy"] = {"odrl": odrl}

    # Ensure user is authenticated via token in session
    token = request.session.get("access_token")
    user_id = request.session.get("user_id")
    user_type = request.session.get("user_type")

    headers = {
        "Authorization": f"Bearer {token}",
        "user-id": user_id,
        "previous-policy-id": policy_id
    }

    print(f'\n\nHeaders: {headers}')

    if type == "request":
        api_endpoint = "/consumer/request/new"
        policy["consumer_id"] = user_id
    elif type == "offer":
        api_endpoint = "/provider/offer/new"
    else:
        # Handle invalid type parameter
        return JsonResponse({"error": "Invalid type parameter"}, status=400)

    api_url = f"{API_BASE_URL}" + api_endpoint

    try:

        # Make POST request to the API
        response = requests.post(api_url, json=policy, headers=headers)
        response.raise_for_status()  # Raise exception for HTTP errors

        # Parse JSON response
        api_response = response.json()
        # print(f'API Response: {api_response}')

        print(response.status_code)

        try:
            _update_contract_if_present(policy, api_response)
        except Exception as exc:
            return JsonResponse(
                {"error": "Failed to update contract", "details": str(exc)},
                status=502
            )

        return JsonResponse(api_response)

    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        # You can log the error or handle it as needed
        print(f'Error sending request to {api_url}: {e}')
        return JsonResponse({"error": "Failed to send request to remote API"}, status=500)


def create_policy_from_upload(request):
    print('calling create_policy_from_upload')

    policy = json.loads(request.body)
    print(type(policy))

    # Ensure user is authenticated via token in session
    token = request.session.get("access_token")
    user_id = request.session.get("user_id")
    user_type = request.session.get("user_type")

    headers = {
        "Authorization": f"Bearer {token}",
        "user-id": user_id,
    }

    print(f'Headers: {headers}')

    # api_endpoint = "/provider/offer/new"
    api_endpoint = "/provider/offer/initial_upcast_dataset"

    endpoint_url = f"{API_BASE_URL}"
    api_url = endpoint_url + api_endpoint
    print(f'API URL: {api_url}')

    try:
        # Make POST request to the API
        response = requests.post(api_url, json=policy, headers=headers)
        response.raise_for_status()  # Raise exception for HTTP errors

        # Parse JSON response
        api_response = response.json()
        # print(f'API Response: {api_response}')

        return JsonResponse(api_response)

    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        # You can log the error or handle it as needed
        print(f'Error sending request to {api_url}: {e}')
        print("422 details:", response.text)
        return JsonResponse({"error": "Failed to send request to remote API"}, status=500)


def get_text_diff(request):
    if request.method == 'POST':
        text1 = request.POST.get('text1')
        text2 = request.POST.get('text2')

        # Generate the full HTML diff
        diff = difflib.HtmlDiff().make_file(text1.splitlines(), text2.splitlines(), context=True, numlines=2)

        # Parse the HTML with BeautifulSoup
        soup = BeautifulSoup(diff, 'html.parser')

        # Find all table elements
        tables = soup.find_all('table')

        for table in tables:
            for td in table.find_all('td'):
                if 'nowrap' in td.attrs:
                    del td.attrs['nowrap']
                td.string = td.get_text().replace('\u00a0', ' ')

        # Convert the tables back to HTML
        tables_html = ''.join(str(table) for table in tables)

        # Extract the table using string operations
        start_index = diff.find('<body')
        end_index = diff.find('</body>', start_index) + len('</body>')

        table_content = diff[start_index:end_index]
        table_content = table_content.replace('&nbsp;', ' ')

        # Replace 'nowrap="nowrap"' with an empty string
        table_content = table_content.replace('nowrap="nowrap"', '')
        return JsonResponse({'diff': table_content})
    return JsonResponse({'error': 'Invalid request'}, status=400)


def _build_inline_diff(old_text, new_text, normalize_unicode=True):
    def normalize(value):
        if value is None:
            return ""
        if normalize_unicode:
            return unicodedata.normalize('NFC', value)
        return value

    def tokenize(value):
        if not value:
            return []
        return re.findall(r'\s+|\S+', value)

    def html_segment(segment):
        return html.escape(segment).replace('\n', '<br>')

    def summary_text(segment):
        if not segment:
            return ''
        flattened = ' '.join(segment.split())
        if not flattened:
            return ''
        return textwrap.shorten(flattened, width=160, placeholder='…')

    old_tokens = tokenize(normalize(old_text))
    new_tokens = tokenize(normalize(new_text))

    matcher = SequenceMatcher(a=old_tokens, b=new_tokens)

    combined_parts = []
    baseline_parts = []
    regenerated_parts = []
    summary_lines = []
    stats = {
        "deleted_segments": 0,
        "inserted_segments": 0,
        "replaced_segments": 0,
        "deleted_tokens": 0,
        "inserted_tokens": 0,
    }

    def wrap_diff_segment(text: str, class_name: str) -> str:
        if not text:
            return ''
        if text.strip() == '':
            return html_segment(text)
        return f'<span class="diff-segment {class_name}">{html_segment(text)}</span>'

    def build_inline_replace_parts(old_segment: str, new_segment: str):
        old_tokens_inline = tokenize(old_segment)
        new_tokens_inline = tokenize(new_segment)
        inline_matcher = SequenceMatcher(a=old_tokens_inline, b=new_tokens_inline)

        combined = []
        baseline_only = []
        regenerated_only = []

        for tag, i1, i2, j1, j2 in inline_matcher.get_opcodes():
            old_slice = ''.join(old_tokens_inline[i1:i2])
            new_slice = ''.join(new_tokens_inline[j1:j2])

            if tag == 'equal':
                segment_html = html_segment(old_slice)
                combined.append(segment_html)
                baseline_only.append(segment_html)
                regenerated_only.append(segment_html)
            if tag in ('delete', 'replace') and old_slice:
                wrapped = wrap_diff_segment(old_slice, 'del')
                combined.append(wrapped)
                baseline_only.append(wrapped)
            if tag in ('insert', 'replace') and new_slice:
                wrapped = wrap_diff_segment(new_slice, 'ins')
                combined.append(wrapped)
                regenerated_only.append(wrapped)

        return ''.join(combined), ''.join(baseline_only), ''.join(regenerated_only)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_segment = ''.join(old_tokens[i1:i2])
        new_segment = ''.join(new_tokens[j1:j2])
        old_summary = summary_text(old_segment)
        new_summary = summary_text(new_segment)

        if tag == 'equal':
            segment_html = html_segment(old_segment)
            combined_parts.append(segment_html)
            baseline_parts.append(segment_html)
            regenerated_parts.append(segment_html)
            continue

        if tag == 'delete':
            if old_segment:
                deleted_html = wrap_diff_segment(old_segment, 'del')
                combined_parts.append(deleted_html)
                baseline_parts.append(deleted_html)
            if old_summary:
                summary_lines.append(f'Deleted: {old_summary}')
                stats["deleted_segments"] += 1
                stats["deleted_tokens"] += max(1, len(tokenize(old_segment.strip())))
            continue

        if tag == 'insert':
            if new_segment:
                inserted_html = wrap_diff_segment(new_segment, 'ins')
                combined_parts.append(inserted_html)
                regenerated_parts.append(inserted_html)
            if new_summary:
                summary_lines.append(f'Inserted: {new_summary}')
                stats["inserted_segments"] += 1
                stats["inserted_tokens"] += max(1, len(tokenize(new_segment.strip())))
            continue

        if tag == 'replace':
            combined_html, baseline_html, regenerated_html = build_inline_replace_parts(old_segment, new_segment)
            if combined_html:
                combined_parts.append(combined_html)
            if baseline_html:
                baseline_parts.append(baseline_html)
            if regenerated_html:
                regenerated_parts.append(regenerated_html)

            if old_summary and new_summary:
                summary_lines.append(f'Replaced: {old_summary} \u2192 {new_summary}')
                stats["replaced_segments"] += 1
            elif old_summary:
                summary_lines.append(f'Deleted: {old_summary}')
            elif new_summary:
                summary_lines.append(f'Inserted: {new_summary}')

            if old_summary:
                stats["deleted_segments"] += 1
                stats["deleted_tokens"] += max(1, len(tokenize(old_segment.strip())))
            if new_summary:
                stats["inserted_segments"] += 1
                stats["inserted_tokens"] += max(1, len(tokenize(new_segment.strip())))

    diff_html = ''.join(combined_parts)
    if not diff_html.strip():
        diff_html = '<p>No textual differences were detected.</p>'

    baseline_html = ''.join(baseline_parts)
    if not baseline_html.strip():
        baseline_html = html_segment(old_text)

    regenerated_html = ''.join(regenerated_parts)
    if not regenerated_html.strip():
        regenerated_html = html_segment(new_text)

    change_segments = len(summary_lines)
    stats["segments"] = change_segments

    return diff_html, baseline_html, regenerated_html, summary_lines, change_segments, stats


@csrf_exempt
def get_text_diffs_for_agreement(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    try:
        payload = json.loads(request.body.decode('utf-8') if request.body else '{}')
    except json.JSONDecodeError:
        payload = {}

    previous_text = payload.get('previous_text')
    current_text = payload.get('current_text')
    normalize_unicode = payload.get('normalize_unicode', True)

    if previous_text is None:
        previous_text = request.POST.get('previous_text')
    if current_text is None:
        current_text = request.POST.get('current_text')

    if previous_text is None or current_text is None:
        return JsonResponse({'error': 'Both previous_text and current_text are required.'}, status=400)

    diff_html, baseline_html, regenerated_html, summary_lines, change_segments, stats = _build_inline_diff(
        previous_text,
        current_text,
        normalize_unicode=normalize_unicode
    )

    payload = {
        'diff_html': diff_html,
        'baseline_html': baseline_html,
        'regenerated_html': regenerated_html,
        'changes': summary_lines,
        'change_segments': change_segments,
        'stats': stats,
    }

    return JsonResponse(payload)


def has_none_value_on_first_level(d):
    """ Check if dictionary d has at least one None value on the first level """
    return any((value is None) or (value == '' and key == "value") for key, value in d.items())


def filter_dicts_with_none_values(data):
    """
    Recursively filter out dictionaries from data that have at least one None value on the first level.
    Handles nested lists and dictionaries.
    """
    if isinstance(data, list):
        filtered_list = []
        for item in data:
            if isinstance(item, dict):
                if not has_none_value_on_first_level(item):
                    filtered_list.append(filter_dicts_with_none_values(item))
            elif isinstance(item, list):
                filtered_list.append(filter_dicts_with_none_values(item))
            else:
                filtered_list.append(item)
        return filtered_list
    elif isinstance(data, dict):
        filtered_dict = {}
        for key, value in data.items():
            if isinstance(value, dict):
                if not has_none_value_on_first_level(value):
                    filtered_dict[key] = filter_dicts_with_none_values(value)
            elif isinstance(value, list):
                filtered_dict[key] = filter_dicts_with_none_values(value)
            else:
                filtered_dict[key] = value
        return filtered_dict
    else:
        return data


def _update_contract_if_present(policy_payload, api_response=None):
    """
    Push updated agreement data to the contract service when a contract id is available.
    """
    contract_info = policy_payload.get("contract_info")
    if not isinstance(contract_info, dict) or not contract_info:
        contract_info = policy_payload.get("agreement_data")
        if not isinstance(contract_info, dict):
            contract_info = {}

    contract_id = policy_payload.get("contract_id")
    if api_response and not contract_id:
        contract_id = api_response.get("contract_id")

    if not contract_id:
        print("No contract_id provided; skipping contract update.")
        return

    # Ensure essential structures exist even if the front end didn't send agreement data.
    contract_info.setdefault("contract_type", policy_payload.get("contract_type", "dsa"))
    contract_info.setdefault("resource_description", policy_payload.get("resource_description_object") or {})
    contract_info.setdefault("custom_clauses", policy_payload.get("custom_arrangement_section") or {})
    contract_info.setdefault("definitions", policy_payload.get("definitions_section") or {})
    contract_info.setdefault("custom_definitions", policy_payload.get("custom_definitions_section") or {})
    contract_info.setdefault("odrl_policy_summary", policy_payload.get("odrl_policy_summary", {}))
    contract_info.setdefault("dpw", policy_payload.get("data_processing_workflow_object") or {})
    if policy_payload.get("odrl_policy"):
        contract_info.setdefault("odrl", policy_payload["odrl_policy"])

    client_info = contract_info.setdefault("client_optional_info", {})
    negotiation_id = policy_payload.get("negotiation_id") or client_info.get("negotiation_id")
    if api_response:
        negotiation_id = api_response.get("negotiation_id") or negotiation_id
    if negotiation_id:
        client_info["negotiation_id"] = negotiation_id

    policy_identifier = (
            policy_payload.get("_id")
            or policy_payload.get("policy_id")
            or (api_response or {}).get("_id")
            or (api_response or {}).get("policy_id")
    )
    if policy_identifier:
        client_info["policy_id"] = str(policy_identifier)

    policy_type = policy_payload.get("type")
    if policy_type:
        client_info["type"] = policy_type

    client_info["updated_at"] = datetime.utcnow().isoformat()

    contract_info["contract_id"] = contract_id

    natural_language_document = policy_payload.get("natural_language_document")
    if natural_language_document:
        contract_info["natural_language_document"] = natural_language_document
        contract_info["nlp"] = natural_language_document

    policy_payload["contract_info"] = contract_info  # keep payload consistent for subsequent calls

    try:
        contract_service_interface.update_contract(contract_id, contract_info)
    except Exception as exc:
        print(f"Failed to update contract {contract_id}: {exc}")
        raise


def updatenegotiation(request):
    # Ensure user is authenticated via token in session
    token = request.session.get("access_token")
    user_id = request.session.get("user_id")
    user_type = request.session.get("user_type")

    headers = {
        "Authorization": f"Bearer {token}",
        "user-id": user_id,
    }

    # Extract request body data
    data = request.POST  # If you're sending data via POST form data
    data = json.loads(request.body)
    # Or
    # data = json.loads(request.body)  # If you're sending data via JSON
    party, action, negotiation_id = "", "", ""
    # Construct URL
    base_url = f"{API_BASE_URL}"
    if data["action"] == "terminate":
        url = f'{base_url}/negotiation/terminate/{data["negotiationId"]}'
    else:
        url = f'{base_url}/negotiation/{data["party"]}/{data["action"]}/{data["negotiationId"]}'

    try:
        # Make POST request
        response = requests.post(url, data=data, headers=headers)
        response.raise_for_status()  # Raise exception for HTTP errors

        # Parse JSON response
        result = response.json()
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# Contract Service
contract_service_interface = ContractAPIService()


def _payload_diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    changes = {}
    excluded_keys = {'id', '_id', 'type', 'uid', 'created_at', 'updated_at',
                     "policy_id", "updated_at", "uid",
                     "created_at", "custom_clauses",
                     "custom_definitions", "contacts", "contract_type", "client_optional_info",
                     "contract_id", "type", "formal_logic", "odrl_policy_summary",
                     "natural_language_document",
                     "agreement_payload_current"}

    if len(old) == 0:
        return changes

    for key in new:
        if key in excluded_keys:
            continue
        if key in old:
            if isinstance(new[key], dict) and isinstance(old[key], dict):
                sub_changes = _payload_diff(old[key], new[key])
                if sub_changes:
                    changes[key] = sub_changes
            elif new[key] != old[key]:
                changes[key] = {"from": old[key], "to": new[key]}
        else:
            changes[key] = {"from": None, "to": new[key]}

    for key in old:
        if key in excluded_keys:
            continue
        if key not in new:
            changes[key] = {"from": old[key], "to": None}

    print("\n _payload_diff: \n", changes)
    return changes


async def save_signature_into_contract(user_id: str, user_role: str, negotiation_id: str, signature_data: str):
    """
    Sends a signature payload to the agreement service.
    Raises requests.exceptions.RequestException on failure.
    """

    dataform = {
        "user_id": user_id,
        "user_role": user_role,
        f"{user_role}_signature": signature_data,
        f"{user_role}_signature_date": str(datetime.utcnow()),
    }

    try:

        res = await contract_service_interface.sign_contract(negotiation_id, dataform)
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Agreement API error: {exc}")

    return res


async def save_signature(request):
    """Save the signature into Contract collection"""

    signature_data = request.POST.get("signature")
    negotiation_id = request.headers.get("negotiationid")

    token = request.session.get("access_token")
    user_id = request.session.get("user_id")
    user_role = request.session.get("user_type")

    print(f"save_signature function, user_id={user_id}, user_role = {user_role}, "
          f"negotiation_id={negotiation_id} \n signature_data={signature_data}")

    try:
        # sign a signature to contract

        if not signature_data:
            return JsonResponse({"error": "Missing signature"}, status=400)
        if not negotiation_id:
            return JsonResponse({"error": "Missing negotiationid header"}, status=400)
        if user_role not in ("provider", "consumer"):
            return JsonResponse({"error": f"Unsupported user role: {user_role}"}, status=400)

        print("to sign a signature to contract!!")

        ret = await save_signature_into_contract(user_id=user_id, user_role=user_role, negotiation_id=negotiation_id,
                                                 signature_data=signature_data)

        if ret["contract_id"]:

            print("save a signature into contract collection successfully!", ret)
        else:

            print(ret["message"])

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Agreement API error: {str(e)}")

    return JsonResponse(
        {
            "message": "Signature saved successfully",
            "signature_data": signature_data
        },
        status=200,
    )


def get_users_details(token, consumer_id, provider_id):
    contacts = {}

    # User profile data comes from the authentication service.
    # Old code:
    # _url = f"{API_BASE_URL}/user/details/"
    _url = f"{API_AUTHENTICATION_URL}/user/details/"

    headers = {
        "Authorization": f"Bearer {token}",
    }

    def fetch_user(uid):
        if not uid:
            return None
        try:
            r = requests.get(_url, headers=headers, params={"user_id": uid}, timeout=8)
            if r.ok:
                return r.json()
        except Exception:
            pass
        return None

    c = fetch_user(consumer_id)
    if c:
        print("get consumer details successfully!!")
        contacts["consumer"] = c

    p = fetch_user(provider_id)
    if p:
        print("get provider details successfully!!")
        contacts["provider"] = p

    return contacts


def gather_agreement_inputs(request):
    """
    Retrieve agreement information from the front end, translate ODRL policy,
    summarize rules (convert each ODRL to natural language description), and return a JSON response.
    """

    negotiation_id = request.headers.get("negotiationid")
    policy_type = request.headers.get("type")  # e.g. "request"
    policy_id = request.headers.get("policyid")

    payload = json.loads(request.body)

    removed_custom_clauses = {
        str(key) for key in (payload.get("custom_arrangement_removed") or []) if key
    }
    removed_custom_definitions = {
        str(key) for key in (payload.get("custom_definitions_removed") or []) if key
    }

    # Ensure negotiation_id is set
    if not payload.get("negotiation_id"):
        payload["negotiation_id"] = negotiation_id

    payload["updated_at"] = datetime.utcnow().isoformat()

    # Build ODRL JSON-LD
    filtered_data = filter_dicts_with_none_values(payload.get("odrl_policy", []))
    odrl = convert_list_to_odrl_jsonld_no_user(filtered_data)

    # odrl = convert_list_to_odrl_jsonld_no_user(payload.get("odrl_policy", []))

    payload["odrl_policy"] = {"odrl": odrl}

    # Ensure user is authenticated via token in session
    token = request.session.get("access_token")
    user_id = request.session.get("user_id")
    user_type = request.session.get("user_type")

    if policy_type == "request":
        payload["consumer_id"] = user_id

    if policy_type == "offer":
        payload["provider_id"] = user_id

    contacts = get_users_details(token, payload.get("consumer_id"), payload.get("provider_id"))
    # Ensure contacts is at least a dict
    if contacts is None:
        contacts = {}

    if not isinstance(contacts, dict):
        raise ValueError(f"get_users_details() returned non-dict: {type(contacts)} -> {contacts!r}")

    consumer_id = payload.get("consumer_id")
    provider_id = payload.get("provider_id")

    # Make sure the expected sub-dicts exist
    contacts.setdefault("consumer", {})
    contacts.setdefault("provider", {})

    if consumer_id:
        contacts["consumer"]["consumer_id"] = consumer_id
    else:
        # optional: log or handle missing consumer_id
        # logger.warning("Missing consumer_id in payload: %r", payload)
        contacts["consumer"]["consumer_id"] = None

    if provider_id:
        contacts["provider"]["provider_id"] = provider_id
    else:
        # optional: log or handle missing provider_id
        # logger.warning("Missing provider_id in payload: %r", payload)
        contacts["provider"]["provider_id"] = None

    # Summarize ODRL rules
    odrl_policy = payload.get("odrl_policy", {}).get("odrl", {})

    # to call APIs get description and definitions
    extract_res = contract_service_interface.get_des_by_odrl_translation(odrl)

    rule_summary = extract_res.get("odrl_des")
    definitions = extract_res.get("definitions")

    custom_definitions = {}
    for key, items in payload.get("custom_definitions_section", {}).items():

        if key not in custom_definitions:
            custom_definitions[key] = items

    custom_clauses = {}
    # Include any custom arrangement sections (from front end)
    for key, items in payload.get("custom_arrangement_section", {}).items():
        rule_summary[key] = items
        custom_clauses[key] = items

    vp = payload.get("validity_period")
    if vp in (None, "null", "None", ""):
        validity_period = 12
    else:
        validity_period = vp

    contract_type = payload.get("contract_type")
    if contract_type is None:
        contract_type = "dsa"

    agreement_data = {

        "client_optional_info": {
            "negotiation_id": payload.get("negotiation_id"),
            "policy_id": policy_id,
            "type": policy_type,
            "updated_at": payload.get("updated_at"),
        },
        "contract_type": contract_type,
        "validity_period": validity_period,
        "notice_period": payload.get("notice_period", 30),
        "contacts": contacts,
        "resource_description": payload.get("resource_description_object"),

        "definitions": definitions,
        "custom_definitions": custom_definitions,
        "odrl_policy_summary": rule_summary,
        "custom_clauses": custom_clauses,
        "odrl": odrl_policy,
        "dpw": payload.get("data_processing_workflow_object", {}),

    }

    agreement_display = deepcopy(agreement_data)
    current_snapshot = deepcopy(agreement_data)

    # Initial NLP generation, obtaining all info form front end
    payload["nlp"] = ""
    previous_payload = payload.get("agreement_payload_current")
    payload["agreement_payload_current"] = previous_payload
    payload_diff = _payload_diff(previous_payload, current_snapshot) if previous_payload else {}
    payload["agreement_payload_changes"] = payload_diff

    # Prefer client-provided custom sections; avoid redundant API calls
    # Only fetch from last policy if no client-provided custom sections AND no prior baseline to merge.
    has_client_custom_sections = bool(payload.get("custom_arrangement_section")) or bool(
        payload.get("custom_definitions_section"))
    if (not has_client_custom_sections) and (not previous_payload) and payload.get("negotiation_id"):
        last_policy_obj = get_negotiation_last_policy(
            request,
            negotiation_id=payload["negotiation_id"],
            return_json=False,
        ) or {}

        last_policy = last_policy_obj.get("last_policy") or {}

        custom_last = last_policy.get("odrl_policy", {}).get("custom_arrangement_section", {}) if last_policy else {}
        for key, items in custom_last.items():
            if key not in custom_clauses and key not in removed_custom_clauses:
                agreement_display["odrl_policy_summary"][key] = items
                agreement_display["custom_clauses"][key] = items

        custom_definitions_last = last_policy.get("odrl_policy", {}).get("custom_definitions",
                                                                         {}) if last_policy else {}
        for key, items in custom_definitions_last.items():
            if key not in agreement_display["custom_definitions"] and key not in removed_custom_definitions:
                agreement_display["custom_definitions"][key] = items

    # Merge with previous baseline from session (no extra API call needed)
    if previous_payload:
        previous_custom_clauses = previous_payload.get("custom_clauses") or {}
        for key, items in previous_custom_clauses.items():

            if key not in custom_clauses and key not in removed_custom_clauses:
                agreement_display["odrl_policy_summary"][key] = items
                agreement_display["custom_clauses"][key] = items

        previous_custom_definitions = previous_payload.get("custom_definitions") or {}
        for key, items in previous_custom_definitions.items():

            if key not in agreement_display["custom_definitions"] and key not in removed_custom_definitions:
                agreement_display["custom_definitions"][key] = items

    payload["agreement_data"] = agreement_display
    return JsonResponse(payload)


# old function to generate an agreement (not using Contract Service API)
# @login_required(login_url="login")
# def generate_legal_agreement(request):
#     print("Create contract without API")
#     policy = json.loads(request.body)
#
#     nlp_text = get_contract_text(policy)
#     # print("generate_legal_agreement->nlp_text : \n", nlp_text)
#     policy["natural_language_document"] = nlp_text
#
#     return JsonResponse(policy)

# to call Contract Service API
def generate_legal_agreement(request):
    print("to call API generating a contract!")
    # parse JSON
    try:
        token = request.session.get("access_token")
        user_id = request.session.get("user_id")
        user_type = request.session.get("user_type")

        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    negotiation_id = request.headers.get("negotiationid", "")
    body.setdefault("client_optional_info", {})["type"] = request.headers.get("type")
    if not body["client_optional_info"].get("negotiation_id"):
        body["client_optional_info"]["negotiation_id"] = negotiation_id

    try:
        contract_obj = contract_service_interface.create_contract(
            user_id=str(user_id),
            json_data=body
        )

        print(f"\nthe contract {contract_obj.get('contract_id')} has been created.\n")
        agreement_payload = body.get("agreement_data") or body
        # Keep session baseline for backward-compat UI flows; client will send it back explicitly.
        request.session["agreement_payload_current"] = agreement_payload

    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Agreement API error: {exc}")

    def serialize_payload(value):
        try:
            return json.loads(json.dumps(value, default=str))
        except Exception:
            return value

    # Return the fresh baseline so the client can persist and send it on gathers
    contract_obj["agreement_payload_current"] = serialize_payload(agreement_payload)

    return JsonResponse(contract_obj)


async def download_contract(request):
    user_id = request.session.get("user_id")
    if not user_id:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    negotiation_id = request.headers.get("negotiationid") or request.GET.get("negotiation_id") or ""
    if not negotiation_id:
        return JsonResponse({"error": "Missing negotiation ID"}, status=400)

    try:
        pdf_bytes = await contract_service_interface.down_contract(
            user_id=str(user_id),
            negotiation_id=negotiation_id
        )
    except requests.exceptions.RequestException as exc:
        return JsonResponse({"error": f"Agreement API error: {exc}"}, status=502)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=500)

    if not pdf_bytes:
        return JsonResponse({"error": "Agreement not found"}, status=404)

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="negotiation_agreement_{negotiation_id}.pdf"'
    return response


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATACONTROLLER_PROCESSOR")
# def ajax_use_case_ontology_classes(request):
#     selected_option = request.GET.get("selected_option")
#     # ontology = read_ontology(selected_option, None)

#     ontology_classes = use_case_ontology_classes(selected_option)
#     return JsonResponse({"ontology_classes": ontology_classes})


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATACONTROLLER_PROCESSOR")
# def submit_consent_form(request):
#     response = json.loads(request.body)
#     ConsentRequest.create(response)
#     return JsonResponse(response)


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATA_PROVIDER")
# def userdataprofile(request):
#     data_subject_data_list = DataSubjectData.objects.filter(
#         consent_given_by=request.user.id, consent_revoked_date__isnull=True
#     ).values_list("data_subject_data", flat=True)
#     context = {"sensors": SensorData.objects.all(), "consents": data_subject_data_list}
#     return render(request, "users/user-sensor-data-profile.html", context=context)


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATA_PROVIDER")
# def saveconsent(request):
#     """
#     This function is used to save the user or the data subject information regarding
#     the sensors or the data that data subject has.
#     """
#     if request.method == "POST":
#         selected_sensors = request.POST.getlist("sensor")
#         for s in selected_sensors:
#             # Data you want to insert or update
#             data = {
#                 "data_subject_data": s,
#                 "consent_status": True,
#                 "consent_given_date": date.today(),
#                 "consent_given_by": request.user.id,
#                 "consent_revoked_date": None,
#             }

#             # Try to get a record that matches 'data_subject_data' and 'consent_given_by'
#             # If it doesn't exist, create a new one
#             data_subject, created = DataSubjectData.objects.get_or_create(
#                 data_subject_data=data["data_subject_data"],
#                 consent_given_by=data["consent_given_by"],
#                 defaults=data,
#             )

#             # If the record already existed, update it with the new data
#             if not created:
#                 DataSubjectData.objects.filter(id=data_subject.id).update(**data)

#         # Update the records that are not in the 'sensors_to_keep' list
#         DataSubjectData.objects.exclude(data_subject_data__in=selected_sensors).update(
#             consent_status=False, consent_revoked_date=date.today()
#         )
#     #        messages.success(request, "Consent Updated!")
#     return redirect("userdataprofile")


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATACONTROLLER_PROCESSOR")
# def get_purpose_processing_data_ajax(request):
#     if request.method == "POST":
#         request_data = json.loads(request.body)  # request.POST
#         from owlready2 import World

#         purposeprocessingworld = World()
#         dataworld = World()
#         try:
#             dataschema_ontology = read_ontology(
#                 request_data["selectedOntology"]["data_schema_ontology"], dataworld
#             )
#             default_ontology = read_ontology(
#                 request_data["selectedOntology"]["default_ontology"]
#             )
#             domain_ontology = read_ontology(
#                 request_data["selectedOntology"]["domain_ontology"],
#                 purposeprocessingworld,
#             )

#             if request_data["type"] == "purposeprocessing":
#                 fetched_data_source_ontology_data = ontology_data_to_dict_tree(
#                     dataschema_ontology,
#                     root="datasource",
#                     class_first_name="datasource",
#                     class_second_name=None,
#                 )

#                 fetched_data_processing_default_ontology = ontology_data_to_dict_tree(
#                     default_ontology,
#                     root="processing",
#                     class_first_name="processing",
#                     class_second_name=None,
#                 )
#                 fetched_data_processing_domain_ontology = ontology_data_to_dict_tree(
#                     domain_ontology,
#                     root="processing",
#                     class_first_name="processing",
#                     class_second_name=None,
#                 )
#                 combined_processing_operations = merge_dictionaries(
#                     fetched_data_processing_default_ontology,
#                     fetched_data_processing_domain_ontology,
#                 )
#                 fetched_data_purpose_default_ontology = ontology_data_to_dict_tree(
#                     default_ontology,
#                     root="purpose",
#                     class_first_name="purpose",
#                     class_second_name=None,
#                 )

#                 fetched_data_purpose_domain_ontology = ontology_data_to_dict_tree(
#                     domain_ontology,
#                     root="purpose",
#                     class_first_name="purpose",
#                     class_second_name=None,
#                 )

#                 combined_purposes = merge_dictionaries(
#                     fetched_data_purpose_default_ontology,
#                     fetched_data_purpose_domain_ontology,
#                 )

#             fetched_data = {
#                 "processing": combined_processing_operations,
#                 "purpose": combined_purposes,
#                 "datasource": fetched_data_source_ontology_data,
#             }
#             return JsonResponse({"data": fetched_data})
#         except Exception as e:
#             print(
#                 f"Issue with ontology. Cannot read. Please select different ontology. Error: {e}."
#             )

# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATACONTROLLER_PROCESSOR")
# def uploadontology(request):
#     if request.method == "POST":
#         name = request.POST.get("name")
#         file = request.FILES.get("ontologyfile")
#         ontology_type = request.POST.get("ontologytype")
#         print(f"file is ={file}")

#         if len(name) < 4 or len(name) > 20:
#             messages.error(
#                 request, "Ontology name should be between 4 and 50 charcters."
#             )
#             return redirect("uploadontology")

#         if file is None:
#             messages.error(
#                 request, "You must upload an ontology file in an owl or rdf format."
#             )
#             return redirect("uploadontology")

#         if not (str(file).endswith(".owl") or str(file).endswith(".rdf")):
#             messages.error(request, "You can only upload an owl or rdf file.")
#             return redirect("uploadontology")

#         savedata = OntologyUpload()
#         savedata.name = name
#         savedata.ontology_type = ontology_type
#         savedata.created_by = request.user
#         savedata.file = file
#         savedata.save()

#         """
#         Read the ontology and convert it to a dictionary tree"""
#         if ontology_type == "DATA_SCHEMA":
#             dataschema_ontology = read_ontology(str(savedata.file))
#             data_sources = ontology_data_to_dict_tree(
#                 dataschema_ontology,
#                 root="datasource",
#                 class_first_name="datasource",
#                 class_second_name=None,
#             )
#             data_list = convert_to_list(data_sources)

#             for item in data_list:
#                 if not SensorData.objects.filter(sensor_data=item).exists():
#                     # Data does not exist, insert it
#                     SensorData.objects.create(sensor_data=item)
#                 else:
#                     # Data already exists, do nothing
#                     pass

#         messages.success(request, "File uploaded.")
#         return redirect("uploadontology")

#     return render(request, "admin_organization/ontology_upload.html")

# def create_rule_dataset_no_user(request):
#     rules = get_rules_from_odrl("./media/default_ontology/ODRL22.rdf")
#     actors = get_actors_from_dpv("./media/default_ontology/dpv.rdf")
#     actions = get_actions_from_odrl("./media/default_ontology/ODRL22.rdf")
#     targets = get_dataset_titles_and_uris("./media/default_ontology/Datasets.ttl")
#     constraints = get_constraints_types_from_odrl("./media/default_ontology/ODRL22.rdf")
#     purposes = get_purposes_from_dpv("./media/default_ontology/dpv.rdf")
#     operators = get_operators_from_odrl("./media/default_ontology/ODRL22.rdf")

#     rules.append({"label": "Obligation", "uri": "http://www.w3.org/ns/odrl/2/Obligation"})

#     context = {
#         "rules": rules,
#         "actors": actors,
#         "actions": actions,
#         "targets": targets,
#         "constraints": constraints,
#         "operators": operators,
#         "purposes": purposes,
#     }
#     return render(request, "../templates/policy/policy.html", context=context)

# def extract_logic_expressions_page(request):

#     return render(request, "../templates/policy/logic.html")

# def extract_logic_expressions(request):
#     translator = LogicTranslator()
#     incoming_request = translator.odrl.parse_list(json.loads(str(request.body, "UTF")))
#     print (incoming_request)
#     result = translator.translate_policy(incoming_request)
#     # return JsonResponse({"logic_expression":result})


# return JsonResponse(
#     {
#         "logic_expression": result
#     }
# )

# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATACONTROLLER_PROCESSOR")
# def viewontology(request):
#     ontologies = OntologyUpload.objects.filter(created_by=request.user)
#     if ontologies.exists():
#         print("ontologies exists")
#     context = {"ontologies": ontologies}
#     return render(request, "admin_organization/view_ontology.html", context=context)


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATACONTROLLER_PROCESSOR")
# def deleteconsentrequestform(request, consentform_id):
#     """
#     This function is used to delete the consent request form. However, it is important to note that we are not deleting the forms, just deactivating it.
#     The reason for this is that later for the audit purpose, we need to keep the record of the consent request form.
#     :param request:
#     :param consentform_id: form id
#     :return:
#     """
#     try:
#         consentform = ConsentRequest.objects.get(id=consentform_id)
#         consentform.consent_form_delete_status = "DELETED"
#         consentform.save()
#         return redirect("datacontrollerconfiguredprivacylists")
#     except Exception as e:
#         return HttpResponseServerError(f"Error.{consentform_id, request.user, e}")


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATACONTROLLER_PROCESSOR")
# def deleteontology(request, ontology_id):
#     try:
#         ontology = OntologyUpload.objects.get(pk=ontology_id, created_by=request.user)
#         # Get the file path from the model instance
#         file_path = ontology.file
#         print(f"file path is {file_path}, type is {type(file_path)} ")
#         # Delete the file from db
#         ontology.delete()
#         # delete file from storage
#         try:
#             os.remove(os.path.join(settings.MEDIA_ROOT, str(file_path)))
#         except OSError as e:
#             HttpResponseServerError(f"Error deleting file: {e}")
#         messages.success(request, "Ontology deleted.")
#         return redirect("viewontology")
#     except ObjectDoesNotExist:
#         return HttpResponseServerError("Ontology does not exist.")


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATACONTROLLER_PROCESSOR")
# def configuredprivacylists(request):
#     consent_request_form = ConsentRequest.objects.filter(
#         consent_requested_by=request.user, consent_form_delete_status="ACTIVE"
#     )
#     context = {"consentforms": consent_request_form, "users": get_all_users()}
#     return render(
#         request,
#         "admin_organization/configured-sent-consents-rule.html",
#         context=context,
#     )


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATACONTROLLER_PROCESSOR")
# def send_consent_to_selected_user(request):
#     if request.method == "POST":
#         try:
#             request_data = json.loads(request.body)
#             consentform = ConsentRequest.objects.get(id=request_data["consentform"])

#             requested_data_from_controller = consentform.consent_data
#             requested_data_from_controller = requested_data_from_controller.strip("[]")
#             # Split the string by commas and remove extra spaces
#             requested_data_from_controller_list = [
#                 s.strip() for s in requested_data_from_controller.split(",")
#             ]
#             fixed_list_requested_data_from_controller = [
#                 s.strip("'") for s in requested_data_from_controller_list
#             ]
#             # peform the data checks with the user and the consent request form
#             success_usr = 0
#             for user in request_data["selected_users"]:
#                 data_subject_data_list = list(
#                     DataSubjectData.objects.filter(
#                         consent_given_by=user, consent_revoked_date__isnull=True
#                     ).values_list("data_subject_data", flat=True)
#                 )

#                 does_data_match = match_user_data_with_controller_request_data(
#                     data_subject_data_list, fixed_list_requested_data_from_controller
#                 )
#                 print("+" * 100)
#                 print("does_data_match", does_data_match)
#                 print("+" * 100)
#                 if (
#                     does_data_match
#                 ):  # if the data matches, then send the consent request form to the user
#                     ConsentRequestFormSendToUser.objects.create(
#                         consent_requestform=ConsentRequest.objects.get(
#                             id=request_data["consentform"]
#                         ),
#                         consent_request_form_sent_to=User.objects.get(id=user),
#                         consent_answer_status="REQUESTED",
#                         consent_given_status="Requested",
#                         additional_constraints={},
#                     )
#                     success_usr += 1

#                 # update the consent request form status
#                 consentform = ConsentRequest.objects.get(id=request_data["consentform"])
#                 consentform.consent_request_sent_status = "SENT"
#                 consentform.save()

#             if success_usr > 0:
#                 return JsonResponse(
#                     {
#                         "success": True,
#                         "message": f"Consent request sent to {success_usr}/{len(request_data['selected_users'])} the selected user(s).",
#                     }
#                 )
#             else:
#                 return JsonResponse(
#                     {
#                         "success": False,
#                         "message": "Consent request cannot be sent. Reason: The requested data from the controller do not match with the available users data.",
#                     }
#                 )

#         except Exception as b:
#             return b


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATACONTROLLER_PROCESSOR")
# def view_consent_form(request, consent_form_id):
#     consentform = ConsentRequest.objects.get(id=consent_form_id)
#     return render(
#         request,
#         "admin_organization/view-consent-form.html",
#         {"consentform": consentform},
#     )


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATA_PROVIDER")
# def view_consent_request_user(request):
#     consent_request = ConsentRequestFormSendToUser.objects.filter(
#         consent_request_form_sent_to=request.user
#     )
#     context = {"consent_requests": consent_request}

#     return render(request, "users/consent-request.html", context=context)


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATA_PROVIDER")
# def view_consent_request_user_single(request, consent_request_id):
#     consent_request = ConsentRequestFormSendToUser.objects.get(id=consent_request_id)
#     custom_restrictions = consent_request.consent_requestform.additional_requests
#     consent_given_status = consent_request.consent_given_status
#     consent_additional_permission_status = consent_request.additional_constraints
#     if consent_given_status == "Requested":
#         list_of_rules = sentence_rule_permission_status(custom_restrictions)
#     else:
#         list_of_rules = sentence_rule_permission_status_revoke(
#             consent_additional_permission_status
#         )

#     if consent_request.consent_answer_status == "REVOKED":
#         return render(
#             request,
#             "users/consent-view-response-revoke.html",
#             {
#                 "consent_request": consent_request,
#                 "custom_restrictions": list_of_rules,
#                 "has_custom_restrictions": len(list_of_rules),
#             },
#         )
#     elif (
#         consent_request.consent_answer_status == "RESPONDED"
#         and consent_given_status == "NotGiven"
#     ):
#         return render(
#             request,
#             "users/consent-view-response-revoke.html",
#             {
#                 "consent_request": consent_request,
#                 "custom_restrictions": list_of_rules,
#                 "has_custom_restrictions": len(list_of_rules),
#             },
#         )

#     else:
#         return render(
#             request,
#             "users/consent-request-single.html",
#             {
#                 "consent_request": consent_request,
#                 "custom_restrictions": list_of_rules,
#                 "has_custom_restrictions": len(list_of_rules),
#             },
#         )


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATA_PROVIDER")
# def save_user_consent_response_data(request):
#     if request.method == "POST":
#         response = json.loads(request.body)
#         consent_request_form_id = ConsentRequestFormSendToUser.objects.get(
#             id=response["consent_requestform_id"]
#         )
#         consenting_user = request.user
#         dataprocessor_controller = User.objects.get(
#             id=response["data_processor_controller_id"]
#         )
#         # to update to responsed
#         changeformstatusresponse = ConsentRequestFormSendToUser.objects.get(
#             id=response["consent_requestform_id"],
#             consent_request_form_sent_to=consenting_user,
#         )

#         if (
#             changeformstatusresponse.consent_given_status == "Requested"
#             and changeformstatusresponse.consent_answer_status == "REQUESTED"
#         ):
#             changeformstatusresponse.consent_answer_status = "RESPONDED"
#         if (
#             changeformstatusresponse.consent_given_status == "Given"
#             and response["consentwithadditioalconstraintsresponse"]["consent"][
#                 "consentgivenstatus"
#             ]
#             == "NotGiven"
#         ):
#             changeformstatusresponse.consent_answer_status = "REVOKED"
#             # update ODRL response
#             updateODRL = ConsentRequestFormResponseODRL.objects.get(
#                 consentrequestsendtouserformid=consent_request_form_id,
#                 data_controller_processor_id=dataprocessor_controller,
#                 consented_by_user=request.user,
#             )

#             updateODRL.odrl_consent_additional_constraints = (
#                 convert_user_consent_to_odrl(
#                     response["consentwithadditioalconstraintsresponse"]
#                 )
#             )
#             updateODRL.save()

#         else:
#             # new respose so crete a new one
#             ConsentRequestFormResponseODRL.objects.create(
#                 odrl_consent_additional_constraints=convert_user_consent_to_odrl(
#                     response["consentwithadditioalconstraintsresponse"]
#                 ),
#                 data_controller_processor_id=dataprocessor_controller,
#                 consentrequestsendtouserformid=consent_request_form_id,
#                 consented_by_user=request.user,
#             )

#         changeformstatusresponse.additional_constraints = response[
#             "consentwithadditioalconstraintsresponse"
#         ]["additional_constraints"]
#         changeformstatusresponse.consent_given_status = response[
#             "consentwithadditioalconstraintsresponse"
#         ]["consent"]["consentgivenstatus"]


#         changeformstatusresponse.save()

#         return JsonResponse({"success": True, "message": "Consent response saved."})


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATACONTROLLER_PROCESSOR")
# def view_responses_controller_processor_odrl(request):
#     odrl_responses = ConsentRequestFormResponseODRL.objects.filter(
#         data_controller_processor_id=request.user
#     )
#     return render(
#         request,
#         "admin_organization/view-odrl-response-list.html",
#         {"odrl_responses": odrl_responses},
#     )


# @login_required(login_url="login")
# @user_passes_test(lambda u: u.role == "DATACONTROLLER_PROCESSOR")
# def view_responses_controller_processor_odrl_single(request, odrl_id):
#     odrl_response = ConsentRequestFormResponseODRL.objects.get(id=odrl_id)
#     pretty_json = json.dumps(
#         odrl_response.odrl_consent_additional_constraints, indent=2
#     )
#     return render(
#         request,
#         "admin_organization/odrl-single.html",
#         {"odrl_response": odrl_response, "pretty_json": pretty_json},
#     )


###policy editor views###

def ajax_get_properties_from_properties_file(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            uri = data.get("uri")
            fields = get_properties_of_a_class(uri)
            return JsonResponse({"fields": fields}, status=200)
        except BaseException as e:
            return JsonResponse({"error": str(e)}, status=400)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)


###Recommender agent views###
def create_agent_record(request):
    # Ensure user is authenticated via token in session
    token = request.session.get("access_token")
    user_id = request.session.get("user_id")
    user_type = request.session.get("user_type")

    headers = {
        "Authorization": f"Bearer {token}",
        "user-id": user_id
    }

    endpoint_url = f"{API_BASE_URL}/agent/new"

    body = json.loads(request.body)

    preferences = body.get("preferences")
    negotiation_id = body.get("negotiation_id")
    original_offer_id = body.get("original_offer_id")
    print('preferences', preferences)
    print('negotiation_id', negotiation_id)
    print('original_offer_id', original_offer_id)

    print('type', user_type)

    try:

        create_new_agent_body = {
            "negotiation_id": negotiation_id,
            "original_offer_id": original_offer_id,
            "agent_type": user_type,
            "preferences": preferences,
        }

        # Make POST request to the API
        response = requests.post(endpoint_url, json=create_new_agent_body, headers=headers)
        response.raise_for_status()  # Raise exception for HTTP errors

        # Parse JSON response
        api_response = response.json()

        # print(f"API Response: {api_response}")

        return JsonResponse(api_response)

    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        # You can log the error or handle it as needed
        print(f'Error sending request to {endpoint_url}: {e}')
        return JsonResponse({"error": "Failed to send request to remote API"}, status=500)


def get_agent_record(request):
    # Ensure user is authenticated via token in session
    token = request.session.get("access_token")
    user_id = request.session.get("user_id")
    user_type = request.session.get("user_type")

    headers = {
        "Authorization": f"Bearer {token}",
        "user-id": user_id
    }
    negotiation_id = request.GET["negotiation_id"]
    endpoint_url = f"{API_BASE_URL}/agent/latest/{negotiation_id}"

    try:
        # Make GET request to the API
        response = requests.get(endpoint_url, headers=headers)
        response.raise_for_status()  # Raise exception for HTTP errors

        # Parse JSON response
        data = response.json()

        # print(f'data from get_agent_record view: {data}')

        return JsonResponse(data, safe=False)

    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        # You can log the error or handle it as needed
        print(f'Error fetching agent record for negotiation id {negotiation_id}: {e}')
        return None
