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

import requests
from bs4 import BeautifulSoup
from django.shortcuts import render
from PolicyEngine.Parsers import ODRLParser
from PolicyEngine.Translators import LogicTranslator
from .helper import convert_user_consent_to_odrl
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils.encoding import force_str
from .helper import generate_token
import json
from django.views.decorators.csrf import csrf_exempt
from .helper import (
    sentence_rule_permission_status,
    sentence_rule_permission_status_revoke,
)
from .helper import get_all_users
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth import authenticate, login, logout
from .models import OntologyUpload, ConsentRequest
from .models import SensorData, ConsentRequestFormSendToUser
from .models import DataSubjectData
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseServerError
from django.http import JsonResponse
from .models import ConsentRequestFormResponseODRL
from .helper import match_user_data_with_controller_request_data
from .helper import convert_to_list
from custom_accounts.helper import merge_dictionaries
from custom_accounts.ajax_ontology import (
    read_ontology,
    use_case_ontology_classes,
    get_rules_from_odrl,
    get_actions_from_odrl,
    get_dataset_titles_and_uris,
    get_constraints_types_from_odrl,
    get_operators_from_odrl,
    convert_list_to_odrl_jsonld,
    get_purposes_from_dpv,
    get_actors_from_dpv, get_fields_from_datasets, convert_list_to_odrl_jsonld_no_user, get_properties_of_a_class,
    populate_graph, get_action_hierarchy_from_odrl, populate_content_to_graph, get_actor_hierarchy_from_dpv,
    get_purpose_hierarchy_from_dpv, get_constraints_for_instances,
    normalize_odrl_graph,
    custom_convert_odrl_policy,
    process_rule,
)
from custom_accounts.ajax_ontology import ontology_data_to_dict_tree
import os

# because of the custom user model
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.contrib import messages
from django.core.mail import EmailMessage
from privux import settings
from django.contrib.sites.shortcuts import get_current_site
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.decorators import login_required
from datetime import date
import os

