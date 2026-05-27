import asyncio
import json
import os
import time
import traceback
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any

import httpx
import jwt
import requests
from bson import ObjectId
from bson.errors import InvalidId
from confluent_kafka import Producer, KafkaException
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi import FastAPI
from fastapi import Header, Body, Query
from fastapi import Path
from fastapi import status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from pydantic import BaseModel, ValidationError
from pydantic import Field
from rdflib import Graph
from starlette.responses import JSONResponse
from starlette.responses import Response

from keycloak_auth.auth import decode_keycloak_token
from keycloak_auth.user_mapping import resolve_or_create_local_user_async


from data_model import User, UpcastNegotiationObject, UpcastPolicyObject, PolicyDiffObject, PolicyDiffResponse, \
    UpcastPolicyConverter, PolicyType, \
    PartyType, NegotiationStatus, pydantic_to_dict, Preference, PolicyKey, RecommenderAgentRecord, \
    NegotiationCreationRequest
from odrl_conversion_utility import odrl_convertor
from recommender.agent import Proposal
from recommender.agent import new_offer, new_request

secure = True

import logging
logger = logging.getLogger(__name__)


logging.basicConfig(
    level=logging.INFO,  # You can change this to DEBUG for more detailed output
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Load environment variables from .env file
root_path = "/negotiation-api"
app = FastAPI(
    title="Negotiation Plugin API",
    description="UPCAST Negotiation Plugin API",
    version="1.0",
    root_path=root_path
)

origins = ["*",
           "http://127.0.0.1:8000",
           "http://localhost:8000",
           "http://62.171.168.208:8000",
           "http://62.171.168.208:8001",
           "http://62.171.168.208:8002",
           "http://127.0.0.1:8001",
           "http://localhost:8001",
           # "http://10.22.38.111:8001",
           ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables from .env file
load_dotenv(dotenv_path=".env")

KEYCLOAK_ISSUER = os.getenv("KEYCLOAK_ISSUER", "").rstrip("/")
KEYCLOAK_JWKS_URL = os.getenv("KEYCLOAK_JWKS_URL") or (
    f"{KEYCLOAK_ISSUER}/protocol/openid-connect/certs" if KEYCLOAK_ISSUER else ""
)
KEYCLOAK_AUDIENCE = os.getenv("KEYCLOAK_AUDIENCE", "")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
KEYCLOAK_TOKEN_URL = os.getenv("KEYCLOAK_TOKEN_URL") or (
    f"{KEYCLOAK_ISSUER}/protocol/openid-connect/token" if KEYCLOAK_ISSUER else f"{root_path}/user/login/"
)
# Swagger UI works more reliably when it posts credentials to a local endpoint
# that can inject Keycloak client settings such as client_id/client_secret.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=root_path + "/user/login/")

# Define Kafka broker configuration
# kafka_conf = {
#     'bootstrap.servers': os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
#     'security.protocol': os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
# }

kafka_conf = {
    'bootstrap.servers': os.getenv("KAFKA_BOOTSTRAP_SERVERS"),
    'security.protocol': os.getenv("KAFKA_SECURITY_PROTOCOL"),
    'sasl.mechanism': os.getenv("KAFKA_SASL_MECHANISM"),
    'sasl.username': os.getenv("KAFKA_SASL_USERNAME"),
    'sasl.password': os.getenv("KAFKA_SASL_PASSWORD")
}

kafka_enabled = False
push_consumer_enabled = True
push_provider_enabled = True
# Create Producer instance
try:
    producer = Producer(kafka_conf)
    producer.list_topics(timeout=2)  # Set a timeout to avoid blocking indefinitely
    kafka_enabled = True
except KafkaException as e:
    print(f"Kafka Producer error: {e}")
    kafka_enabled = False
    producer = None  # Ensure the provider is not used further

MONGO_USER = os.getenv("MONGO_USER")
print(f'MONGO_USER {MONGO_USER}')
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
print(f'MONGO_PASSWORD {MONGO_PASSWORD}')
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
print(f'MONGO_HOST {MONGO_HOST}')
MONGO_PORT = os.getenv("MONGO_PORT")
print(f'MONGO_PORT {MONGO_PORT}')
MONGO_DB = os.getenv("MONGO_DB", "dips_services")
print(f'MONGO_DB {MONGO_DB}')
if MONGO_PORT:  # Assumption: A local or remote installation of MongoDB is provided.
    MONGO_PORT = int(MONGO_PORT)
    MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}"
else:  # Assumption: The database is stored in mongodb cloud.
    MONGO_URI = f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}/?retryWrites=true&w=majority&appName=Cluster0"

DJANGO_BASE_URL = os.getenv("DJANGO_BASE_URL")
CONTRACT_BASE_URL = os.getenv("API_CONTRACT_SERVICE_URL")
LOGIN_URL = f"{DJANGO_BASE_URL}/negotiation/login"
DEFAULT_CONTRACT_TYPE = os.getenv("CONTRACT_DEFAULT_TYPE", "dsa")
DEFAULT_CONTRACT_CACTUS_FORMAT = int(os.getenv("CONTRACT_CACTUS_FORMAT", "0"))
DEFAULT_CONTRACT_NOTICE_PERIOD = int(os.getenv("CONTRACT_NOTICE_PERIOD", "30"))
DEFAULT_CONTRACT_VALIDITY_PERIOD = int(os.getenv("CONTRACT_VALIDITY_PERIOD", "12"))

client = AsyncIOMotorClient(MONGO_URI)
print(f'MONGO_URI {MONGO_URI}')
db = client[MONGO_DB]
print(f'db {db}')
negotiations_collection = db.negotiations
requests_collection = db.requests
offers_collection = db.offers
policy_collection = db.policies
contracts_collection = db.contracts
users_collection = db.users
agent_records_collection = db.agent_records
print(f'agents_collection {agent_records_collection}')
print(f'users_collection {users_collection}')

SECRET_KEY = os.getenv("SECRET_KEY", "fallback_key")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 180

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
blacklist = {}

router = APIRouter()
def build_contract_service_headers(access_token: Optional[str], extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    # Old code called contract-service without bearer authentication.
    # New code forwards the same token received by negotiation-api.
    headers = dict(extra_headers or {})
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return headers


# Password Hashing Functions
def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# JWT Creation Function
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta if expires_delta else timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


import re


async def is_strong_password(password):
    # Check length
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."

    # Check for uppercase, lowercase, digit, and special character
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r'\d', password):
        return False, "Password must contain at least one digit."
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character."

    return True, "Password is strong."


async def verify_master(master_password_input):
    # Check for existing admin user
    admin_user = await users_collection.find_one({"is_admin": True})

    if admin_user is not None:
        # Use the admin's hashed password as the master password
        master_password = admin_user.get("password")
        print("master_password", master_password)
    else:
        # Use the master password from the environment variable
        raw_master_password = os.getenv("MASTER_PASSWORD")
        if not raw_master_password:
            raise HTTPException(
                status_code=500, detail="MASTER_PASSWORD environment variable not set"
            )

        master_password = get_password_hash(raw_master_password)

        # Initialize the first admin user if no admin exists
        first_admin = {
            "username_email": "admin@example.com",
            "password": master_password,
            "is_admin": True
        }
        await users_collection.insert_one(first_admin)

    if not verify_password(master_password_input, master_password):
        raise HTTPException(status_code=403, detail="Invalid master password")

    return True


async def verify_access_token_and_resolve_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        if not KEYCLOAK_ISSUER or not KEYCLOAK_JWKS_URL:
            raise HTTPException(status_code=503, detail="Keycloak authentication is not configured")
        payload = decode_keycloak_token(
            token,
            issuer=KEYCLOAK_ISSUER,
            jwks_url=KEYCLOAK_JWKS_URL,
            audience=KEYCLOAK_AUDIENCE or None,
            verify_aud=bool(KEYCLOAK_AUDIENCE),
            logger=logger,
        )
        email: Optional[str] = payload.get("email")
        sub: Optional[str] = payload.get("sub")
        if email is None or sub is None:
            raise credentials_exception
    except HTTPException:
        raise
    except Exception:
        raise credentials_exception

    user = await resolve_or_create_local_user_async(
        users_collection,
        payload,
        logger,
        include_audit_fields=False,
    )

    return User(**user)


async def verify_negotiation_access(negotiation_id, user_id, role=None):
    """
    Verify user has access to a negotiation.

    Args:
        negotiation_id: The negotiation ID
        user_id: The current user ID
        role: Optional specific role requirement ('user', 'consumer', 'provider')

    Returns:
        The negotiation object if access is granted

    Raises:
        HTTPException if access is denied
    """
    query = {"_id": ObjectId(negotiation_id)}

    if role == 'user':
        query["user_id"] = ObjectId(user_id)
    elif role == 'consumer':
        query["consumer_id"] = ObjectId(user_id)
    elif role == 'provider':
        query["provider_id"] = ObjectId(user_id)
    else:
        # Any role is acceptable
        query["$or"] = [
            {"user_id": ObjectId(user_id)},
            {"consumer_id": ObjectId(user_id)},
            {"provider_id": ObjectId(user_id)}
        ]

    negotiation = await negotiations_collection.find_one(query)

    if not negotiation:
        raise HTTPException(
            status_code=404,
            detail="Negotiation not found or you don't have permission to access it"
        )

    return negotiation


def _extract_contact_details(user_doc: Dict[str, Any], role: str) -> Dict[str, Any]:
    if not user_doc:
        return {}

    allowed_fields = [
        "name",
        "type",
        "username_email",
        "organization",
        "incorporation",
        "address",
        "vat_no",
        "position_title",
        "phone",
        "citizenship",
        "passport_id",
    ]
    contact = {field: user_doc.get(field) for field in allowed_fields}

    uid = user_doc.get("_id")
    if uid is not None:
        contact["_id"] = str(uid)
        key = "consumer_id" if role == "consumer" else "provider_id"
        contact[key] = str(uid)

    return contact


def _policy_resource_description(policy: UpcastPolicyObject) -> Dict[str, Any]:
    source = {}
    if getattr(policy, "resource_description_object", None):
        try:
            source = policy.resource_description_object.dict()
        except AttributeError:
            source = policy.resource_description_object or {}

    keys = [
        "title",
        "price",
        "price_unit",
        "uri",
        "policy_url",
        "environmental_cost_of_generation",
        "environmental_cost_of_serving",
        "description",
        "type_of_data",
        "data_format",
        "data_size",
        "geographic_scope",
        "tags",
        "publisher",
        "theme",
        "distribution",
    ]
    sanitized = {k: source.get(k) for k in keys}

    price_value = source.get("price")
    if price_value is not None:
        try:
            sanitized["price"] = f"{float(price_value):.2f}"
        except (ValueError, TypeError):
            sanitized["price"] = str(price_value)
    else:
        sanitized["price"] = ""

    sanitized.pop("created_at", None)
    sanitized.pop("updated_at", None)

    return sanitized


def _policy_odrl_section(policy: UpcastPolicyObject) -> Dict[str, Any]:
    odrl_payload = policy.odrl_policy or {}
    if isinstance(odrl_payload, dict) and "odrl" in odrl_payload:
        return odrl_payload["odrl"]
    return odrl_payload