API_BASE_URL = os.environ.get("API_BASE_URL")
if not API_BASE_URL:
    raise ValueError("API_BASE_URL environment variable is not set.")

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

        # Call FastAPI to verify the token
        verify_url = f"{API_BASE_URL}/user/verify-token/"
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

        if not username or not password:
            messages.error(request, "Please enter both username and password.")
            return redirect("login")

        url = f"{API_BASE_URL}/user/login/"
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
        
        data = {
            "name": user_name,
            "type": user_type,
            "username_email": email,
            "password": password
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
        
        endpoint_url = f"{API_BASE_URL}/user/register/"
        
        try:
            response = requests.post(f"{endpoint_url}?master_password_input={master_password}", 
                                     json=data)
            if response.status_code in [200, 201]:
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
    
    endpoint_url = f"{API_BASE_URL}/user/logout/"
    
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
            return JsonResponse({"fields":fields})
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
    token = request.session.get("access_token")
    user_id = request.session.get("user_id")
    user_type = request.session.get("user_type")
    
    # Fallback: Check URL parameters for authentication
    if not token or not user_id:
        token = request.GET.get("access_token")
        user_id = request.GET.get("user_id")
        user_type = request.GET.get("user_type")
        
        # If URL parameters provided, verify token and set session
        if token and user_id:
            try:
                # Verify token with FastAPI
                verify_url = f"{API_BASE_URL}/user/verify-token/"
                verify_res = requests.post(verify_url, data=token, headers={"Content-Type": "text/plain"})
                
                if verify_res.status_code == 200:
                    # Token is valid, set session for future requests
                    request.session["access_token"] = token
                    request.session["user_id"] = user_id
                    request.session["user_type"] = user_type or "provider"
                    print(f"✅ Session set from URL parameters for user {user_id}")
                else:
                    print(f"❌ Token verification failed: {verify_res.status_code}")
                    return redirect("login")
            except Exception as e:
                print(f"❌ Error verifying token: {e}")
                return redirect("login")
    
    if not token or not user_id:
        return redirect("login") 
    
    selected_negotiation_id = request.GET.get("negotiation_id", None)

    # populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/ODRL22.rdf")),"xml")
    # populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/dpv.ttl")),"turtle")
    # populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/dpv.rdf")),"xml")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/ODRL_DPV.rdf")),"xml")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/Datasets.ttl")),"turtle")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/Datasets_with_metadata.ttl")),"turtle")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/AdditionalProperties.ttl")),"turtle")
    # populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/CactusOntology.rdf")),"xml")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/CactusOntology.ttl")),"ttl")
    populate_graph((os.path.join(settings.MEDIA_ROOT, "default_ontology/foaf.rdf")),"xml")

    
    # Prepare data for context
    rules = get_rules_from_odrl()
    actors = get_actor_hierarchy_from_dpv()
    actions = get_action_hierarchy_from_odrl()
    targets = get_dataset_titles_and_uris()
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
    except Exception as e:
        print(f"Error fetching offers: {e}")
        offers = []


    context = {
        "datarequestedby": user_id,
        "rules": rules,
        "actors": actors[0:1],
        "actions": actions,
        "targets": targets,
        "constraints": constraints,
        "operators": operators,
        "purposes": purposes,
        "negotiations": [],
        "offers": offers,
        "user": user_id,
        "user_type": user_type,
        "selected_negotiation_id": selected_negotiation_id,
    }
    return render(request, "admin_organization/configure.html", context=context)


def save_signature(request):
    if request.method == 'POST':
        signature_data = request.POST.get('signature')
        # Here you can save the signature_data to MongoDB or any other storage

        # Dummy response for demonstration
        response_data = {'message': 'Signature saved successfully'}
        return JsonResponse(response_data)
    else:
        return JsonResponse({'error': 'Invalid request'})



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
        
        return JsonResponse({"negotiations" : data})
    
    except Exception as e:
        print(f"Error fetching negotiations: {e}")
        negotiations = []
        return JsonResponse({'error': 'Error fetching negotiations'}, status=500)
    

def get_offer(request):
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
            
            # create data element if it does not exist
            output = custom_convert_odrl_policy(odrl_policy["odrl"])
            
            print(f'output from custom_convert_odrl_policy: {output}')
            
            # insert into odrl_policy
            data["odrl_policy"]["data"] = output
            
            formatted_data = json.dumps(data, indent=2)
            
            print(f'Formatted data: {formatted_data}')
            

        return JsonResponse(data)
    
    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        # You can log the error or handle it as needed
        print(f'Error fetching offer {offer_id}: {e}')
        return None


def get_negotiation_last_policy(request):
    negotiation_id = request.GET["negotiation_id"]
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
        
        print(f'data from get_negotiation_last_policy: {data}')

        return JsonResponse(data)

    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        # You can log the error or handle it as needed
        print(f'Error fetching negotiation {negotiation_id}: {e}')
        return None


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
        policy["negotiation_id"]=negotiation_id
    type = policy["type"]
    
    print(f'Type: {type}')

    translator = LogicTranslator()
    response = json.loads(request.body)
    filtered_response = filter_dicts_with_none_values(response["odrl_policy"])
    odrl = convert_list_to_odrl_jsonld_no_user(filtered_response)

    try:
        odrl_parser = ODRLParser()
        policies = odrl_parser.parse_list([odrl])
        logic = translator.translate_policy(policies)
        policy["odrl_policy"] = {"odrl": odrl, "formal_logic": logic, "data": filtered_response}
    except BaseException as b:
        policy["odrl_policy"] = {"odrl": odrl}

    # Construct API endpoint
    # endpoint_url = "http://localhost:8002/negotiation-api/provider/offer"
    # if type == "request":
    # # if user_type == 'consumer':
    #     api_endpoint = f"/consumer/request/{policy_id}"
    #     policy["consumer_id"] = user_id

    # if type == "offer":
    # # if user_type == 'provider':
    #     api_endpoint = f"/provider/offer/{policy_id}"
    #     policy["provider_id"] = user_id
    # else:
    #     # Handle invalid type parameter
    #     return JsonResponse({"error": "Invalid type parameter"}, status=400)

    # api_url = endpoint_url + api_endpoint
    
    api_url = f"{API_BASE_URL}/provider/offer"

    try:

        # Make POST request to the API
        response = requests.put(api_url, json=policy, headers=headers)
        response.raise_for_status()  # Raise exception for HTTP errors

        # Parse JSON response
        api_response = response.json()

        return JsonResponse(api_response)

    except requests.exceptions.HTTPError as e:
        print(f"HTTP error from API: {response.status_code} - {response.text}")
        return JsonResponse({"error": f"API error: {response.text}"}, status=response.status_code)

    except requests.exceptions.RequestException as e:
        print(f"Connection error: {e}")
        return JsonResponse({"error": "Failed to connect to API"}, status=500)



def create_policy(request):
    
    type = request.headers.get("type")
        
    negotiation_id = request.headers.get("negotiationid")
    
    if negotiation_id =='':
        type = "request"
        
    policy_id = request.headers.get("policyid")
    policy = json.loads(request.body)
    policy["negotiation_id"]=negotiation_id
    
    translator = LogicTranslator()
    response = json.loads(request.body)
    filtered_response = filter_dicts_with_none_values(response["odrl_policy"])
    odrl = convert_list_to_odrl_jsonld_no_user(filtered_response)

    try:
        odrl_parser = ODRLParser()
        policies = odrl_parser.parse_list([odrl])
        logic = translator.translate_policy(policies)
        policy["odrl_policy"] = {"odrl": odrl, "formal_logic": logic, "data": filtered_response}
    except BaseException as b:
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
    
    print(f'Headers: {headers}')
    

    if type == "request":
        api_endpoint = "/consumer/request/new"
        policy["consumer_id"] = user_id
    elif type == "offer":
        api_endpoint = "/provider/offer/new"
    else:
        # Handle invalid type parameter
        return JsonResponse({"error": "Invalid type parameter"}, status=400)

    endpoint_url = f"{API_BASE_URL}"
    api_url = endpoint_url + api_endpoint

    try:

        # Make POST request to the API
        response = requests.post(api_url, json=policy, headers=headers)
        response.raise_for_status()  # Raise exception for HTTP errors

        # Parse JSON response
        api_response = response.json()
        print(f'API Response: {api_response}')

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
    
    api_endpoint = "/provider/offer/new"

    endpoint_url = f"{API_BASE_URL}"
    api_url = endpoint_url + api_endpoint
    print(f'API URL: {api_url}')

    try:
        # Make POST request to the API
        response = requests.post(api_url, json=policy, headers=headers)
        response.raise_for_status()  # Raise exception for HTTP errors

        # Parse JSON response
        api_response = response.json()
        print(f'API Response: {api_response}')

        return JsonResponse(api_response)

    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        # You can log the error or handle it as needed
        print(f'Error sending request to {api_url}: {e}')
        print("422 details:", response.text)
        return JsonResponse({"error": "Failed to send request to remote API"}, status=500)


# def text_diff(request):
#     return render(request, 'admin_organization/textdiff.html')

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
    party, action, negotiation_id = "","",""
    # Construct URL
    base_url = f"{API_BASE_URL}"
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
        
        print(f"API Response: {api_response}")

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
        
        print(f'data from get_agent_record view: {data}')

        return JsonResponse(data, safe=False)

    except requests.exceptions.RequestException as e:
        # Handle request exceptions
        # You can log the error or handle it as needed
        print(f'Error fetching agent record for negotiation id {negotiation_id}: {e}')
        return None  
    
      