def _coerce_positive_int(value: Any, fallback: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
            return parsed if parsed > 0 else fallback
        except ValueError:
            return fallback
    if isinstance(value, dict):
        for key in ("value", "duration", "months", "period"):
            candidate = value.get(key)
            if candidate is not None:
                return _coerce_positive_int(candidate, fallback)
    return fallback


def _build_contract_request(
        policy: UpcastPolicyObject,
        negotiation_id: ObjectId,
        request_id: str,
        consumer_doc: Dict[str, Any],
        provider_doc: Dict[str, Any],
) -> Dict[str, Any]:
    timestamp = datetime.utcnow().isoformat()

    return {
        "contract_type": policy.contract_type or DEFAULT_CONTRACT_TYPE,
        "client_optional_info": {
            "negotiation_id": str(negotiation_id),
            "policy_id": request_id,
            "type": policy.type or PolicyType.REQUEST.value,
            "updated_at": timestamp,
        },
        "cactus_format": DEFAULT_CONTRACT_CACTUS_FORMAT,
        "validity_period": _coerce_positive_int(policy.validity_period, DEFAULT_CONTRACT_VALIDITY_PERIOD),
        "notice_period": DEFAULT_CONTRACT_NOTICE_PERIOD,
        "contacts": {
            "consumer": _extract_contact_details(consumer_doc, "consumer"),
            "provider": _extract_contact_details(provider_doc, "provider"),
        },
        "resource_description": _policy_resource_description(policy),
        "definitions": {},
        "custom_clauses": {},
        "dpw": policy.data_processing_workflow_object or {},
        "odrl": _policy_odrl_section(policy),
    }


async def _fetch_contract_payload(contract_id: str, access_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not CONTRACT_BASE_URL:
        raise HTTPException(status_code=500, detail="Contract service URL not configured")

    endpoint_url = f"{CONTRACT_BASE_URL.rstrip('/')}/contract/get_request_body/{contract_id}"
    timeout = httpx.Timeout(15.0, connect=5.0, read=10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        headers = build_contract_service_headers(access_token)
        resp = await client.get(endpoint_url, headers=headers)

    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Contract service error ({resp.status_code}): {resp.text}")

    payload = resp.json()
    payload.pop("_id", None)
    payload.pop("id", None)
    payload.pop("contractid", None)
    return payload


async def _update_contract_document(
        contract_oid: ObjectId,
        policy: UpcastPolicyObject,
        negotiation_id: ObjectId,
        policy_id: str,
        consumer_doc: Dict[str, Any],
        provider_doc: Dict[str, Any],
        access_token: Optional[str] = None,
) -> Optional[str]:
    contract_id_str = str(contract_oid)
    payload = await _fetch_contract_payload(contract_id_str, access_token=access_token) or {}

    payload["contract_type"] = policy.contract_type or payload.get("contract_type") or DEFAULT_CONTRACT_TYPE
    payload["validity_period"] = _coerce_positive_int(
        policy.validity_period,
        payload.get("validity_period") or DEFAULT_CONTRACT_VALIDITY_PERIOD,
    )
    payload["notice_period"] = payload.get("notice_period") or DEFAULT_CONTRACT_NOTICE_PERIOD
    payload["contacts"] = {
        "consumer": _extract_contact_details(consumer_doc, "consumer"),
        "provider": _extract_contact_details(provider_doc, "provider"),
    }
    payload["resource_description"] = _policy_resource_description(policy)
    payload.setdefault("definitions", {})
    payload.setdefault("custom_clauses", {})
    payload["dpw"] = policy.data_processing_workflow_object or payload.get("dpw") or {}
    payload["odrl"] = _policy_odrl_section(policy)

    client_info = payload.setdefault("client_optional_info", {})
    client_info["negotiation_id"] = str(negotiation_id)
    client_info["policy_id"] = policy_id
    client_info["type"] = policy.type or client_info.get("type") or PolicyType.REQUEST.value
    client_info["updated_at"] = datetime.utcnow().isoformat()

    if policy.natural_language_document:
        payload["nlp"] = policy.natural_language_document

    payload["contract_id"] = contract_id_str

    endpoint_url = f"{CONTRACT_BASE_URL.rstrip('/')}/contract/update/{contract_id_str}"
    timeout = httpx.Timeout(20.0, connect=5.0, read=15.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        headers = build_contract_service_headers(access_token)
        resp = await client.put(endpoint_url, json=payload, headers=headers)
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Contract service error ({resp.status_code}): {resp.text}")

    updated_text: Optional[str] = None
    try:
        resp_payload = resp.json()
        updated_text = resp_payload.get("legal_contract") or resp_payload.get("nlp")
    except ValueError:
        updated_text = None

    return updated_text


async def _maybe_generate_contract_for_policy(
        policy: UpcastPolicyObject,
        negotiation_id: ObjectId,
        policy_id: str,
        access_token: Optional[str] = None,
) -> tuple[Optional[ObjectId], Optional[str]]:

    existing_contract = getattr(policy, "contract_id", None)
    contract_obj_id: Optional[ObjectId] = None
    contract_text: Optional[str] = None

    try:
        consumer_doc = await users_collection.find_one({"_id": ObjectId(policy.consumer_id)})
        provider_doc = await users_collection.find_one({"_id": ObjectId(policy.provider_id)})
        if not consumer_doc or not provider_doc:
            raise ValueError("Associated users not found for contract generation")

        if existing_contract:
            try:
                contract_obj_id = ObjectId(str(existing_contract))
            except (InvalidId, TypeError):
                contract_obj_id = None
        print("\ncontract_obj_id: ", contract_obj_id)
        if contract_obj_id:
            updated_contract_text = await _update_contract_document(
                contract_obj_id,
                policy,
                negotiation_id,
                policy_id,
                consumer_doc,
                provider_doc,
                access_token=access_token,
            )
            policy.contract_id = contract_obj_id
            if updated_contract_text:
                policy.natural_language_document = updated_contract_text
            return contract_obj_id, policy.natural_language_document

        contract_id_str, contract_text = await _request_contract_creation(
            policy=policy,
            negotiation_id=negotiation_id,
            request_id=policy_id,
            consumer_doc=consumer_doc,
            provider_doc=provider_doc,
            access_token=access_token,
        )
        contract_obj_id = ObjectId(contract_id_str)
        policy.contract_id = contract_obj_id
        if contract_text:
            policy.natural_language_document = contract_text
    except Exception as exc:
        print(f"Failed to synchronize contract for negotiation {negotiation_id}: {exc}")
        contract_obj_id = None
        contract_text = None

    return contract_obj_id, contract_text


async def _request_contract_creation(
        policy: UpcastPolicyObject,
        negotiation_id: ObjectId,
        request_id: str,
        consumer_doc: Dict[str, Any],
        provider_doc: Dict[str, Any],
        access_token: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    if not CONTRACT_BASE_URL:
        raise HTTPException(status_code=500, detail="Contract service URL not configured")

    payload = _build_contract_request(
        policy,
        negotiation_id,
        request_id,
        consumer_doc,
        provider_doc,
    )
    # print("Contract creation payload:", json.dumps(payload, default=str))
    endpoint_url = f"{CONTRACT_BASE_URL.rstrip('/')}/contract/create"
    timeout = httpx.Timeout(20.0, connect=5.0, read=15.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            headers = build_contract_service_headers(access_token)
            response = await client.post(endpoint_url, json=payload, headers=headers)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Unable to reach contract service: {exc}") from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Contract service error ({response.status_code}): {response.text}",
        )

    response_data = response.json()
    contract_id = response_data.get("contract_id")
    if not contract_id:
        raise HTTPException(status_code=502, detail="Contract service did not return a contract_id")

    contract_text = response_data.get("legal_contract") or response_data.get("nlp")

    return contract_id, contract_text


@router.post("/user/sso-provision/")
async def sso_provision(
        sub: str = Body(...),
        email: str = Body(...),
        name: str = Body(...),
        user_type: str = Body(default="provider"),
):
    # Old code created or updated the local Mongo user and then minted an
    # internal HS256 JWT for Negotiation-Tool.
    #
    # New code:
    # Keycloak is now the authentication authority, so negotiation-api must not
    # issue a second auth token. Keep the endpoint only as an explicit marker
    # that the old exchange flow is retired.
    raise HTTPException(
        status_code=501,
        detail="SSO provisioning no longer mints local tokens. Use the Keycloak access token directly.",
    )


# User Login
@router.post("/user/login/")
async def login_user(form_data: OAuth2PasswordRequestForm = Depends()):
    # Old code authenticated users against MongoDB and issued a local JWT.
    #
    # New code:
    # negotiation-api proxies Swagger/UI password login to Keycloak so docs can
    # still use the built-in "Authorize" flow while injecting the correct
    # Keycloak client settings.
    if not KEYCLOAK_TOKEN_URL or not KEYCLOAK_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Keycloak login is not configured")

    form_payload = {
        "client_id": KEYCLOAK_CLIENT_ID,
        "grant_type": "password",
        "username": form_data.username,
        "password": form_data.password,
    }
    requested_scopes = [scope for scope in (form_data.scopes or []) if scope]
    for required_scope in ("openid", "profile", "email"):
        if required_scope not in requested_scopes:
            requested_scopes.append(required_scope)
    form_payload["scope"] = " ".join(requested_scopes)
    if KEYCLOAK_CLIENT_SECRET:
        form_payload["client_secret"] = KEYCLOAK_CLIENT_SECRET

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(KEYCLOAK_TOKEN_URL, data=form_payload)

    if response.status_code >= 400:
        try:
            detail = response.json().get("error_description") or response.json().get("detail") or "Incorrect username or password"
        except Exception:
            detail = response.text or "Incorrect username or password"
        raise HTTPException(status_code=response.status_code, detail=detail)

    return response.json()


@router.post("/user/logout/")
async def logout_user(request: Request):
    # Old code blacklisted locally-issued JWTs.
    #
    # New code:
    # logout is handled by Keycloak. negotiation-api remains stateless and the
    # caller should clear its local session.
    return {"message": "Logout is handled by Keycloak."}


# Decode token helper
def decode_access_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def is_token_blacklisted(token: str):
    if token in blacklist:
        # Check if the token's expiry has passed
        if datetime.utcnow().timestamp() > blacklist[token]:
            del blacklist[token]  # Clean up expired token
            return False
        return True
    return False


@router.post("/consumer/recommend", summary="Recommend a request", response_model=Proposal)
def consumer_recommend(
        # current_user: User = Depends(verify_access_token_and_resolve_user),
        body: RecommenderAgentRecord = Body(..., description="The recommender agent record")
):
    result = new_request(body)
    return result


@router.post("/provider/recommend", summary="Recommend a request", response_model=Proposal)
def provider_recommend(
        # current_user: User = Depends(verify_access_token_and_resolve_user),
        body: RecommenderAgentRecord = Body(..., description="The recommender agent record")
):
    result = new_offer(body)
    return result


@router.post("/negotiation/create", summary="Create a negotiation")
async def create_upcast_negotiation(current_user: User = Depends(verify_access_token_and_resolve_user),
                                    token: str = Depends(oauth2_scheme),
                                    body: UpcastPolicyObject = Body(..., description="The request object")
                                    ):
    try:
        conflict_status = "no conflict"

        # Retrieve consumer and provider objects from users_collection
        consumer = await users_collection.find_one({"_id": ObjectId(body.consumer_id)})
        provider = await users_collection.find_one({"_id": ObjectId(body.provider_id)})

        if consumer is None or provider is None:
            raise HTTPException(status_code=404, detail="Consumer or provider not found")

        # Normalise ODRL payload before persistence
        body = odrl_convertor(body)

        body.type = PolicyType.REQUEST.value
        # Save the offer to MongoDB

        body.consumer_id = ObjectId(str(body.consumer_id))
        body.provider_id = ObjectId(str(body.provider_id))

        now = datetime.utcnow()
        # body["created_at"] = now
        # body["updated_at"] = now
        result = await policy_collection.insert_one(pydantic_to_dict(body))
        # Retrieve the generated _id
        request_id = str(result.inserted_id)

        negotiation_id = ObjectId()
        contract_text = None
        contract_object_id = None
        try:
            contract_id_str, contract_text = await _request_contract_creation(
                policy=body,
                negotiation_id=negotiation_id,
                request_id=request_id,
                consumer_doc=consumer,
                provider_doc=provider,
                access_token=token,
            )
            contract_object_id = ObjectId(contract_id_str)
            body.contract_id = contract_object_id
            if contract_text:
                body.natural_language_document = contract_text
        except Exception as contract_exc:
            print(f"Failed to generate contract for negotiation {negotiation_id}: {contract_exc}")

        negotiation = UpcastNegotiationObject(
            user_id=ObjectId(current_user.id),
            consumer_id=ObjectId(consumer["_id"]),
            provider_id=ObjectId(provider["_id"]),
            negotiation_status=NegotiationStatus.REQUESTED,
            resource_description=body.resource_description_object.dict(),
            dpw=body.data_processing_workflow_object,
            nlp=body.natural_language_document,
            conflict_status=conflict_status,
            negotiations=[request_id],
            negotiation_contracts=[contract_object_id] if contract_object_id else [],
            original_offer_id=request_id,
            created_at=now,
            updated_at=now
        )

        negotiation_dict = pydantic_to_dict(negotiation)
        negotiation_dict["_id"] = negotiation_id

        result = await negotiations_collection.insert_one(negotiation_dict)
        if result.inserted_id:

            # Update the request object and cloned policy (if any) with the existing negotiation_id
            policy_updates = {
                "negotiation_id": negotiation_id,
                "updated_at": datetime.utcnow()
            }
            if contract_object_id:
                policy_updates["contract_id"] = contract_object_id
            if contract_text:
                policy_updates["natural_language_document"] = contract_text

            await policy_collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": policy_updates}
            )

            await update_read_only_for_policy(negotiation_id, request_id)

            message = {
                "message": "Negotiation created successfully",
                "negotiation_id": str(result.inserted_id),

            }
            await push_messages("create", message)
            return message
        else:
            raise HTTPException(status_code=500, detail=f"Negotiation could not be created.")

    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Negotiation could not be created. {str(e)}. Traceback: {error_message}")


@router.get("/negotiation/{negotiation_id}", summary="Get a negotiation", response_model=UpcastNegotiationObject)
async def get_upcast_negotiation(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    try:
        #        negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id), "user_id": ObjectId(current_user.id)})
        if secure:
            negotiation = await negotiations_collection.find_one({
                "_id": ObjectId(negotiation_id),
                "$or": [
                    {"user_id": ObjectId(current_user.id)},
                    {"consumer_id": ObjectId(current_user.id)},
                    {"provider_id": ObjectId(current_user.id)}
                ]
            })
        else:
            negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id)})
        if negotiation:
            # print("negotiation", negotiation)
            return UpcastNegotiationObject(**pydantic_to_dict(negotiation, True))

        raise HTTPException(status_code=404, detail="Negotiation not found")
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.get("/negotiation/policies/{negotiation_id}", summary="Get policies related to a negotiation",
            response_model=List[UpcastPolicyObject])
async def get_policies_for_negotiation(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    if secure:
        negotiation = await negotiations_collection.find_one({
            "_id": ObjectId(negotiation_id),
            "$or": [
                {"user_id": ObjectId(current_user.id)},
                {"consumer_id": ObjectId(current_user.id)},
                {"provider_id": ObjectId(current_user.id)}
            ]
        })
        if not negotiation:
            raise HTTPException(status_code=404,
                                detail="Negotiation not found or you don't have permission to access it")
    try:
        object_id = ObjectId(negotiation_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid negotiation_id format")

    policies = await policy_collection.find({"negotiation_id": object_id}).to_list(length=None)

    if not policies:
        raise HTTPException(status_code=404, detail="No policies found for this negotiation")

    return [UpcastPolicyObject(**pydantic_to_dict(policy, True)) for policy in policies]


@router.get("/negotiation", summary="Get negotiations")  # , response_model=List[UpcastNegotiationObject])
async def get_upcast_negotiations(
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Retrieve negotiations where the user is either a consumer or a provider
    # negotiations = await negotiations_collection.find(
    #    {"$or": [{"consumer_id": ObjectId(current_user.id)}, {"provider_id": ObjectId(current_user.id)}, {"user_id": ObjectId(current_user.id)}]}
    # ).to_list(length=None)
    negotiations = await negotiations_collection.find(
        {"$or": [{"consumer_id": ObjectId(current_user.id)}, {"provider_id": ObjectId(current_user.id)},
                 {"user_id": ObjectId(current_user.id)}]}
    ).to_list(length=None)

    if not negotiations:
        return []
        # raise HTTPException(status_code=404, detail="No negotiations found for this user")

    return [pydantic_to_dict(negotiation, True) for negotiation in negotiations]
    # return [UpcastNegotiationObject(**pydantic_to_dict(negotiation, True)) for negotiation in negotiations]


@router.get("/providers/{account_id}/negotiations", summary="List negotiations by provider account")
async def list_provider_negotiations(
        account_id: str = Path(..., description="Provider account (user) id"),
        status: Optional[str] = Query(default=None, description="Filter by negotiation status (e.g., agreed, offered, requested, finalized, terminated, accepted, verified, draft)"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    """
    Return negotiations where the given provider account is the provider.
    If a status is supplied, filter to that status (case-insensitive, matches stored lowercase values).

    Response shape (example):
    [
      {
        "negotiation_id": "neg-123",
        "status": "agreed",
        "provider_id": "account-xyz",
        "consumer_id": "consumer-123",
        "updated_at": "2025-12-03T10:15:00Z",
        "contract_id": "contract-456"
      }
    ]
    """
    # Security: a user may only list their own provider negotiations
    try:
        provider_oid = ObjectId(account_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid account_id format")

    if secure:
        # Allow if current_user is this provider or is admin (optional)
        if not current_user or str(current_user.id) != str(provider_oid):
            # Fallback: for now, restrict strictly to owner
            raise HTTPException(status_code=403, detail="Not authorized to list these negotiations")

    query: Dict[str, Any] = {"provider_id": provider_oid}
    if status:
        query["negotiation_status"] = status.lower()

    cursor = negotiations_collection.find(query).sort("updated_at", -1)
    rows = await cursor.to_list(length=None)

    def _last_contract_id(doc: Dict[str, Any]) -> Optional[str]:
        ids = doc.get("negotiation_contracts") or []
        if not ids:
            return None
        try:
            return str(ids[-1])
        except Exception:
            return None

    result = []
    for n in rows:
        result.append({
            "negotiation_id": str(n.get("_id")),
            "status": n.get("negotiation_status"),
            "provider_id": str(n.get("provider_id")) if n.get("provider_id") else None,
            "consumer_id": str(n.get("consumer_id")) if n.get("consumer_id") else None,
            "updated_at": (n.get("updated_at") or ""),
            "contract_id": _last_contract_id(n)
        })

    return result


@router.put("/negotiation", summary="Update a negotiation")
async def update_upcast_negotiation(
        current_user: User = Depends(verify_access_token_and_resolve_user),
        body: UpcastNegotiationObject = Body(..., description="The negotiation object")
):
    if secure:
        existing_negotiation = await negotiations_collection.find_one({
            "_id": ObjectId(body.id),
            "$or": [
                {"user_id": ObjectId(current_user.id)},
                {"consumer_id": ObjectId(current_user.id)},
                {"provider_id": ObjectId(current_user.id)}
            ]
        })
        if not existing_negotiation:
            raise HTTPException(status_code=404,
                                detail="Negotiation not found or you do not have permission to update this negotiation")
    try:
        body["updated_at"] = datetime.utcnow()
        update_result = await negotiations_collection.update_one({"_id": ObjectId(body.id)},
                                                                 {"$set": pydantic_to_dict(body),
                                                                  "updated_at": datetime.utcnow()}
                                                                 )

        if update_result.matched_count == 0:
            raise HTTPException(status_code=404,
                                detail="Negotiation not found or you do not have permission to update this negotiation")

        if update_result.modified_count == 0:
            raise HTTPException(status_code=400, detail="No changes")

        return {"message": "Negotiation updated successfully", "negotiation_id": body.id}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.delete("/negotiation/{negotiation_id}", summary="Delete a negotiation")
async def delete_upcast_negotiation(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    try:
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Delete the negotiation
        delete_result = await negotiations_collection.delete_one(
            {"_id": ObjectId(negotiation_id),
             "$or": [{"consumer_id": ObjectId(current_user.id)}, {"provider_id": ObjectId(current_user.id)},
                     {"user_id": ObjectId(current_user.id)}]}
        )

        if delete_result.deleted_count == 0:
            raise HTTPException(status_code=404,
                                detail="Negotiation not found or you do not have permission to delete this negotiation")

        # Delete corresponding requests
        await policy_collection.delete_many({"negotiation_id": ObjectId(negotiation_id)})

        # Delete corresponding offers
        await policy_collection.delete_many({"negotiation_id": ObjectId(negotiation_id)})

        return {"message": "Negotiation and corresponding requests and offers deleted successfully",
                "negotiation_id": negotiation_id}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception. {str(e)}. Traceback: {error_message}")


@router.get("/contract/{negotiation_id}", summary="Get a contract", )
async def get_upcast_contract(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(verify_access_token_and_resolve_user),
        token: str = Depends(oauth2_scheme),
):
    try:
        negotiation = await verify_negotiation_access(negotiation_id, current_user.id)

        negotiations_list = negotiation.get("negotiations", [])
        if not negotiations_list:
            raise HTTPException(status_code=404, detail="No policies found in the negotiations")

        last_policy_id = negotiations_list[-1]
        if isinstance(last_policy_id, dict):
            last_policy_id = last_policy_id.get("_id") or last_policy_id.get("id")

        if not last_policy_id:
            raise HTTPException(status_code=404, detail="Last policy reference not found")

        try:
            last_policy_object_id = last_policy_id if isinstance(last_policy_id, ObjectId) else ObjectId(last_policy_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid policy identifier for negotiation")

        last_policy = await policy_collection.find_one({"_id": last_policy_object_id})
        if not last_policy:
            raise HTTPException(status_code=404, detail="Last policy not found")

        contract_id = last_policy.get("contract_id")
        if not contract_id:
            # Negotiation exists but no contract yet
            raise HTTPException(status_code=404, detail="Contract not available for this negotiation")

        endpoint_url = f"{CONTRACT_BASE_URL.rstrip('/')}/contract/get_contract/{contract_id}"

        headers = build_contract_service_headers(token, {"contract_id": str(contract_id)})  # keep only if the service expects it
        timeout = httpx.Timeout(10.0, connect=2.0, read=6.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.get(endpoint_url, headers=headers)
            except httpx.RequestError as e:
                raise HTTPException(status_code=502, detail=f"Agreement API unreachable: {e}") from e

        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Contract not found in agreement service")
        if resp.is_client_error or resp.is_server_error:
            raise HTTPException(
                status_code=502,
                detail=f"Agreement API error {resp.status_code}"
            )

        return resp.json()

    except HTTPException:
        raise
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.get("/policy/{policy_id}", summary="Get a policy", response_model=UpcastPolicyObject)
async def get_upcast_policy(
        policy_id: str = Path(..., description="The ID of the policy"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    try:

        if secure:
            policy = await policy_collection.find_one({
                "_id": ObjectId(policy_id),
                "$or": [
                    {"user_id": ObjectId(current_user.id)},
                    {"consumer_id": ObjectId(current_user.id)},
                    {"provider_id": ObjectId(current_user.id)}
                ]
            })
        else:
            policy = await policy_collection.find_one({"_id": ObjectId(policy_id)})
        if policy:
            return UpcastPolicyObject(**pydantic_to_dict(policy, True))

        raise HTTPException(status_code=404, detail="Policy not found")
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


# New endpoint
@router.get("/negotiation/{negotiation_id}/last-policy", summary="Get the last policy",
            response_model=UpcastPolicyObject)
async def get_last_policy(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    try:
        #        negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": ObjectId(current_user.id)}, {"provider_id": ObjectId(current_user.id)}, {"user_id": ObjectId(current_user.id)}]})
        if secure:
            negotiation = await negotiations_collection.find_one({
                "_id": ObjectId(negotiation_id),
                "$or": [
                    {"user_id": ObjectId(current_user.id)},
                    {"consumer_id": ObjectId(current_user.id)},
                    {"provider_id": ObjectId(current_user.id)}
                ]
            })
        else:
            negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id)})

        if not negotiation:
            raise HTTPException(status_code=404, detail="Negotiation not found")

        negotiations_list = negotiation.get("negotiations", [])
        if not negotiations_list:
            raise HTTPException(status_code=404, detail="No policies found in the negotiations")

        last_policy_raw_id = negotiations_list[-1]
        last_policy_oid = _ensure_object_id(last_policy_raw_id)
        if last_policy_oid is None:
            raise HTTPException(status_code=400, detail="Malformed policy id in negotiation list")

        request = await policy_collection.find_one({"_id": last_policy_oid})
        if not request:
            raise HTTPException(status_code=404, detail="Last policy not found")

        last_policy_dict = pydantic_to_dict(request, True)
        # last_policy_dict["is_read_only"] = await compute_is_read_only_flag(
        #     negotiation,
        #     last_policy_dict=last_policy_dict,
        # )
        return last_policy_dict
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.get(
    "/negotiation/{negotiation_id}/penultimate-policy",
    summary="Get the penultimate policy (fallback to last if only one)",
    response_model=UpcastPolicyObject,
)
async def get_penultimate_policy(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: "User" = Depends(verify_access_token_and_resolve_user),
):
    try:
        # 1) Validate negotiation_id
        if not ObjectId.is_valid(negotiation_id):
            raise HTTPException(status_code=400, detail="Invalid negotiation_id")

        # 2) Build filter (secure vs open)
        base_filter = {"_id": ObjectId(negotiation_id)}
        if secure:
            try:
                uid = ObjectId(current_user.id)
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid current_user id")
            base_filter["$or"] = [
                {"user_id": uid},
                {"consumer_id": uid},
                {"provider_id": uid},
            ]

        # 3) Fetch negotiation
        negotiation = await negotiations_collection.find_one(base_filter)
        if not negotiation:
            raise HTTPException(status_code=404, detail="Negotiation not found or access denied")

        # 4) Pick penultimate (or last if only one)
        negotiations_list = negotiation.get("negotiations", [])
        if not isinstance(negotiations_list, list) or not negotiations_list:
            raise HTTPException(status_code=404, detail="No policies found in the negotiations")

        raw_id = negotiations_list[-2] if len(negotiations_list) >= 2 else negotiations_list[-1]

        # 5) Coerce to ObjectId
        if isinstance(raw_id, ObjectId):
            policy_id = raw_id
        elif isinstance(raw_id, str) and ObjectId.is_valid(raw_id):
            policy_id = ObjectId(raw_id)
        else:
            raise HTTPException(status_code=400, detail="Malformed policy id in negotiation list")

        # 6) Load policy doc
        policy_doc = await policy_collection.find_one({"_id": policy_id})
        if not policy_doc:
            raise HTTPException(status_code=404, detail="Referenced policy not found")

        # 7) Return in your preferred shape
        return pydantic_to_dict(policy_doc, True)

    except HTTPException:
        raise
    except Exception as e:
        error_message = traceback.format_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Exception: {str(e)}. Traceback: {error_message}",
        )


# Recursive function to find changes in nested dictionaries
def find_changes(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    changes = {}
    excluded_keys = {'id', '_id', 'type', 'uid', 'created_at', 'updated_at'}

    if len(old) == 0:
        return changes

    for key in new:
        if key in excluded_keys:
            continue
        if key in old:
            if isinstance(new[key], dict) and isinstance(old[key], dict):
                sub_changes = find_changes(old[key], new[key])
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

    return changes


NEGOTIATION_AUTO_READ_ONLY_STATUSES = {
    NegotiationStatus.ACCEPTED.value.lower(),
    NegotiationStatus.AGREED.value.lower(),
    NegotiationStatus.VERIFIED.value.lower(),
    NegotiationStatus.FINALIZED.value.lower(),
    NegotiationStatus.TERMINATED.value.lower(),
}


def _normalize_status(value: Any) -> str:
    return str(value or "").lower()


def _ensure_object_id(value: Any) -> Optional[ObjectId]:
    if isinstance(value, ObjectId):
        return value
    if value is None:
        return None
    try:
        return ObjectId(str(value))
    except Exception:
        return None


async def compute_is_read_only_flag(
        negotiation: Dict[str, Any],
        *,
        last_policy_dict: Dict[str, Any],
        previous_policy_dict: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Determine whether the last policy in a negotiation should be marked read-only.
    """
    status_value = _normalize_status(negotiation.get("negotiation_status"))
    if status_value in NEGOTIATION_AUTO_READ_ONLY_STATUSES:
        return True

    negotiations_list = negotiation.get("negotiations") or []
    if len(negotiations_list) < 2:
        return False

    if previous_policy_dict is None:
        previous_id = negotiations_list[-2]
        previous_oid = _ensure_object_id(previous_id)
        if previous_oid is None:
            return False
        previous_doc = await policy_collection.find_one({"_id": previous_oid})
        previous_policy_dict = pydantic_to_dict(previous_doc, True) if previous_doc else {}

    if not previous_policy_dict:
        return False

    changes = find_changes(previous_policy_dict, last_policy_dict or {})

    print("previous_policy_dic", previous_policy_dict.get("_id"))
    print("last_policy_dict", last_policy_dict.get("_id"))

    for ignorable_key in (
        "consumer_id",
        "is_read_only",
        "contract_id",
        "created_at",
        "updated_at",
        "negotiation_id",
        "_id",
        "id",
        "user_id",
        "provider_id",
        "consumer_id"

    ):

        changes.pop(ignorable_key, None)

    print("\n\n\n changes: ", changes)
    return bool(changes)


async def update_read_only_for_policy(
        negotiation_id: Any,
        policy_id: Optional[Any] = None
) -> None:
    """
    Compute and persist the read-only flag for a specific policy entry in a negotiation.
    When policy_id is None, the latest policy in the negotiation is targeted.
    """
    negotiation_oid = _ensure_object_id(negotiation_id)
    if negotiation_oid is None:
        return

    negotiation = await negotiations_collection.find_one({"_id": negotiation_oid})
    if not negotiation:
        return

    negotiations_list = negotiation.get("negotiations") or []
    if not negotiations_list:
        return

    target_oid = _ensure_object_id(policy_id) if policy_id else _ensure_object_id(negotiations_list[-1])
    if target_oid is None:
        return

    previous_policy_dict: Dict[str, Any] = {}
    target_index: Optional[int] = None
    for idx, entry in enumerate(negotiations_list):
        entry_oid = _ensure_object_id(entry)
        if entry_oid == target_oid:
            target_index = idx
            break
    if target_index is None:
        return

    if target_index > 0:
        previous_oid = _ensure_object_id(negotiations_list[target_index - 1])
        if previous_oid:
            previous_doc = await policy_collection.find_one({"_id": previous_oid})
            if previous_doc:
                previous_policy_dict = pydantic_to_dict(previous_doc, True)

    policy_doc = await policy_collection.find_one({"_id": target_oid})
    if not policy_doc:
        return

    policy_dict = pydantic_to_dict(policy_doc, True)
    is_read_only = await compute_is_read_only_flag(
        negotiation,
        last_policy_dict=policy_dict,
        previous_policy_dict=previous_policy_dict,
    )

    await policy_collection.update_one(
        {"_id": target_oid},
        {"$set": {"is_read_only": is_read_only}}
    )


# Endpoint to get the last policy and the changes between the last two policies
@router.get("/negotiation/{negotiation_id}/last-policy-diff", summary="Get the last policy",
            response_model=PolicyDiffResponse)
async def get_last_policy(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    print("testing")

    try:
        if secure:
            negotiation = await negotiations_collection.find_one({
                "_id": ObjectId(negotiation_id),
                "$or": [
                    {"user_id": ObjectId(current_user.id)},
                    {"consumer_id": ObjectId(current_user.id)},
                    {"provider_id": ObjectId(current_user.id)}
                ]
            })
        else:
            negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id)})

        if not negotiation:
            raise HTTPException(status_code=404, detail="Negotiation not found")

        negotiations_list = negotiation.get("negotiations", [])
        if not negotiations_list:
            raise HTTPException(status_code=404, detail="No policies found in the negotiations")

        last_policy_id = negotiations_list[-1]
        # print ("last_policy_id: ", last_policy_id)
        last_policy = await policy_collection.find_one({"_id": ObjectId(last_policy_id)})

        if len(negotiations_list) < 2:
            second_last_policy = {}
        else:
            second_last_policy_id = negotiations_list[-2]
            second_last_policy = await policy_collection.find_one({"_id": ObjectId(second_last_policy_id)})

            # print("second_last_policy_id: ", second_last_policy_id)

        if not last_policy:
            raise HTTPException(status_code=404, detail="Last policy not found")

        last_policy_dict = pydantic_to_dict(last_policy, True)

        second_last_policy_dict = pydantic_to_dict(second_last_policy, True) if second_last_policy else {}

        # Normalize ODRL order to avoid order-only diffs
        def _normalize_odrl_policy_order(doc: Dict[str, Any]):
            try:
                op = doc.get("odrl_policy") or {}
                arr = op.get("data")
                if isinstance(arr, list):
                    def _k(o):
                        return "|".join([
                            str(o.get("rule", "")),
                            str(o.get("actor", "")),
                            str(o.get("action", "")),
                            str(o.get("target", "")),
                            str(o.get("purpose", "")),
                            str(o.get("query", "")),
                        ]).lower()
                    arr.sort(key=_k)
            except Exception:
                pass

        _normalize_odrl_policy_order(second_last_policy_dict)
        _normalize_odrl_policy_order(last_policy_dict)

        # Calculate the changes between the last two policies
        changes = find_changes(second_last_policy_dict, last_policy_dict)

        # Normalize changes so typed fields in PolicyDiffObject parse consistently
        def _to_change(val: Any) -> Dict[str, Any]:
            if isinstance(val, dict) and ("from" in val or "to" in val):
                return val
            return {"from": None, "to": val}

        def _coerce_mapping(m: Any) -> Any:
            if isinstance(m, dict):
                return {k: _to_change(v) for k, v in m.items()}
            return m

        for k in ("custom_arrangement_section", "custom_definitions", "resource_description_object", "odrl_policy", "data_processing_workflow_object"):
            if k in changes:
                changes[k] = _coerce_mapping(changes[k])

        print(second_last_policy.get("_id"))
        print(last_policy_dict.get("_id"))
        print  ("get_last_policy_diff changes", changes)

        # read_only_flag = await compute_is_read_only_flag(
        #     negotiation,
        #     last_policy_dict=last_policy_dict,
        #     previous_policy_dict=second_last_policy_dict,
        # )
        # last_policy_dict["is_read_only"] = read_only_flag

        try:
            response = PolicyDiffResponse(
                last_policy=last_policy_dict,
                changes=PolicyDiffObject(**changes)
            )

            print("get_last_policy_diff response diff", response.changes)
        except ValidationError as e:
            print("Response validation failed:", e.json(indent=2))
            raise

        return response
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.get(
    "/negotiation/{negotiation_id}/last-second-policy-diff",
    summary="Get the penultimate policy (with diff against the prior snapshot)",
    response_model=PolicyDiffResponse,
)
async def get_penultimate_policy_diff(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(verify_access_token_and_resolve_user),
):
    try:
        if secure:
            negotiation = await negotiations_collection.find_one(
                {
                    "_id": ObjectId(negotiation_id),
                    "$or": [
                        {"user_id": ObjectId(current_user.id)},
                        {"consumer_id": ObjectId(current_user.id)},
                        {"provider_id": ObjectId(current_user.id)},
                    ],
                }
            )
        else:
            negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id)})

        if not negotiation:
            raise HTTPException(status_code=404, detail="Negotiation not found")

        negotiations_list = negotiation.get("negotiations", [])
        if not negotiations_list:
            raise HTTPException(status_code=404, detail="No policies found in the negotiations")

        # Determine penultimate policy (fallback to latest if only one exists)
        penultimate_policy_id = negotiations_list[-2] if len(negotiations_list) >= 2 else negotiations_list[-1]
        penultimate_policy = await policy_collection.find_one({"_id": ObjectId(penultimate_policy_id)})
        if not penultimate_policy:
            raise HTTPException(status_code=404, detail="Penultimate policy not found")

        # Determine the prior snapshot to diff against (empty dict if none exists)
        if len(negotiations_list) >= 3:
            previous_policy_id = negotiations_list[-3]
            previous_policy = await policy_collection.find_one({"_id": ObjectId(previous_policy_id)})
        else:
            previous_policy = None

        penultimate_policy_dict = pydantic_to_dict(penultimate_policy, True)
        previous_policy_dict = pydantic_to_dict(previous_policy, True) if previous_policy else {}

        # Normalize ODRL order to avoid order-only diffs
        def _normalize_odrl_policy_order(doc: Dict[str, Any]):
            try:
                op = doc.get("odrl_policy") or {}
                arr = op.get("data")
                if isinstance(arr, list):
                    def _k(o):
                        return "|".join([
                            str(o.get("rule", "")),
                            str(o.get("actor", "")),
                            str(o.get("action", "")),
                            str(o.get("target", "")),
                            str(o.get("purpose", "")),
                            str(o.get("query", "")),
                        ]).lower()
                    arr.sort(key=_k)
            except Exception:
                pass

        _normalize_odrl_policy_order(previous_policy_dict)
        _normalize_odrl_policy_order(penultimate_policy_dict)

        changes = find_changes(previous_policy_dict, penultimate_policy_dict)

        diff_response = PolicyDiffResponse(
            last_policy=penultimate_policy_dict,
            changes=PolicyDiffObject(**changes),
        )
        return diff_response
    except HTTPException:
        raise
    except Exception as e:
        error_message = traceback.format_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Exception: {str(e)}. Traceback: {error_message}",
        )


# a new Object for policy compaeable
class PolicyDiff(BaseModel):
    previous_policy: Dict[str, Any]
    last_policy: Dict[str, Any]
    changes: Dict[str, Any] = Field(..., description="Diff ops between first and last")


@router.get(
    "/policy/get_diffs",
    summary="Get the difference between two policies",
    response_model=PolicyDiff,
)
async def get_diffs_bet_two_policy(
        response: Response,
        first_policy_id: str = Header(..., alias="first-policy-id", description="ID of the first policy"),
        second_policy_id: str = Header(..., alias="second-policy-id", description="ID of the second policy"),
):
    # 1) Validate ObjectIds
    try:
        first_oid = ObjectId(first_policy_id)

    except Exception as e:

        raise HTTPException(status_code=400, detail=f"Invalid first policy ID format: {first_policy_id}")

    try:
        second_oid = ObjectId(second_policy_id)

    except Exception as e:

        raise HTTPException(status_code=400, detail=f"Invalid second policy ID format: {second_policy_id}")

    # 2) Fetch both in one go
    try:
        docs = await policy_collection.find(
            {"_id": {"$in": [first_oid, second_oid]}}
        ).to_list(length=2)
        doc_map = {doc["_id"]: doc for doc in docs}

        # Map correctly: first -> previous/base, second -> last/new
        previous_doc = doc_map.get(first_oid)
        last_doc = doc_map.get(second_oid)

        if not previous_doc or not last_doc:
            missing = []
            if not previous_doc:
                missing.append(f"first ({first_policy_id})")
            if not last_doc:
                missing.append(f"second ({second_policy_id})")
            raise HTTPException(status_code=404, detail=f"Policy not found for: {', '.join(missing)}")

        # 3) Serialize & diff (ensure your pydantic_to_dict accepts plain dicts or adapt)
        previous_dict = pydantic_to_dict(previous_doc, True)
        last_dict = pydantic_to_dict(last_doc, True)

        changes = find_changes(previous_dict, last_dict)

        # 4) Headers & response
        response.headers["X-Changes-Count"] = str(len(changes))
        response.headers["X-Compared-Ids"] = f"{first_policy_id},{second_policy_id}"

        return PolicyDiff(
            previous_policy=previous_dict,
            last_policy=last_dict,
            changes=changes,
        )

    except HTTPException:
        # Preserve intended 400/404 responses
        raise
    except Exception as e:

        raise HTTPException(status_code=500, detail="Internal server error while processing policy differences")


@router.get("/consumer/request/{request_id}", summary="Get an existing request", response_model=UpcastPolicyObject)
async def get_upcast_request(
        current_user: User = Depends(verify_access_token_and_resolve_user),
        request_id: str = Path(..., description="The ID of the request")
):
    request = await policy_collection.find_one({"_id": ObjectId(request_id),
                                                "$or": [
                                                    {"user_id": ObjectId(current_user.id)},
                                                    {"consumer_id": ObjectId(current_user.id)},
                                                    {"provider_id": ObjectId(current_user.id)}
                                                ]
                                                })
    if request:
        return UpcastPolicyObject(**pydantic_to_dict(request, True))
    else:
        raise HTTPException(status_code=404, detail="Request not found")


@router.post("/negotiation/create-with-initial", summary="Create a negotiation with initial offer and request")
async def create_negotiation_with_initial_policies(
        body: NegotiationCreationRequest = Body(..., description="The negotiation creation request"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    """
    Create a negotiation with both an initial offer and request.
    Requires authentication via JWT token.
    """
    try:

        # Verify consumer and provider exist
        consumer = await users_collection.find_one({"_id": ObjectId(body.consumer_id)})
        provider = await users_collection.find_one({"_id": ObjectId(body.provider_id)})

        if not consumer:
            raise HTTPException(status_code=404, detail="Consumer not found")
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")

        now = datetime.utcnow()

        # Create initial offer policy
        initial_offer = body.initial_offer
        initial_offer.type = PolicyType.OFFER.value
        initial_offer.provider_id = ObjectId(body.provider_id)
        initial_offer.consumer_id = ObjectId(body.consumer_id)
        initial_offer.created_at = now
        initial_offer.updated_at = now

        # Insert initial offer
        offer_result = await policy_collection.insert_one(pydantic_to_dict(initial_offer))
        offer_id = offer_result.inserted_id

        # Create initial request policy
        initial_request = body.initial_request
        initial_request.type = PolicyType.REQUEST.value
        initial_request.consumer_id = ObjectId(body.consumer_id)
        initial_request.provider_id = ObjectId(body.provider_id)
        initial_request.created_at = now
        initial_request.updated_at = now

        # Insert initial request
        request_result = await policy_collection.insert_one(pydantic_to_dict(initial_request))
        request_id = request_result.inserted_id

        # Extract negotiation metadata (use from request or offer, preferring request)
        title = body.title or initial_request.title or initial_offer.title

        # Handle resource description - it should be a dict according to UpcastNegotiationObject
        resource_description = body.resource_description
        if not resource_description:
            if initial_request.resource_description_object:
                resource_description = pydantic_to_dict(initial_request.resource_description_object)
            elif initial_offer.resource_description_object:
                resource_description = pydantic_to_dict(initial_offer.resource_description_object)
            else:
                resource_description = {}

        # Handle dpw (Data Processing Workflow) - should be a Dict
        dpw = body.dpw
        if not dpw:
            dpw = (
                    initial_request.data_processing_workflow_object or
                    initial_offer.data_processing_workflow_object or
                    {}
            )

        # Handle nlp (Natural Language Part) - should be a string
        nlp = body.nlp
        if not nlp:
            nlp = (
                    initial_request.natural_language_document or
                    initial_offer.natural_language_document or
                    ""
            )

        # Create negotiation object
        negotiation = UpcastNegotiationObject(
            user_id=ObjectId(current_user.id),  # Set the consumer as the user who initiated
            title=title,
            consumer_id=ObjectId(body.consumer_id),
            provider_id=ObjectId(body.provider_id),
            negotiation_status=body.negotiation_status.value,
            resource_description=resource_description,
            dpw=dpw,
            nlp=nlp,
            conflict_status="no conflict",
            negotiations=[offer_id, request_id],  # Include both policies in order
            original_offer_id=offer_id,
            created_at=now,
            updated_at=now
        )

        # Insert negotiation
        negotiation_result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
        negotiation_id = negotiation_result.inserted_id

        # Update both policies with the negotiation_id
        await policy_collection.update_one(
            {"_id": offer_id},
            {
                "$set": {
                    "negotiation_id": negotiation_id,
                    "updated_at": now
                }
            }
        )

        await policy_collection.update_one(
            {"_id": request_id},
            {
                "$set": {
                    "negotiation_id": negotiation_id,
                    "updated_at": now
                }
            }
        )

        await update_read_only_for_policy(negotiation_id, offer_id)
        await update_read_only_for_policy(negotiation_id, request_id)

        response_data = {
            "message": "Negotiation created successfully with initial offer and request",
            "negotiation_id": str(negotiation_id),
            "offer_id": str(offer_id),
            "request_id": str(request_id),
            "status": body.negotiation_status.value
        }

        # Push notification messages
        await push_messages("create", {
            "message": "Negotiation created with initial policies",
            "negotiation_id": str(negotiation_id)
        })

        return response_data

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        error_message = traceback.format_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create negotiation: {str(e)}. Traceback: {error_message}"
        )



#
@router.post("/consumer/request/new", summary="Create a new request")
async def create_new_upcast_request(
        current_user: User = Depends(verify_access_token_and_resolve_user),
        token: str = Depends(oauth2_scheme),
        previous_policy_id: Optional[str] = Header(None, description="The ID of the previous offer"),
        body: UpcastPolicyObject = Body(..., description="The request object")
):
    try:
        # Normalise ODRL payload to keep stored policies aligned
        body = odrl_convertor(body)

        if body.negotiation_id:
            cloned_policy_id = None
            existing_negotiation = await negotiations_collection.find_one({"_id": ObjectId(body.negotiation_id)})
            # print(f"Existing negotiation: {existing_negotiation}")

        if not body.negotiation_id:

            print("if not body.negotiation_id \n")
            print("previous_policy_id", previous_policy_id)
            # Clone the policy with id = previous_policy_id
            previous_policy = await policy_collection.find_one({"_id": ObjectId(previous_policy_id)})
            print(f"Previous policy: {previous_policy}")
            if not previous_policy:
                raise HTTPException(status_code=404, detail="Previous policy not found")

            # Remove the _id field from the cloned policy
            previous_policy.pop("_id")
            print('previous_policy.pop("_id")')
            # Create a new policy object from the cloned policy
            cloned_policy = UpcastPolicyObject(**previous_policy)
            print(f"Cloned policy: {cloned_policy}")
            cloned_policy.type = PolicyType.REQUEST.value  # Change the policy type to "offer"

            now = datetime.utcnow()
            cloned_policy.created_at = now
            cloned_policy.updated_at = now
            # Insert the cloned policy into the policy collection
            result = await policy_collection.insert_one(pydantic_to_dict(cloned_policy))
            print(f"Inserted cloned policy ID: {result.inserted_id}")
            cloned_policy_id = str(result.inserted_id)

        # Change the policy type of the original body to "offer"
        body.type = PolicyType.REQUEST.value

        body.provider_id = ObjectId(body.provider_id)
        body.consumer_id = ObjectId(body.consumer_id)
        print(f"Consumer ID: {body.consumer_id}, Provider ID: {body.provider_id}")
        now = datetime.utcnow()
        body.created_at = now
        body.updated_at = now
        print(f"Body created at: {body.created_at}, updated at: {body.updated_at}")
        # Save the offer to MongoDB
        result = await policy_collection.insert_one(pydantic_to_dict(body))
        print(f"Offer saved: {result.inserted_id}")

        # Retrieve the generated _id
        request_id = str(result.inserted_id)
        negotiation_object_id = ObjectId(body.negotiation_id) if body.negotiation_id else ObjectId()

        existing_contract = getattr(body, "contract_id", None)
        if existing_contract:
            try:
                body.contract_id = ObjectId(str(existing_contract))
            except (InvalidId, TypeError):
                body.contract_id = None

        original_nlp = body.natural_language_document
        contract_object_id, contract_text = await _maybe_generate_contract_for_policy(
            body, negotiation_object_id, request_id, access_token=token
        )
        policy_updates = {}
        if contract_object_id:
            policy_updates["contract_id"] = contract_object_id
        if contract_text and contract_text != original_nlp:
            policy_updates["natural_language_document"] = contract_text
        if policy_updates:
            await policy_collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": policy_updates}
            )

        if not body.negotiation_id:  # If negotiation_id is empty, create a new negotiation

            negotiation = UpcastNegotiationObject(
                user_id=ObjectId(current_user.id),
                title=body.title,
                consumer_id=ObjectId(body.consumer_id),
                provider_id=ObjectId(body.provider_id),  # Assuming provider_id is available in the request object
                negotiation_status=NegotiationStatus.REQUESTED,
                resource_description=body.resource_description_object.dict(),
                dpw=body.data_processing_workflow_object,
                nlp=(contract_text or body.natural_language_document),
                conflict_status="",  # Initialize with an empty string
                negotiations=[ObjectId(cloned_policy_id), ObjectId(request_id)],  # Add the request to negotiations list
                negotiation_contracts=[contract_object_id] if contract_object_id else [],
                original_offer_id=ObjectId(cloned_policy_id),
                created_at=now,
                updated_at=now
            )

            print(f"New negotiation object: {negotiation}")

            negotiation_dict = pydantic_to_dict(negotiation)
            negotiation_dict["_id"] = negotiation_object_id
            result = await negotiations_collection.insert_one(negotiation_dict)
            print(f"Inserted negotiation ID: {result.inserted_id}")
            negotiation_id = negotiation_object_id

            # Update the request object and cloned policy (if any) with the new negotiation_id
            await policy_collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": {"negotiation_id": negotiation_id,
                          "updated_at": datetime.utcnow()}}
            )

            if cloned_policy_id:
                await policy_collection.update_one(
                    {"_id": ObjectId(cloned_policy_id)},
                    {"$set": {"negotiation_id": negotiation_id,
                              "updated_at": datetime.utcnow()}}
                )
            if cloned_policy_id:
                await update_read_only_for_policy(negotiation_id, cloned_policy_id)
            await update_read_only_for_policy(negotiation_id, request_id)
        else:
            negotiation_push = [ObjectId(request_id)]
            if cloned_policy_id:
                negotiation_push.append(ObjectId(cloned_policy_id))
            push_payload = {"negotiations": {"$each": negotiation_push}}
            if contract_object_id:
                push_payload["negotiation_contracts"] = {"$each": [contract_object_id]}
            updates = {
                "$set": {"negotiation_status": NegotiationStatus.REQUESTED,
                         "updated_at": datetime.utcnow(),
                         "nlp": contract_text or body.natural_language_document},
                "$push": push_payload
            }

            await negotiations_collection.update_one(
                {"_id": negotiation_object_id},
                updates
            )
            negotiation_id = negotiation_object_id

            # Update the request object and cloned policy (if any) with the existing negotiation_id
            await policy_collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": {"negotiation_id": negotiation_id,
                          "updated_at": datetime.utcnow()}}
            )
            if cloned_policy_id:
                await policy_collection.update_one(
                    {"_id": ObjectId(cloned_policy_id)},
                    {"$set": {"negotiation_id": negotiation_id,
                              "updated_at": datetime.utcnow()}}
                )
            if cloned_policy_id:
                await update_read_only_for_policy(negotiation_id, cloned_policy_id)
            await update_read_only_for_policy(negotiation_id, request_id)

        message = {
            "message": "Request sent successfully",
            "request_id": request_id,
            "negotiation_id": str(negotiation_id),

        }
        await push_messages("create", message)
        return message
    except BaseException as e:
        print(e)
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")
        # raise HTTPException(status_code=500,
        #                     detail=f"Exception: {str(e)}.")


@router.put("/consumer/request/{request_id}", summary="Update an existing request")
async def update_upcast_request(
        request_id: str,
        body: UpcastPolicyObject = Body(..., description="The request object"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    print(f"Updating request with ID: {request_id} for user: {current_user.id}")
    try:
        # Verify the request exists and belongs to the current user
        if secure:
            existing_request = await policy_collection.find_one({
                "_id": ObjectId(request_id),
                "consumer_id": current_user.id,
                "type": PolicyType.REQUEST.value
            })
            print(f"Existing request: {existing_request}")
        else:
            existing_request = await policy_collection.find_one({
                "_id": ObjectId(request_id),
                "type": PolicyType.REQUEST.value
            })
        if not existing_request:
            raise HTTPException(
                status_code=404,
                detail="Request not found or you don't have permission to update it"
            )

        # Update the existing request with the new data
        # Convert to dict and remove id to prevent overwriting
        # Normalise ODRL payload to keep stored policies aligned
        body = odrl_convertor(body)
        update_data = pydantic_to_dict(body)
        if "_id" in update_data:
            del update_data["_id"]

        # Ensure type and user-related fields aren't changed
        update_data["type"] = PolicyType.REQUEST.value
        update_data["consumer_id"] = current_user.id

        update_data["updated_at"] = datetime.utcnow()

        # Update the request in the database
        result = await policy_collection.update_one(
            {"_id": ObjectId(request_id)},
            {"$set": update_data}
        )

        if result.modified_count == 0:
            return {"message": "No changes were made to the request"}

        # If negotiation data was updated, also update the negotiation record
        if existing_request.get("negotiation_id"):
            negotiation_id = existing_request["negotiation_id"]

            # Update relevant fields in the negotiation
            negotiation_updates = {}
            if "title" in body.__dict__ and body.title:
                negotiation_updates["title"] = body.title
            if "resource_description_object" in body.__dict__ and body.resource_description_object:
                negotiation_updates["resource_description"] = body.resource_description_object.dict()
            if "data_processing_workflow_object" in body.__dict__ and body.data_processing_workflow_object:
                negotiation_updates["dpw"] = body.data_processing_workflow_object
            if "natural_language_document" in body.__dict__ and body.natural_language_document:
                negotiation_updates["nlp"] = body.natural_language_document

            negotiation_updates["updated_at"] = datetime.utcnow()

            if negotiation_updates:
                await negotiations_collection.update_one(
                    {"_id": ObjectId(negotiation_id)},
                    {"$set": negotiation_updates}
                )

        return {
            "message": "Request updated successfully",
            "request_id": request_id,
            "negotiation_id": str(existing_request.get("negotiation_id", ""))
        }

    except Exception as e:
        error_message = traceback.format_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Exception: {str(e)}. Traceback: {error_message}"
        )


# @router.put("/provider/offer/{offer_id}", summary="Update an existing offer ")
# async def update_upcast_offer(
#         offer_id: str,
#         body: UpcastPolicyObject = Body(..., description="The offer object"),
#         current_user: User = Depends(verify_access_token_and_resolve_user)
# ):
#     try:
#         if secure:
#             existing_offer = await policy_collection.find_one({
#                 "_id": ObjectId(offer_id),
#                 # "provider_id": current_user.id,
#                 "type": PolicyType.OFFER.value
#             })
#             print(f"Existing offer: {existing_offer}")
#         else:
#             existing_offer = await policy_collection.find_one({
#                 "_id": ObjectId(offer_id),
#                 "type": PolicyType.OFFER.value
#             })
#         if not existing_offer:
#             raise HTTPException(
#                 status_code=404,
#                 detail="Offer not found or you don't have permission to update it"
#             )

#         # Prepare update data from the request body
#         update_data = pydantic_to_dict(body)
#         if "_id" in update_data:
#             del update_data["_id"]

#         # Ensure type and user-related fields aren't changed
#         update_data["type"] = PolicyType.OFFER.value
#         update_data["provider_id"] = current_user.id

#         # Update the offer in the database
#         result = await policy_collection.update_one(
#             {"_id": ObjectId(offer_id)},
#             {"$set": update_data}
#         )

#         if result.modified_count == 0:
#             return {"message": "No changes were made to the offer"}

#         # If negotiation data was updated, also update the negotiation record
#         negotiation_id = existing_offer.get("negotiation_id")
#         if negotiation_id:
#             # Update relevant fields in the negotiation
#             negotiation_updates = {}
#             if "title" in body.__dict__ and body.title:
#                 negotiation_updates["title"] = body.title
#             if "resource_description_object" in body.__dict__ and body.resource_description_object:
#                 negotiation_updates["resource_description"] = body.resource_description_object.dict()
#             if "data_processing_workflow_object" in body.__dict__ and body.data_processing_workflow_object:
#                 negotiation_updates["dpw"] = body.data_processing_workflow_object
#             if "natural_language_document" in body.__dict__ and body.natural_language_document:
#                 negotiation_updates["nlp"] = body.natural_language_document

#             if negotiation_updates:
#                 await negotiations_collection.update_one(
#                     {"_id": ObjectId(negotiation_id)},
#                     {"$set": negotiation_updates}
#                 )

#         return {
#             "message": "Offer updated successfully",
#             "offer_id": offer_id,
#             "negotiation_id": str(negotiation_id) if negotiation_id else ""
#         }

#     except Exception as e:
#         error_message = traceback.format_exc()
#         raise HTTPException(
#             status_code=500,
#             detail=f"Exception: {str(e)}. Traceback: {error_message}"
#         )

@app.put("/provider/offer", summary="Update an existing offer")
async def update_upcast_offer(
        body: UpcastPolicyObject = Body(..., description="The request object"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    try:
        # Normalise ODRL payload to keep stored policies aligned
        body = odrl_convertor(body)

        # Change the policy type to "offer"
        body.type = PolicyType.OFFER
        body.consumer_id = current_user.id

        plc = pydantic_to_dict(body)
        plc.pop("id")
        # Save the offer to MongoDB

        print('policy negotiation_id', body.negotiation_id)

        if not body.negotiation_id:
            result = await policy_collection.insert_one(pydantic_to_dict(body))
            # Retrieve the generated _id
            request_id = str(result.inserted_id)
            negotiation = UpcastNegotiationObject(
                user_id=current_user.id,
                title=body.title,
                consumer_id=ObjectId(body.consumer_id),
                provider_id=ObjectId(body.provider_id),  # Assuming provider_id is available in the request object
                negotiation_status=NegotiationStatus.DRAFT,
                resource_description=body.resource_description_object.dict(),
                dpw=body.data_processing_workflow_object,
                nlp=body.natural_language_document,
                conflict_status="",  # Initialize with an empty string
                negotiations=[ObjectId(request_id)],  # Add the request to negotiations list       
            )
            result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
            negotiation_id = result.inserted_id

            print(f'negotiation id {negotiation_id}')

            # Update the request object with the new negotiation_id
            await policy_collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": {"negotiation_id": negotiation_id}}
            )

        else:
            if not body.id:
                raise HTTPException(status_code=400, detail="Policy ID is missing or invalid")

            print(f"Updating policy with ID: {body.id}")

            result = await policy_collection.update_one({"_id": ObjectId(body.id)}, {"$set": plc})
            request_id = str(body.id)

            if not body.negotiation_id:
                raise HTTPException(status_code=400, detail="Negotiation ID is missing or invalid")

            print(f"Updating negotiation with ID: {body.negotiation_id}")

            try:
                update_result = await negotiations_collection.update_one(
                    {"_id": ObjectId(body.negotiation_id)},
                    {
                        "$push": {"negotiations": ObjectId(request_id)}
                    }
                )

                print(f"update_result {update_result}")

                negotiation_id = body.negotiation_id

                if update_result.modified_count == 0:
                    raise HTTPException(status_code=404, detail="Negotiation not found or not updated")

            except Exception as e:
                print(f"MongoDB update failed: {str(e)}")
                raise HTTPException(status_code=500, detail=f"Failed to update negotiation: {str(e)}")

        print(f'negotiation id before return statement {negotiation_id}')
        return {"message": "Request sent successfully", "request_id": request_id, "negotiation_id": str(negotiation_id)}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.delete("/consumer/request/{request_id}", summary="Delete a request")
async def delete_upcast_request(
        request_id: str = Path(..., description="The ID of the request"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    if secure:
        request = await policy_collection.find_one({
            "_id": ObjectId(request_id),
            "consumer_id": ObjectId(current_user.id)
        })
    else:
        request = await policy_collection.find_one({"_id": ObjectId(request_id)})

    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    # Delete the request
    delete_result = await policy_collection.delete_one({"_id": ObjectId(request_id)})

    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=404,
                            detail="Request not found or you do not have permission to delete this request")

    # If the request is part of a negotiation, remove it from the negotiation's negotiations field
    if request.get("negotiation_id"):
        await negotiations_collection.update_one(
            {"_id": request["negotiation_id"]},
            {"$pull": {"negotiations": {"_id": ObjectId(request_id)}}}
        )

    return {"message": "Request deleted successfully", "request_id": request_id}


# @router.get("/consumer/all_policies", summary="Get all policies", response_model=List[UpcastPolicyObject])
# async def get_all_policies(
#         current_user: User = Depends(verify_access_token_and_resolve_user)
# ):
#     offers = await policy_collection.find({"provider_id": {"$exists": True}}).to_list(length=None)
#
#     if not offers:
#         raise HTTPException(status_code=404, detail="No offers found")
#
#     return [UpcastPolicyObject(**pydantic_to_dict(offer, True)) for offer in offers]

@router.get("/consumer/offer", summary="Get available offers", response_model=List[UpcastPolicyObject])
async def get_upcast_offers(
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    offers = await policy_collection.find({
        'type': 'offer',
        '$or': [
            {'negotiation_id': {'$exists': False}},
            {'negotiation_id': ''},
            {'negotiation_id': None}
        ]
    }).to_list(length=None)

    if not offers:
        raise HTTPException(status_code=404, detail="No offers found")

    return [UpcastPolicyObject(**pydantic_to_dict(offer, True)) for offer in offers]


@router.post("/provider/offer/new", summary="Create a new offer")
async def create_new_upcast_offer(
        current_user: User = Depends(verify_access_token_and_resolve_user),
        token: str = Depends(oauth2_scheme),
        body: UpcastPolicyObject = Body(..., description="The offer object")
):
    try:
        # Normalise ODRL payload to keep stored policies aligned
        body = odrl_convertor(body)

        # body.provider_id = ObjectId(current_user.id)
        # body.consumer_id = ObjectId(body.consumer_id)

        body.provider_id = ObjectId(body.provider_id)
        body.consumer_id = ObjectId(body.consumer_id)



        # Convert Pydantic model to dictionary
        body_dict = pydantic_to_dict(body)

        # if uncomment following, an error occuring: cannot generate a new offer form provider side.
        # # Handle manual ID if provided,
        # if body.id:
        #     if await policy_collection.find_one({"_id": body.id}):  # Ensure ID is unique
        #         raise HTTPException(status_code=400, detail="Policy ID already exists")
        #     body_dict["_id"] = body.id  # Assign manual ID
        # else:
        #     body_dict.pop("id", None)  # Remove 'id' if it's None to avoid issues

        # Change the policy type to "offer"
        body_dict["type"] = PolicyType.OFFER.value

        now = datetime.utcnow()
        body_dict["created_at"] = now
        body_dict["updated_at"] = now
        # Insert into MongoDB
        result = await policy_collection.insert_one(body_dict)

        # offer_id = body.id
        # if result:
        offer_id = str(result.inserted_id)
        print("create_new_upcast_offer: ", offer_id)

        negotiation_object_id = ObjectId(body.negotiation_id) if body.negotiation_id else ObjectId()

        existing_contract = getattr(body, "contract_id", None)
        if existing_contract:
            try:
                body.contract_id = ObjectId(str(existing_contract))
            except (InvalidId, TypeError):
                body.contract_id = None

        original_nlp = body.natural_language_document
        contract_object_id, contract_text = await _maybe_generate_contract_for_policy(
            body, negotiation_object_id, offer_id, access_token=token
        )
        policy_updates = {}
        if contract_object_id:
            policy_updates["contract_id"] = contract_object_id
        if contract_text and contract_text != original_nlp:
            policy_updates["natural_language_document"] = contract_text
        if policy_updates:
            await policy_collection.update_one(
                {"_id": ObjectId(offer_id)},
                {"$set": policy_updates}
            )

        # Handle negotiation if applicable
        if body.negotiation_id:
            print("create_new_upcast_offer, negotiation_id", body.negotiation_id)

            await negotiations_collection.update_one(
                {"_id": negotiation_object_id},
                {
                    "$set": {"negotiation_status": NegotiationStatus.OFFERED,
                             "updated_at": datetime.utcnow(),
                             "nlp": contract_text or body.natural_language_document},

                    "$addToSet": {  # avoids duplicates
                        "negotiations": ObjectId(offer_id),
                        **({"negotiation_contracts": {"$each": [contract_object_id]}}
                           if contract_object_id else {})
                    }
                }
            )
            await policy_collection.update_one(
                {"_id": offer_id},
                {"$set": {"negotiation_id": body.negotiation_id,
                          "updated_at": datetime.utcnow()}}
            )
            await update_read_only_for_policy(negotiation_object_id, offer_id)

        message = {
            "message": "Offer created successfully",
            "offer_id": offer_id,
            "negotiation_id": str(body.negotiation_id),

        }
        await push_messages("create", message)
        return message

    except BaseException as e:
        error_message = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Exception: {str(e)}. Traceback: {error_message}")


@app.post("/provider/offer/initial", summary="Create a new initial offer")
async def create_initial_upcast_offer(
        master_password_input: str,
        body: UpcastPolicyObject = Body(..., description="The offer object"),
):
    await verify_master(master_password_input)
    try:
        # Normalise ODRL payload to keep stored policies aligned
        body = odrl_convertor(body)
        # Convert Pydantic model to dictionary
        body_dict = pydantic_to_dict(body)

        # Handle manual ID if provided
        if body.id:
            if await policy_collection.find_one({"_id": body.id}):  # Ensure ID is unique
                raise HTTPException(status_code=400, detail="Policy ID already exists")
            body_dict["_id"] = body.id  # Assign manual ID
        else:
            body_dict.pop("id", None)  # Remove 'id' if it's None to avoid issues

        # Change the policy type to "offer"
        body_dict["type"] = PolicyType.OFFER.value
        now = datetime.utcnow()
        body_dict["created_at"] = now
        body_dict["updated_at"] = now
        # Insert into MongoDB
        result = await policy_collection.insert_one(body_dict)

        offer_id = body.id if body.id else str(result.inserted_id)

        # Handle negotiation if applicable
        if body.negotiation_id:
            await negotiations_collection.update_one(
                {"_id": ObjectId(str(body.negotiation_id))},
                {
                    "$set": {"negotiation_status": NegotiationStatus.OFFERED,
                             "updated_at": datetime.utcnow()},
                    "$push": {"negotiations": offer_id}
                }
            )
            await policy_collection.update_one(
                {"_id": offer_id},
                {"$set": {"negotiation_id": body.negotiation_id,
                          "updated_at": datetime.utcnow()}}
            )
            await update_read_only_for_policy(body.negotiation_id, offer_id)

        return {"message": "Offer created successfully", "offer_id": offer_id,
                "negotiation_id": str(body.negotiation_id)}

    except BaseException as e:
        error_message = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.post("/provider/offer/initial_dataset", summary="Create a new initial offer from a dataset",
             response_model=UpcastPolicyObject)
async def create_initial_upcast_offer_from_dataset(
        current_user: User = Depends(verify_access_token_and_resolve_user),
        token: str = Depends(oauth2_scheme),
        body: Dict[str, Any] = Body(..., description="The dataset object"),
):
    negotiation_provider_user_id = None
    for ex in body['extras']:
        if ex['key'] == 'natural_language_document':
            natural_language_document = ex['value']
        if ex['key'] == 'negotiation_provider_user_id':
            negotiation_provider_user_id = ex['value']
        if ex['key'] == 'upcast':
            upcast_object = ex['value']
            try:
                if type(upcast_object) is dict:
                    upcast_object_graph = Graph().parse(data=upcast_object, format="json-ld")
                elif type(upcast_object) is str:
                    upcast_object = json.loads(upcast_object.replace("'", '"'))
                    upcast_object_graph = Graph().parse(data=upcast_object, format="json-ld")

                pc = UpcastPolicyConverter(upcast_object_graph)

                upcast_policy = pc.convert_to_policy()

            except BaseException as b:
                raise HTTPException(status_code=400, detail=f"UPCAST object could not be parsed: {b}")
    try:
        try:
            upcast_policy["resource_description_object"].pop("raw_object")
        except:
            pass
        if negotiation_provider_user_id is None:
            negotiation_provider_user_id = current_user.id

        upo = UpcastPolicyObject.parse_obj(upcast_policy)
        # If necessary, make changes on Upcast policy object

        # Normalise ODRL payload before persistence
        upo = odrl_convertor(upo)

        upo.consumer_id = ObjectId(negotiation_provider_user_id)
        now = datetime.utcnow()
        upo.created_at = now
        upo.updated_at = now
        # Insert the cloned policy into the policy collection
        result = await policy_collection.insert_one(pydantic_to_dict(upo))
        offer_id = result.inserted_id

        negotiation = UpcastNegotiationObject(
            user_id=ObjectId(current_user.id),
            title=upo.title,
            consumer_id=current_user.id,
            provider_id=upo.provider_id,  # Assuming provider_id is available in the request object
            negotiation_status=NegotiationStatus.REQUESTED,
            resource_description=upo.resource_description_object.dict(),
            dpw=upo.data_processing_workflow_object,
            nlp=upo.natural_language_document,
            conflict_status="",  # Initialize with an empty string
            negotiations=[offer_id],  # Add the request to negotiations list
            original_offer_id=offer_id,
            created_at=now,
            updated_at=now
        )

        result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
        negotiation_id = result.inserted_id

        # Update the request object and cloned policy (if any) with the new negotiation_id
        await policy_collection.update_one(
            {"_id": ObjectId(offer_id)},
            {"$set": {"negotiation_id": negotiation_id,
                      "updated_at": datetime.utcnow()}}
        )
        await update_read_only_for_policy(negotiation_id, offer_id)

        # Retrieve the offer from the database using the converted ObjectId
        offer = await policy_collection.find_one({"_id": offer_id})

        # Check if the offer exists
        if offer is None:
            raise HTTPException(status_code=404, detail="Offer not found")

        message = {
            "message": "Initial offer created successfully",
            "offer_id": str(offer_id),
            "negotiation_id": str(negotiation_id)
        }
        await push_messages("create", message, doConsumerPush=False)

        return UpcastPolicyObject(**pydantic_to_dict(offer, True))

    except BaseException as e:
        error_message = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.post("/provider/offer/initial_upcast_dataset", summary="Create a new initial offer "
                                                               "from an upcast dataset",
             response_model=UpcastPolicyObject)
async def create_initial_upcast_offer_from_dataset(
        current_user: User = Depends(verify_access_token_and_resolve_user),
        token: str = Depends(oauth2_scheme),
        body: Dict[str, Any] = Body(..., description="The dataset object"),
):
    current_user_id = current_user.id
    odrl_policy = {}
    negotiation_provider_user_id = None
    try:
        if isinstance(body, str):
            upcast_json = body
        elif isinstance(body, dict):
            upcast_json = json.dumps(body)
        else:
            raise ValueError("Unsupported UPCAST payload type")

        upcast_object = json.loads(upcast_json)

        upcast_object_graph = Graph().parse(data=upcast_json, format="json-ld")

        pc = UpcastPolicyConverter(upcast_object_graph, upcast_object)

        upcast_policy = pc.convert_to_policy()


    except BaseException as b:
        raise HTTPException(status_code=400, detail=f"UPCAST object could not be parsed: {b}")
    try:
        try:
            upcast_policy["resource_description_object"].pop("raw_object")
        except:
            pass

        upo = UpcastPolicyObject.parse_obj(upcast_policy)

        # Normalise ODRL payload before persistence
        upo = odrl_convertor(upo)

        # If necessary, make changes on Upcast policy object
        provider_lookup_value = upo.provider_id
        resolved_provider_id = None
        provider_doc = None
        if provider_lookup_value:
            try:
                resolved_provider_id = ObjectId(str(provider_lookup_value))
                provider_doc = await users_collection.find_one({"_id": resolved_provider_id})
            except (InvalidId, TypeError):

                provider_lookup_str = str(provider_lookup_value)
                escaped = re.escape(provider_lookup_str)

                # exact token in comma-separated org string
                token_pat = rf"(^|,\s*){escaped}(\s*,|$)"

                # whole word in other fields (won't match JOTIM)
                word_pat = rf"\b{escaped}\b"

                provider_doc = await users_collection.find_one({
                    "$or": [
                        {"organization": provider_lookup_value},  # array element match
                        {"organization": {"$regex": token_pat, "$options": "i"}},  # legacy string
                        {"name": {"$regex": word_pat, "$options": "i"}},  # whole word
                        {"username_email": {"$regex": word_pat, "$options": "i"}},  # whole word
                    ]
                })

                if not provider_doc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"contactPoint '{provider_lookup_str}' is not associated with "
                               f"any user, please provide a valid name, organization, username_email or a MongoDB _id"
                    )
                resolved_provider_id = provider_doc["_id"]
            if not provider_doc:
                raise HTTPException(status_code=404, detail="Provider user not found")
        else:
            raise HTTPException(status_code=400, detail="contactPoint is not provided!")

        consumer_doc = await users_collection.find_one({"_id": ObjectId(current_user_id)})
        if not consumer_doc:
            raise HTTPException(status_code=404, detail="Current consumer not found")

        upo.provider_id = resolved_provider_id
        upo.consumer_id = ObjectId(current_user_id)
        upo.user_id = ObjectId(current_user_id)
        now = datetime.utcnow()
        upo.created_at = now
        upo.updated_at = now

        contract_text = None
        contract_object_id = None
        contract_id_str = ""
        negotiation_id = ObjectId()
        try:
            contract_id_str, contract_text = await _request_contract_creation(
                policy=upo,
                negotiation_id=negotiation_id,
                request_id="",
                consumer_doc=consumer_doc,
                provider_doc=provider_doc,
                access_token=token,
            )
            contract_object_id = ObjectId(contract_id_str)
            upo.contract_id = contract_object_id
            if contract_text:
                upo.natural_language_document = contract_text
        except Exception as contract_exc:
            print(f"Failed to generate contract for initial upcast offer: {contract_exc}")

        policy_dict = pydantic_to_dict(upo)
        result = await policy_collection.insert_one(policy_dict)
        offer_id = result.inserted_id

        negotiation = UpcastNegotiationObject(
            user_id=ObjectId(current_user_id),
            title=upo.title,
            consumer_id=ObjectId(current_user_id),
            provider_id=ObjectId(upo.provider_id),  # Assuming provider_id is available in the request object
            negotiation_status=NegotiationStatus.OFFERED,
            resource_description=upo.resource_description_object.dict(),
            dpw=upo.data_processing_workflow_object,
            nlp=upo.natural_language_document,
            conflict_status="",  # Initialize with an empty string
            negotiations=[offer_id],  # Add the request to negotiations list
            negotiation_contracts=[contract_object_id] if contract_object_id else [],
            original_offer_id=offer_id,
            created_at=now,
            updated_at=now
        )

        negotiation_dict = pydantic_to_dict(negotiation)
        negotiation_dict["_id"] = negotiation_id
        await negotiations_collection.insert_one(negotiation_dict)

        # Update the request object and cloned policy (if any) with the new negotiation_id
        update_fields = {
            "negotiation_id": negotiation_id,
            "updated_at": datetime.utcnow()
        }
        if contract_object_id:
            update_fields["contract_id"] = contract_object_id
        if contract_text:
            update_fields["natural_language_document"] = contract_text

        await policy_collection.update_one(
            {"_id": ObjectId(offer_id)},
            {"$set": update_fields}
        )
        await update_read_only_for_policy(negotiation_id, offer_id)

        offer = await policy_collection.find_one({"_id": offer_id})

        if offer is None:
            raise HTTPException(status_code=404, detail="Offer not found")

        message = {
            "message": "Initial offer created successfully",
            "offer_id": str(offer_id),
            "negotiation_id": str(negotiation_id),

        }
        await push_messages("create", message, doConsumerPush=False)

        return UpcastPolicyObject(**pydantic_to_dict(offer, True))

    except BaseException as e:
        error_message = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.get("/users_list", summary="Get all users list")
async def get_all_users(current_user: User = Depends(verify_access_token_and_resolve_user)):
    users = await users_collection.find().to_list(length=None)
    for user in users:
        user["id"] = str(user.pop("_id"))
        user.pop("password")  # Convert _id to id and stringify
    users = [user for user in users if not user.get("is_admin", False)]
    return JSONResponse(content=users)


@router.get("/provider/offer/{offer_id}", summary="Get an existing offer", response_model=UpcastPolicyObject)
async def get_upcast_offer(
        offer_id: str = Path(..., description="The ID of the offer"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    print("/provider/offer/{offer_id}  -> get_upcast_offer")
    # Convert offer_id to ObjectId
    offer_object_id = ObjectId(offer_id)
    if secure:
        # Update to check ownership
        offer = await policy_collection.find_one({
            "_id": offer_object_id,
            "$or": [
                {"user_id": ObjectId(current_user.id)},
                {"consumer_id": ObjectId(current_user.id)},
                {"provider_id": ObjectId(current_user.id)}
            ]
        })
        if not offer:
            raise HTTPException(status_code=404, detail="Offer not found or you don't have permission to access it")
    else:
        # Retrieve the offer from the database using the converted ObjectId
        offer = await policy_collection.find_one({"_id": offer_object_id})

    # Check if the offer exists
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")

    # print("\n\n\n/provider/offer/{offer_id}  -> offer", offer)

    return UpcastPolicyObject(**pydantic_to_dict(offer, True))


@router.delete("/offer/{offer_id}", summary="Delete an offer")
async def delete_upcast_offer(
        offer_id: str = Path(..., description="The ID of the offer"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    try:
        offer_object_id = ObjectId(offer_id)
        if secure:
            # Find the offer with ownership check
            offer = await policy_collection.find_one({
                "_id": offer_object_id,
                "$or": [
                    {"user_id": ObjectId(current_user.id)},
                    {"consumer_id": ObjectId(current_user.id)},
                    {"provider_id": ObjectId(current_user.id)}
                ]
            })
        else:
            # Find the offer
            offer = await policy_collection.find_one({"_id": offer_object_id})

        if not offer:
            raise HTTPException(status_code=404, detail="Offer not found")

        # Delete the offer
        delete_result = await policy_collection.delete_one({"_id": offer_object_id})

        if delete_result.deleted_count == 0:
            raise HTTPException(status_code=404,
                                detail="Offer not found or you do not have permission to delete this offer")

        # If the offer is part of a negotiation, remove it from the negotiation's negotiations field
        if offer.get("negotiation_id"):
            await negotiations_collection.update_one(
                {"_id": offer["negotiation_id"]},
                {"$pull": {"negotiations": {"_id": offer_object_id}}}
            )

        return {"message": "Offer deleted successfully", "offer_id": offer_object_id,
                "negotiation_id": str(offer["negotiation_id"])}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


# @router.post("/provider/offer/finalize", summary="Accept an offer")
# async def accept_upcast_offer(
#     user_id: str = Header(..., description="The ID of the user"),
#     offer_id: str = Header(..., description="The ID of the offer")
# ):
#     return {"message": "Offer finalized successfully", "offer_id": offer_id}
#
# @router.get("/contract/{negotiation_id}", summary="Get a contract", response_model=Union[dict, UpcastContractObject])
# async def get_upcast_contract(
#         negotiation_id: str = Path(..., description="The ID of the negotiation"),
#         current_user: User = Depends(verify_access_token_and_resolve_user)
# ):
#     try:
#         if secure:
#             negotiation = await negotiations_collection.find_one({
#                 "_id": ObjectId(negotiation_id),
#                 "$or": [
#                     {"user_id": ObjectId(current_user.id)},
#                     {"consumer_id": ObjectId(current_user.id)},
#                     {"provider_id": ObjectId(current_user.id)}
#                 ]
#             })
#         else:
#             negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id)})
#
#         if not negotiation:
#             raise HTTPException(status_code=404, detail="Negotiation not found")
#
#         negotiations_list = negotiation.get("negotiations", [])
#         if not negotiations_list:
#             raise HTTPException(status_code=404, detail="No policies found in the negotiations")
#
#         request = await policy_collection.find_one({"_id": ObjectId(negotiations_list[-1])})
#
#         last_policy = negotiations_list[-1]
#         return UpcastContractObject(**pydantic_to_dict(request, True))
#     except BaseException as e:
#         error_message = traceback.format_exc()  # get the full traceback
#         raise HTTPException(status_code=500,
#                             detail=f"Exception: {str(e)}. Traceback: {error_message}")


#
# @router.post("/contract/sign", summary="Sign a contract (Under Construction)")
# async def sign_upcast_contract(
#     current_user: User = Depends(verify_access_token_and_resolve_user),
#     body: UpcastContractObject = Body(..., description="The contract sign object")
# ):
#     # Under Construction
#     return {"message": "This endpoint is under construction"}

@router.get("/users", summary="Get all users")
async def get_all_users(master_password_input: str):
    # Check for existing admin user
    admin_user = await users_collection.find_one({"is_admin": True})

    if admin_user is not None:
        # Use the admin's hashed password as the master password
        master_password = admin_user.get("password")
    else:
        # Use the master password from the environment variable
        raw_master_password = os.getenv("MASTER_PASSWORD")
        if not raw_master_password:
            raise HTTPException(
                status_code=500, detail="MASTER_PASSWORD environment variable not set"
            )

        master_password = get_password_hash(raw_master_password)

        # Initialize the first admin user if no admin exists
        first_admin = {
            "username_email": "admin@example.com",
            "password": master_password,
            "is_admin": True
        }
        await users_collection.insert_one(first_admin)
    # Verify the provided master password
    if not verify_password(master_password_input, master_password):
        raise HTTPException(status_code=403, detail="Invalid master password")
    else:
        users = await users_collection.find().to_list(length=None)
        for user in users:
            user["id"] = str(user.pop("_id"))  # Convert _id to id and stringify
        return JSONResponse(content=users)


async def get_negotiation_id(offer_id: str, negotiation_id: str):
    if negotiation_id:
        return negotiation_id

    # Get the offer from the database
    offer = await policy_collection.find_one({"_id": ObjectId(offer_id)})
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")

    negotiation_id = offer.get("negotiation_id")
    if negotiation_id is None:
        raise HTTPException(status_code=400, detail="Negotiation ID not found in the offer")

    return negotiation_id


@router.post("/negotiation/consumer/accept/{negotiation_id}", summary="Accept an offer")
async def accept_upcast_request(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        # offer_id: str = Path(..., description="The ID of the offer"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    # negotiation_id = await get_negotiation_id(offer_id, negotiation_id)
    try:
        update_result = await negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$set": {"negotiation_status": NegotiationStatus.ACCEPTED.value,
                      "updated_at": datetime.utcnow()}}
        )
        await update_read_only_for_policy(negotiation_id)
        message = {"message": "Offer accepted successfully", "negotiation_id": negotiation_id,
                   "negotiation_status": NegotiationStatus.ACCEPTED.value}
        await push_messages("update", message)
        return message
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.post("/negotiation/consumer/verify/{negotiation_id}", summary="Verify a request")
async def verify_upcast_request(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        # offer_id: str = Path(..., description="The ID of the request"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    # negotiation_id = await get_negotiation_id(offer_id, negotiation_id)
    try:
        update_result = await negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$set": {"negotiation_status": NegotiationStatus.VERIFIED.value,
                      "updated_at": datetime.utcnow()}}
        )
        await update_read_only_for_policy(negotiation_id)
        message = {"message": "Offer verified successfully", "negotiation_id": negotiation_id,
                   "negotiation_status": NegotiationStatus.VERIFIED.value}
        await push_messages("update", message)
        return message
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.post("/negotiation/provider/agree/{negotiation_id}", summary="Agree on a request")
async def agree_upcast_offer(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    # negotiation_id = await get_negotiation_id(request_id, negotiation_id)
    try:
        update_result = await negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$set": {"negotiation_status": NegotiationStatus.AGREED.value,
                      "updated_at": datetime.utcnow()}}
        )
        await update_read_only_for_policy(negotiation_id)
        message = {"message": "Request agreed successfully", "negotiation_id": str(negotiation_id),
                   "negotiation_status": NegotiationStatus.AGREED.value}
        await push_messages("update", message)
        return message
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.post("/negotiation/provider/finalize/{negotiation_id}", summary="Finalize a negotiation")
async def finalize_upcast_offer(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        # offer_id: str = Path(..., description="The ID of the offer"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    # negotiation_id = await get_negotiation_id(offer_id, negotiation_id)
    try:
        update_result = await negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$set": {"negotiation_status": NegotiationStatus.FINALIZED.value,
                      "updated_at": datetime.utcnow()}}
        )

        await update_read_only_for_policy(negotiation_id)

        negotiaion_coll = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id)})

        if len(negotiaion_coll.get("negotiation_contracts", [])) >= 1:

            last_contract_id = negotiaion_coll["negotiation_contracts"][-1]
        else:
            last_contract_id = "no contract available"

        message = {"message": "Offer finalized successfully", "negotiation_id": str(negotiation_id),
                   "negotiation_status": NegotiationStatus.FINALIZED.value,
                   "finalized_contract": str(last_contract_id)
                   }
        await push_messages("update", message, doContractsKafkaPush=True)
        return message
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.post("/negotiation/terminate/{negotiation_id}", summary="Terminate a negotiation")
async def terminate_upcast_negotiation(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(verify_access_token_and_resolve_user)
):
    try:
        update_result = await negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$set": {"negotiation_status": NegotiationStatus.TERMINATED.value,
                      "updated_at": datetime.utcnow()}}
        )
        await update_read_only_for_policy(negotiation_id)

        if update_result.matched_count == 0:
            raise HTTPException(status_code=404,
                                detail="Negotiation not found or you do not have permission to terminate this negotiation")
        message = {"message": "Negotiation terminated successfully", "negotiation_id": negotiation_id,
                   "negotiation_status": NegotiationStatus.TERMINATED.value}
        await push_messages("update", message)
        return message
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.post("/agent/new", summary="Create a new agent")
async def create_new_agent(
        user_id: str = Header(..., description="The ID of the user"),
        body: Dict = Body(..., description="The negotiation id, original offer id, agent type and preferences")
):
    try:
        print('create new agent')

        # extract original offer id from request and find the policy in mongodb
        original_offer_id = body.get("original_offer_id")

        # extract negotiation id from request and find the negotiation in mongodb
        negotiation_id = body.get("negotiation_id")
        negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id)})
        if not negotiation:
            raise HTTPException(status_code=404, detail="Negotiation not found")

        negotiations_list = negotiation.get("negotiations", [])
        # print(f'negotiations list {negotiations_list}')

        negotiations_list_no_duplicates = list(dict.fromkeys(negotiations_list))
        # print(f'negotiations list no duplicates {negotiations_list_no_duplicates}')

        previous_request_id = negotiations_list_no_duplicates[-1]
        previous_request = await policy_collection.find_one({"_id": ObjectId(previous_request_id)})
        if previous_request:
            previous_request_dict = UpcastPolicyObject(**pydantic_to_dict(previous_request, True))
        else:
            raise HTTPException(status_code=404, detail="Request not found")

        if len(negotiations_list_no_duplicates) < 2:
            print('less than 2 elements in negotiations list')
            # If there is only one negotiation, use the original offer ID
            previous_offer_id = original_offer_id
        else:
            print('2 or more elements in negotiations list')
            previous_offer_id = negotiations_list_no_duplicates[-2]

        previous_offer = await policy_collection.find_one({"_id": ObjectId(previous_offer_id)})
        if previous_offer:
            previous_offer_dict = UpcastPolicyObject(**pydantic_to_dict(previous_offer, True))
        else:
            raise HTTPException(status_code=404, detail="Request not found")

        print(f'previous offer id {previous_offer_id}')
        print(f'previous request id {previous_request_id}')

        # convert ObjectId to string
        previous_offer["_id"] = str(previous_offer["_id"])
        previous_request["_id"] = str(previous_request["_id"])

        agent_type = PartyType(body.get("agent_type"))

        print(f'agent type {agent_type}')

        # Extract 'preferences'
        preferences = body.get("preferences")

        print(f'preferences {preferences}')

        # if preferences isn't already a list, make preferences into a list of one
        if not isinstance(preferences, list):
            preferences = [preferences]

        print(f'preferences {preferences}')

        actor_preference = Preference(
            key=PolicyKey.ACTOR,
            upper_value=preferences[0].get('maxPrefActor', ''),
            lower_value=preferences[0].get('minPrefActor', '')
        )

        print(f'actor preference {actor_preference}')

        action_preference = Preference(
            key=PolicyKey.ACTION,
            upper_value=preferences[0].get('maxPrefAction', ''),
            lower_value=preferences[0].get('minPrefAction', '')
        )

        purpose_preference = Preference(
            key=PolicyKey.PURPOSE,
            upper_value=preferences[0].get('maxPrefPurpose', ''),
            lower_value=preferences[0].get('minPrefPurpose', '')
        )

        price_preference = Preference(
            key=PolicyKey.PRICE,
            upper_value=preferences[0].get('maxPrefPrice', ''),
            lower_value=preferences[0].get('minPrefPrice', '')
        )

        print(f'price preference {price_preference}')

        recommender_agent_record = RecommenderAgentRecord(
            agent_type=agent_type,
            preferences=[actor_preference, action_preference, purpose_preference, price_preference],
            previous_offer=previous_offer_dict,
            previous_request=previous_request_dict,
            negotiation_id=negotiation_id,
            user_id=user_id,
        )

        print(f'Recommender agent record user id {recommender_agent_record.user_id}')

        result = await agent_records_collection.insert_one(pydantic_to_dict(recommender_agent_record))
        inserted_id = result.inserted_id  # Get the ID of the inserted document
        print(f'Inserted ID: {inserted_id}')

        # get the _id of the object just inserted

        return {"message": "agent created successfully", "agent_id": str(inserted_id),
                "recommender_agent_record": recommender_agent_record}

    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


# get all recommender agent records from a user id 
@router.get("/agent", summary="Get recommender agent records by user ID")
async def get_recommender_agent_records(
        user_id: str = Header(..., description="The ID of the user"),
):
    try:
        agent_records = await agent_records_collection.find({"user_id": user_id}).to_list(length=None)
        if not agent_records:
            raise HTTPException(status_code=404, detail="No agent records found for this user")

        return [RecommenderAgentRecord(**pydantic_to_dict(agent_record, True)) for agent_record in agent_records]
    except BaseException as e:
        error_message = traceback.format_exc()


# get recommender agent records from a user id for a particular negotiation
@router.get("/agent/{negotiation_id}", summary="Get recommender agent records by user ID and negotiation ID")
async def get_recommender_agent_records_for_negotiation(
        user_id: str = Header(..., description="The ID of the user"),
        negotiation_id: str = Path(..., description="The ID of the negotiation")
):
    try:
        agent_records = await agent_records_collection.find({"user_id": user_id,
                                                             "negotiation_id": negotiation_id
                                                             }).to_list(length=None)
        if not agent_records:
            raise HTTPException(status_code=404, detail="No agent records found for this user")

        return [RecommenderAgentRecord(**pydantic_to_dict(agent_record, True)) for agent_record in agent_records]
    except BaseException as e:
        error_message = traceback.format_exc()


# get the latest recommender agent records from a user id for a particular negotiation
@router.get("/agent/latest/{negotiation_id}",
            summary="Get latest recommender agent record for a specified user ID and negotiation ID")
async def get_latest_recommender_agent_record(
        user_id: str = Header(..., description="The ID of the user"),
        negotiation_id: str = Path(..., description="The ID of the negotiation")
):
    try:
        agent_record = await agent_records_collection.find_one({"user_id": user_id,
                                                                "negotiation_id": negotiation_id},
                                                               sort=[("created_at", -1)]
                                                               # Sort descending by creation time
                                                               )
        if not agent_record:
            raise HTTPException(status_code=404, detail="No agent records found for this user in this negotiation")

        return RecommenderAgentRecord(**pydantic_to_dict(agent_record))

    except BaseException as e:
        error_message = traceback.format_exc()


async def push_messages(action, message, doKafkaPush=True, doProviderPush=True, doConsumerPush=True, doContractsKafkaPush=False):
    negotiation_id = message.get("negotiation_id")
    provider_username = os.getenv("PROVIDER_DASHBOARD_USERNAME")
    provider_password = os.getenv("PROVIDER_DASHBOARD_PASSWORD")
    # print(f"[push_messages] negotiation_id={negotiation_id}")
    # print(f"[push_messages] provider_username_set={bool(provider_username)} provider_password_set={bool(provider_password)} push_provider_enabled={push_provider_enabled}")
    negotiation_uri = None
    if negotiation_id:
        try:
            negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id)})
            if negotiation:
                negotiation_uri = negotiation.get("resource_description", {}).get("uri")
        except Exception as exc:
            print(f"[push_messages] failed to resolve negotiation {negotiation_id}: {exc}")
    # print(f"[push_messages] negotiation_uri_present={bool(negotiation_uri)}")

    if doProviderPush:
        start = time.perf_counter()
        await push_provider_dashboard_message(action, message)
        logging.debug(f"push_provider_dashboard_message took {time.perf_counter() - start:.3f} seconds")

    if doConsumerPush:
        start = time.perf_counter()
        await push_consumer_dashboard_message(action, message)
        logging.debug(f"push_consumer_dashboard_message took {time.perf_counter() - start:.3f} seconds")

    if doKafkaPush:
        start = time.perf_counter()
        await push_kafka_message(action, message)
        logging.debug(f"push_kafka_message took {time.perf_counter() - start:.3f} seconds")

    if doContractsKafkaPush:
        start = time.perf_counter()
        await push_contract_kafka_message(action, message)
        logging.debug(f"push_kafka_contract_message took {time.perf_counter() - start:.3f} seconds")

async def push_kafka_message(action, message):
    try:
        if kafka_enabled:
            if action == "create":
                action = action
                message_json = {
                    "source": "negotiation-plugin",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "nid": message["negotiation_id"],
                    "action": "create",
                    "result": message
                }
            else:
                action = message["negotiation_status"]
                message_json = {
                    "source": "negotiation-plugin",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "nid": message["negotiation_id"],
                    "action": message["negotiation_status"],
                    "result": message
                }
            producer.produce("negotiation-plugin", json.dumps(message_json).encode('utf-8'), callback=delivery_report)
            # producer.flush()  # Ensure all messages are delivered before exiting
            await asyncio.to_thread(producer.flush)
            logging.debug(f"Successful push to kafka. action:{action}")

    except BaseException as b:
        logging.error("Failed to push Kafka message", exc_info=True)

async def push_contract_kafka_message(action, message):
    try:
        if kafka_enabled:
            message_json = {
                "source": "negotiation-plugin",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "nid": message["negotiation_id"],
                "action": message["negotiation_status"],
                "result": message
            }
            producer.produce("UPCAST-CONTRACTS", json.dumps(message_json).encode("utf-8"), callback=delivery_report)
            await asyncio.to_thread(producer.flush)
            logging.debug(f"Sent contract message to topic UPCAST-CONTRACTS")
    except BaseException:
        logging.error("Failed to push contract message", exc_info=True)

def convert_all(obj):
    if isinstance(obj, dict):
        return {k: convert_all(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_all(i) for i in obj]
    elif isinstance(obj, (ObjectId, datetime)):
        return str(obj)
    return obj


# async def push_consumer_dashboard_message(action, object):
#     try:
#         if push_consumer_enabled:
#             username = os.getenv("CONSUMER_DASHBOARD_USERNAME")
#             password = os.getenv("CONSUMER_DASHBOARD_PASSWORD")
#             username_encoded = urllib.parse.quote(username)
#             password_encoded = urllib.parse.quote(password)
#             url = "https://sso.ict-abovo.gr/realms/goodflows/protocol/openid-connect/token"
#
#             payload = f'grant_type=password&client_id=goodflows-api&username={username_encoded}&password={password_encoded}&client_secret=imPnW4YevqTWmUBx6NSCC2v4kad7Xphp'
#             headers = {
#                 'Content-Type': 'application/x-www-form-urlencoded',
#                 'cache-control': 'no-cache'
#             }
#
#             response = requests.request("POST", url, headers=headers, data=payload)
#             access_token = json.loads(response.content.decode("UTF-8"))["access_token"]
#
#             url = "https://upcast-api.ict-abovo.gr/negotiation"
#
#             negotiation = await negotiations_collection.find_one({"_id": ObjectId(object["negotiation_id"])})
#             if negotiation:
#                 #                clean_obj = convert_all(negotiation)
#                 #                payload = json.dumps(negotiation, indent=2)
#                 neg_object = pydantic_to_dict(negotiation, True)
#                 payload = json.dumps(neg_object, default=str)
#                 headers = {
#                     'Content-Type': 'application/json',
#                     'Authorization': f"Bearer {access_token}"
#                 }
#                 # print ("push_consumer_dashboard_message -> payload", payload)
#                 response = requests.put(url, headers=headers, data=payload)
#                 if response.status_code == 200:
#                     logging.debug(
#                         f"Successful push to consumer dashboard. Status: {response.status_code}, Response: {response.text}")
#                 else:
#                     logging.error(
#                         f"Error consumer push. Status: {response.status_code}, Response: {response.text}, payload:{payload}, headers: {headers} ")
#
#             #     return True
#             # else:
#             #     return False
#         # else:
#         #     return False
#     except BaseException as b:
#
#         logging.error("Failed to push message to consumer dashboard", exc_info=True)


async def push_consumer_dashboard_message(action, object):
    try:
        if push_consumer_enabled:
            username = os.getenv("CONSUMER_DASHBOARD_USERNAME")
            password = os.getenv("CONSUMER_DASHBOARD_PASSWORD")

            # Old code:
            # username_encoded = urllib.parse.quote(username)
            # password_encoded = urllib.parse.quote(password)
            #
            # New code:
            # Validate env values before trying to build the token request. This
            # avoids TypeError when username/password are missing or not strings.
            if not isinstance(username, str) or not username.strip():
                logging.error("Consumer dashboard push skipped: CONSUMER_DASHBOARD_USERNAME is missing or empty")
                return
            if not isinstance(password, str) or not password.strip():
                logging.error("Consumer dashboard push skipped: CONSUMER_DASHBOARD_PASSWORD is missing or empty")
                return

            token_url = "https://sso.ict-abovo.gr/realms/goodflows/protocol/openid-connect/token"
            token_payload = {
                "grant_type": "password",
                "client_id": "goodflows-api",
                "username": username,
                "password": password,
                "client_secret": "imPnW4YevqTWmUBx6NSCC2v4kad7Xphp",
            }
            token_headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'cache-control': 'no-cache'
            }

            async with httpx.AsyncClient(timeout=4.0) as client:
                token_resp = await client.post(token_url, data=token_payload, headers=token_headers)
                if token_resp.status_code != 200:
                    logging.error(f"Consumer dashboard token error: {token_resp.status_code} {token_resp.text}")
                    return
                access_token = token_resp.json()["access_token"]

                url = "https://upcast-api.ict-abovo.gr/negotiation"
                negotiation = await negotiations_collection.find_one({"_id": ObjectId(object["negotiation_id"])})
                if not negotiation:
                    return

                neg_object = pydantic_to_dict(negotiation, True)
                payload = json.dumps(neg_object, default=str)
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f"Bearer {access_token}"
                }

                resp = await client.put(url, headers=headers, content=payload)
                # log resp.status_code / resp.text here
    except Exception:
        logging.error("Failed to push message to consumer dashboard", exc_info=True)



async def push_provider_dashboard_message(action, object):
    try:
        if push_provider_enabled:
            username = os.getenv("PROVIDER_DASHBOARD_USERNAME")
            password = os.getenv("PROVIDER_DASHBOARD_PASSWORD")

            if not isinstance(username, str) or not username.strip():
                logging.error("Provider dashboard push skipped: PROVIDER_DASHBOARD_USERNAME is missing or empty")
                return
            if not isinstance(password, str) or not password.strip():
                logging.error("Provider dashboard push skipped: PROVIDER_DASHBOARD_PASSWORD is missing or empty")
                return

            # Token retrieval (you said this works)
            url = "https://keycloak.maggioli-research.gr/auth/realms/upcast-dev/protocol/openid-connect/token"
            payload = {
                "client_id": "upcast-angular",
                "username": username,
                "password": password,
                "grant_type": "password"
            }
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(url, data=payload, headers=headers, timeout=3)

                if response.status_code == 200:
                    data = response.json()
                    access_token = data.get("access_token")
                    logging.debug(f"Access Token retrieved successfully: {access_token[:20]}...")
                else:
                    logging.error(f"Token Error: {response.status_code} {response.text}")
                    return

                negotiation_id = str(object["negotiation_id"])
                logging.debug(f"Processing action: {action} for negotiation_id: {negotiation_id}")

                if action == "create":
                    # Debug the database query
                    logging.debug(f"Querying database for negotiation_id: {negotiation_id}")

                    # Make sure this is awaited if using async MongoDB driver
                    negotiation = await negotiations_collection.find_one({"_id": ObjectId(object["negotiation_id"])})

                    if negotiation:
                        logging.debug("Negotiation found in database")
                        neg_object = pydantic_to_dict(negotiation, True)

                        # Extract distribution URL
                        distribution_url = None
                        resource_desc = neg_object.get("resource_description")
                        if isinstance(resource_desc, dict):
                            distribution = resource_desc.get("distribution")
                            if isinstance(distribution, dict):
                                distribution_url = distribution.get("url")

                        if not distribution_url:
                            logging.error(
                                f"Missing or invalid distribution.url in negotiation object: {neg_object.keys()}")
                            return
                        logging.debug(f"Distribution URL extracted: {distribution_url}")

                        url = "https://dev.upcast.maggioli-research.gr/upcast-service/api/negotiationplugin/create"
                        payload = {
                            "negotiationId": negotiation_id,
                            "url": distribution_url
                        }

                        headers = {
                            'Content-Type': 'application/json',
                            'Authorization': f'Bearer {access_token}'
                        }

                        # Log the request details
                        logging.debug(f"Second POST URL: {url}")
                        logging.debug(f"Second POST Payload: {json.dumps(payload)}")
                        logging.debug(f"Second POST Headers: {headers}")

                        # Make the second request
                        response = await client.post(url, json=payload, headers=headers, timeout=10)

                        st = response.status_code
                        resp = response.text

                        logging.debug(f"Second POST Status: {st}")
                        logging.debug(f"Second POST Response: {resp}")

                        if response.status_code == 200:
                            logging.debug(f"Successful push to provider dashboard. Status: {st}, Response: {resp}")
                        else:
                            logging.error(
                                "Error pushing to provider dashboard. "
                                f"Status: {st}, Response: {resp}, "
                                f"negotiation_id: {negotiation_id}, distribution_url: {distribution_url}, payload: {payload}"
                            )
                            # Try to parse error response
                            try:
                                error_data = response.json()
                                logging.error(f"Error details: {error_data}")
                            except:
                                pass
                    else:
                        logging.error(f"Negotiation not found in database for ID: {negotiation_id}")

                else:  # update status
                    status = str(object["negotiation_status"])
                    url = f"https://dev.upcast.maggioli-research.gr/upcast-service/api/negotiationplugin/updatestatus/{negotiation_id}/{status}"

                    headers = {
                        'Authorization': f'Bearer {access_token}'
                    }

                    logging.debug(f"Status update URL: {url}")
                    logging.debug(f"Status update Headers: {headers}")

                    # Fixed the original bug here
                    response = await client.post(url, headers=headers, timeout=10)
                    st = response.status_code
                    resp = response.text

                    logging.debug(f"Status update response: {st} - {resp}")

    except Exception as e:
        logging.error("Failed to push message to provider dashboard", exc_info=True)


@router.post("/user/verify-token/")
async def verify_token(token: str = Body(..., description="JWT token to verify")):
    """
    Verify a JWT token and return user information if valid.

    This endpoint validates the provided JWT token and returns the user's details
    if the token is valid and not blacklisted.

    Args:
        token: The JWT token to verify

    Returns:
        dict: User information and token validity status

    Raises:
        HTTPException: If token is invalid, expired, or blacklisted
    """
    try:
        current_user = await verify_access_token_and_resolve_user(token)
        user = await users_collection.find_one({"_id": ObjectId(str(current_user.id))})
        if user is None:
            raise HTTPException(status_code=401, detail="User not found")

        return {
            "valid": True,
            "user": {
                "id": str(user["_id"]),
                "username_email": user["username_email"],
                "type": user["type"],
            }
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


@router.get("/user/verify-token/")
async def verify_token_get(current_user: User = Depends(verify_access_token_and_resolve_user)):
    """
    Verify the token from Authorization header (GET method).

    This endpoint uses the existing authentication dependency to verify
    the token from the Authorization header.

    Returns:
        dict: User information and token validity status
    """
    user_response = {
        "id": str(current_user.id),
        "username_email": current_user.username_email,
        "type": current_user.type,
    }

    return {
        "valid": True,
        "user": user_response,
        "message": "Token is valid"
    }


def delivery_report(err, msg):
    """ Callback for message delivery report """
    if err is not None:
        print(f"Message delivery failed: {err}")
    else:
        print(f"Message delivered to {msg.topic()} [{msg.partition()}]")


app.include_router(router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
