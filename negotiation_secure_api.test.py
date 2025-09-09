import asyncio
import json
import os
import time
import traceback
import urllib.parse
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Dict, Optional, Any, Union

import requests
from confluent_kafka import Producer, KafkaException
import jwt
from bson import ObjectId
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
from pydantic import Field, EmailStr
from pydantic import field_validator
from rdflib import Graph
from starlette.responses import JSONResponse

from PolicyConverter import UpcastPolicyConverter
from data_model import User, UpcastNegotiationObject, UpcastPolicyObject, UpcastResourceDescriptionObject, \
    PolicyDiffObject, UpcastContractObject, PolicyChange, PolicyDiffResponse, UpcastPolicyConverter, PolicyType, \
    PartyType, NegotiationStatus, pydantic_to_dict, Preference, PolicyKey, RecommenderAgentRecord, \
    NegotiationCreationRequest
from recommender.agent import Proposal
from recommender.agent import new_offer, new_request

import httpx
import json
import logging


secure = True

import logging

logging.basicConfig(
    level=logging.INFO,  # You can change this to DEBUG for more detailed output
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Load environment variables from .env file
root_path="/negotiation-api-test"
app = FastAPI(
    title="Negotiation Plugin API",
    description="UPCAST Negotiation Plugin API",
    version="1.0",
    root_path=root_path
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=root_path+"/user/login/")  # Adjusted to match the login route

origins = ["*",
           "http://127.0.0.1:8000",
           "http://localhost:8000",
           "http://62.171.168.208:8000" ,
           "http://62.171.168.208:8001" ,
           "http://62.171.168.208:8002",
            "http://127.0.0.1:8001",
           "http://localhost:8001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# Load environment variables from .env file
load_dotenv(dotenv_path=".env.test")

# Define Kafka broker configuration
kafka_conf = {
    'bootstrap.servers': os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"),
    'security.protocol': os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
}

# kafka_conf = {
#     'bootstrap.servers': os.getenv("KAFKA_BOOTSTRAP_SERVERS"),
#     'security.protocol': os.getenv("KAFKA_SECURITY_PROTOCOL"),
#     'sasl.mechanism': os.getenv("KAFKA_SASL_MECHANISM"),
#     'sasl.username': os.getenv("KAFKA_SASL_USERNAME"),
#     'sasl.password': os.getenv("KAFKA_SASL_PASSWORD")
# }


kafka_enabled = False
push_consumer_enabled = True
push_provider_enabled = True
# Create Producer instance
# try:
#     producer = Producer(kafka_conf)
#     producer.list_topics(timeout=2)  # Set a timeout to avoid blocking indefinitely
#     kafka_enabled = True
# except KafkaException as e:
#     print(f"Kafka Producer error: {e}")
#     kafka_enabled = False
#     producer = None  # Ensure the provider is not used further

MONGO_USER = os.getenv("MONGO_USER")
print(f'MONGO_USER {MONGO_USER}')
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
print(f'MONGO_PASSWORD {MONGO_PASSWORD}')
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
print(f'MONGO_HOST {MONGO_HOST}')
MONGO_PORT = os.getenv("MONGO_PORT")
print(f'MONGO_PORT {MONGO_PORT}')
if MONGO_PORT: # Assumption: A local or remote installation of MongoDB is provided.
    MONGO_PORT = int(MONGO_PORT)
    MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}"
else: # Assumption: The database is stored in mongodb cloud.
    MONGO_URI = f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}/?retryWrites=true&w=majority&appName=Cluster0"


client = AsyncIOMotorClient(MONGO_URI)
print(f'MONGO_URI {MONGO_URI}')
db = client.upcast
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


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Check if the token is blacklisted
    if await is_token_blacklisted(token):
        raise credentials_exception

    try:
        # Decode the token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except Exception:
        raise credentials_exception

    # Fetch the user from the database
    user = await users_collection.find_one({"username_email": email})
    if user is None:
        raise credentials_exception

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

@router.put("/user/update-password", response_model=User)
async def update_user_password(
    master_password_input: str,
    user_update: User
):
    """
    Updates a user's password. Requires validation of the master password.
    """
    # Check for existing admin user
    await verify_master(master_password_input)
    # Verify the provided master password


    # Fetch the user to update
    existing_user = await users_collection.find_one({"username_email": user_update.username_email})

    if not existing_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Hash the new password
    updated_password_hash = get_password_hash(user_update.password)

    # Update the user's password in the database
    update_result = await users_collection.update_one(
        {"_id": existing_user["_id"]},
        {"$set": {"password": updated_password_hash}}
    )

    if update_result.modified_count == 0:
        raise HTTPException(status_code=500, detail="Failed to update password")

    # Return the updated user (excluding the password for security)
    updated_user = await users_collection.find_one({"_id": existing_user["_id"]})
    updated_user["password"] = None  # Avoid returning the password

    return updated_user


@app.delete("/user/{user_id}")
async def delete_user(user_id: str, master_password_input: str):
    """
    Deletes a user by their ID.
    """
    delete_result = await users_collection.delete_one({"_id": ObjectId(user_id)})

    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "User deleted successfully"}


@app.post("/user/register", response_model=User)
async def register_user(user: User, master_password_input: str):
    """
    Registers a new user. Requires validation of the master password.
    """
    await verify_master(master_password_input)
    # Verify the provided master password
    #if not verify_password(master_password_input, master_password):
    #   raise HTTPException(status_code=403, detail="Invalid master password")
    #else:
    # Check if the email is already registered
    if await users_collection.find_one({"username_email": user.username_email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    is_strong, resp = await is_strong_password(user.password)
    if is_strong:
        try:

            # Hash the user's password
            user.password = get_password_hash(user.password)
            # Insert the new user into the database
            user_dict = user.dict(by_alias=True, exclude_unset=True)
            result = await users_collection.insert_one(user_dict)
            user_dict["_id"] = str(result.inserted_id)
        except:
            raise HTTPException(status_code=400, detail="User cannot be created (possible reason, duplicate user ID)")
        return user_dict
    else:
        raise HTTPException(status_code=400, detail=resp)


# User Login
@router.post("/user/login/")
async def login_user(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await users_collection.find_one({"username_email": form_data.username})
    if not user or not verify_password(form_data.password, user["password"]):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username_email"]}, expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer", "user_id":str(user["_id"]), "user_type":user["type"]}


@router.get("/user/details/", response_model=User, summary="Get details of a user")
async def get_user_details(
        user_id: Optional[str] = Query(None,
                                       description="ID of the user to fetch. If not provided, returns current user's details"),
        current_user: User = Depends(get_current_user)
):
    """
    Retrieve user details.

    This endpoint requires authentication and returns user profile information.
    - If no user_id is provided, it returns the current user's details
    - If a user_id is provided, it returns that user's details (if authorized)

    Args:
        user_id: Optional ID of the user to fetch
        current_user: The currently authenticated user

    Returns:
        User: The user details object
    """
    try:
        # If no user_id is provided, use the current user's ID
        target_user_id = user_id if user_id else current_user.id

        # Fetch the user from the database
        user = await users_collection.find_one({"_id": ObjectId(target_user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Convert ObjectId to string for the response
        user["_id"] = str(user["_id"])

        # Return the user without the password field for security
        if "password" in user:
            user.pop("password")

        return user

    except Exception as e:
        error_message = traceback.format_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve user details: {str(e)}. Traceback: {error_message}"
        )


@router.post("/user/logout/")
async def logout_user(request: Request):
    token = request.headers.get("Authorization")
    if not token or not token.startswith("Bearer "):
        raise HTTPException(status_code=400, detail="No token provided")

    token = token.split("Bearer ")[1]
    payload = decode_access_token(token)  # Validate and decode token

    # Add token to the blacklist with its expiry
    expiry = payload.get("exp", datetime.utcnow() + timedelta(seconds=0))
    blacklist[token] = expiry
    return {"message": "Successfully logged out"}


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
        #current_user: User = Depends(get_current_user),
        body: RecommenderAgentRecord = Body(..., description="The recommender agent record")
):
    result = new_request(body)
    return result 

@router.post("/provider/recommend", summary="Recommend a request", response_model=Proposal)
def provider_recommend(
        #current_user: User = Depends(get_current_user),
        body: RecommenderAgentRecord = Body(..., description="The recommender agent record")
):
    result = new_offer(body)
    return result 

@router.post("/negotiation/create", summary="Create a negotiation")
async def create_upcast_negotiation(current_user: User = Depends(get_current_user),
        body: UpcastPolicyObject = Body(..., description="The request object")
):
    try:
        conflict_status = "no conflict"

        # Retrieve consumer and provider objects from users_collection
        consumer = await users_collection.find_one({"_id": ObjectId(body.consumer_id)})
        provider = await users_collection.find_one({"_id": ObjectId(body.provider_id)})

        if consumer is None or provider is None:
            raise HTTPException(status_code=404, detail="Consumer or provider not found")

        body.type = PolicyType.REQUEST.value
        # Save the offer to MongoDB

        body.consumer_id = ObjectId(str(body.consumer_id))
        body.provider_id = ObjectId(str(body.provider_id))

        now = datetime.utcnow()
        body["created_at"] = now
        body["updated_at"] = now
        result = await policy_collection.insert_one(pydantic_to_dict(body))
        # Retrieve the generated _id
        request_id = str(result.inserted_id)

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
            original_offer_id=request_id,
            created_at=now,
            updated_at=now
        )

        result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
        if result.inserted_id:

            # Update the request object and cloned policy (if any) with the existing negotiation_id
            await policy_collection.update_one(
                {"_id": ObjectId(request_id)},
                {
                    "$set": {
                        "negotiation_id": result.inserted_id,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            message = {"message": "Negotiation created successfully",
                       "negotiation_id": str(result.inserted_id)}
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
        current_user: User = Depends(get_current_user)
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
            return UpcastNegotiationObject(**pydantic_to_dict(negotiation, True))

        raise HTTPException(status_code=404, detail="Negotiation not found")
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.get("/negotiation/policies/{negotiation_id}", summary="Get policies related to a negotiation", response_model=List[UpcastPolicyObject])
async def get_policies_for_negotiation(
    negotiation_id: str = Path(..., description="The ID of the negotiation"),
    current_user: User = Depends(get_current_user)
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


@router.get("/negotiation", summary="Get negotiations")#, response_model=List[UpcastNegotiationObject])
async def get_upcast_negotiations(
    current_user: User = Depends(get_current_user)
):


    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Retrieve negotiations where the user is either a consumer or a provider
    #negotiations = await negotiations_collection.find(
    #    {"$or": [{"consumer_id": ObjectId(current_user.id)}, {"provider_id": ObjectId(current_user.id)}, {"user_id": ObjectId(current_user.id)}]}
    #).to_list(length=None)
    negotiations = await negotiations_collection.find(
        {"$or": [{"consumer_id": ObjectId(current_user.id)}, {"provider_id": ObjectId(current_user.id)}, {"user_id": ObjectId(current_user.id)}]}
    ).to_list(length=None)

    if not negotiations:
        return []
        # raise HTTPException(status_code=404, detail="No negotiations found for this user")


    return [pydantic_to_dict(negotiation, True) for negotiation in negotiations]
    #return [UpcastNegotiationObject(**pydantic_to_dict(negotiation, True)) for negotiation in negotiations]


@router.put("/negotiation", summary="Update a negotiation")
async def update_upcast_negotiation(
    current_user: User = Depends(get_current_user),
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
        update_result = await negotiations_collection.update_one({"_id":ObjectId(body.id)},
            {"$set": pydantic_to_dict(body),
                "updated_at": datetime.utcnow()}
        )

        if update_result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Negotiation not found or you do not have permission to update this negotiation")

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
    current_user: User = Depends(get_current_user)
):
    try:
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Delete the negotiation
        delete_result = await negotiations_collection.delete_one(
            {"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": ObjectId(current_user.id)}, {"provider_id": ObjectId(current_user.id)}, {"user_id": ObjectId(current_user.id)}]}
        )

        if delete_result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Negotiation not found or you do not have permission to delete this negotiation")

        # Delete corresponding requests
        await policy_collection.delete_many({"negotiation_id": ObjectId(negotiation_id)})

        # Delete corresponding offers
        await policy_collection.delete_many({"negotiation_id": ObjectId(negotiation_id)})

        return {"message": "Negotiation and corresponding requests and offers deleted successfully", "negotiation_id": negotiation_id}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception. {str(e)}. Traceback: {error_message}")


# New endpoint
@router.get("/negotiation/{negotiation_id}/last-policy", summary="Get the last policy", response_model=UpcastPolicyObject)
async def get_last_policy(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(get_current_user)
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

        request = await policy_collection.find_one({"_id": ObjectId(negotiations_list[-1])})
        last_policy = negotiations_list[-1]
        return pydantic_to_dict(request,True)
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")



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


# Endpoint to get the last policy and the changes between the last two policies
@router.get("/negotiation/{negotiation_id}/last-policy-diff", summary="Get the last policy", response_model=PolicyDiffResponse)
async def get_last_policy(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(get_current_user)
):
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
        last_policy = await policy_collection.find_one({"_id": ObjectId(last_policy_id)})


        if len(negotiations_list) < 2:
            second_last_policy = {}
        else:
            second_last_policy_id = negotiations_list[-2]
            second_last_policy = await policy_collection.find_one({"_id": ObjectId(second_last_policy_id)})

        if not last_policy:
            raise HTTPException(status_code=404, detail="Last policy not found")

        last_policy_dict = pydantic_to_dict(last_policy, True)

        second_last_policy_dict = pydantic_to_dict(second_last_policy, True) if second_last_policy else {}

        # Calculate the changes between the last two policies
        changes = find_changes(second_last_policy_dict, last_policy_dict)

        try:
            response = PolicyDiffResponse(
                last_policy=last_policy_dict,
                changes=PolicyDiffObject(**changes)
            )
        except ValidationError as e:
            print("Response validation failed:", e.json(indent=2))
            raise

        return response
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")

@router.get("/consumer/request/{request_id}", summary="Get an existing request", response_model=UpcastPolicyObject)
async def get_upcast_request(
    current_user: User = Depends(get_current_user),
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
        current_user: User = Depends(get_current_user)
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
    
@router.post("/consumer/request/new", summary="Create a new request")
async def create_new_upcast_request(
        current_user: User = Depends(get_current_user),
        previous_policy_id: Optional[str] = Header(None, description="The ID of the previous offer"),
        body: UpcastPolicyObject = Body(..., description="The request object")
):
    try:
        if body.negotiation_id:
            cloned_policy_id = None
            existing_negotiation = await negotiations_collection.find_one({"_id": ObjectId( body.negotiation_id)})
            print(f"Existing negotiation: {existing_negotiation}")

        if not body.negotiation_id:
            # Clone the policy with id = previous_policy_id
            previous_policy = await policy_collection.find_one({"_id": ObjectId(previous_policy_id)})
            print(f"Previous policy: {previous_policy}")
            if not previous_policy:
                raise HTTPException(status_code=404, detail="Previous policy not found")

            # Remove the _id field from the cloned policy
            previous_policy.pop("_id")

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

        if not body.negotiation_id:  # If negotiation_id is empty, create a new negotiation

            negotiation = UpcastNegotiationObject(
                user_id=ObjectId(current_user.id),
                title=body.title,
                consumer_id=ObjectId(body.consumer_id),
                provider_id=ObjectId(body.provider_id),  # Assuming provider_id is available in the request object
                negotiation_status=NegotiationStatus.REQUESTED,
                resource_description=body.resource_description_object.dict(),
                dpw=body.data_processing_workflow_object,
                nlp=body.natural_language_document,
                conflict_status="",  # Initialize with an empty string
                negotiations=[ObjectId(cloned_policy_id), ObjectId(request_id)], # Add the request to negotiations list
                original_offer_id=ObjectId(cloned_policy_id),
                created_at=now,
                updated_at=now
            )
            
            print(f"New negotiation object: {negotiation}")

            result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
            print(f"Inserted negotiation ID: {result.inserted_id}")
            negotiation_id = result.inserted_id

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
        else:
            # Update existing negotiation by appending the offer and cloned policy (if any) to negotiations list
            updates = {
                "$set": {"negotiation_status": NegotiationStatus.REQUESTED,
                "updated_at": datetime.utcnow()},
                "$push": {"negotiations": {"$each": [ObjectId(request_id)]}}
            }
            if cloned_policy_id:
                updates["$push"]["negotiations"]["$each"].append(ObjectId(cloned_policy_id))

            await negotiations_collection.update_one(
                {"_id": ObjectId(str(body.negotiation_id))},
                updates
            )
            negotiation_id = body.negotiation_id

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
        message = {"message": "Request sent successfully", "request_id": request_id, "negotiation_id": str(negotiation_id)}
        await push_messages("create", message)
        return message
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
#        raise HTTPException(status_code=500,
#                            detail=f"Exception: {str(e)}. Traceback: {error_message}")
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}.")



@router.put("/consumer/request/{request_id}", summary="Update an existing request")
async def update_upcast_request(
        request_id: str,
        body: UpcastPolicyObject = Body(..., description="The request object"),
        current_user: User = Depends(get_current_user)
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
#         current_user: User = Depends(get_current_user)
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
    current_user: User = Depends(get_current_user)
):
    try:
        
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
                title = body.title,
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
        current_user: User = Depends(get_current_user)
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
#         current_user: User = Depends(get_current_user)
# ):
#     offers = await policy_collection.find({"provider_id": {"$exists": True}}).to_list(length=None)
#
#     if not offers:
#         raise HTTPException(status_code=404, detail="No offers found")
#
#     return [UpcastPolicyObject(**pydantic_to_dict(offer, True)) for offer in offers]

@router.get("/consumer/offer", summary="Get available offers", response_model=List[UpcastPolicyObject])
async def get_upcast_offers(
        current_user: User = Depends(get_current_user)
):
    offers = await policy_collection.find({
        'type':'offer',
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
        current_user: User = Depends(get_current_user),
        body: UpcastPolicyObject = Body(..., description="The offer object")
):
    try:
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

        message = {"message": "Offer created successfully", "offer_id": offer_id, "negotiation_id": str(body.negotiation_id)}
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

        return {"message": "Offer created successfully", "offer_id": offer_id, "negotiation_id": str(body.negotiation_id)}

    except BaseException as e:
        error_message = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.post("/provider/offer/initial_dataset", summary="Create a new initial offer from a dataset", response_model=UpcastPolicyObject)
async def create_initial_upcast_offer_from_dataset(
        current_user: User = Depends(get_current_user),
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
                raise HTTPException(status_code=400, detail="UPCAST object could not be parsed")
    try:
        try:
            upcast_policy["resource_description_object"].pop("raw_object")
        except:
            pass
        if negotiation_provider_user_id is None:
            negotiation_provider_user_id = current_user.id

        upo = UpcastPolicyObject.parse_obj(upcast_policy)
        # If necessary, make changes on Upcast policy object

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

        # Retrieve the offer from the database using the converted ObjectId
        offer = await policy_collection.find_one({"_id": offer_id})

        # Check if the offer exists
        if offer is None:
            raise HTTPException(status_code=404, detail="Offer not found")

        return UpcastPolicyObject(**pydantic_to_dict(offer, True))

    except BaseException as e:
        error_message = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.post("/provider/offer/initial_upcast_dataset", summary="Create a new initial offer from an upcast dataset", response_model=UpcastPolicyObject)
async def create_initial_upcast_offer_from_dataset(
        current_user: User = Depends(get_current_user),
        body: Dict[str, Any] = Body(..., description="The dataset object"),
        ):
    current_user_id = current_user.id
    #await push_messages("create", body)
    #await push_messages("update", body)
    odrl_policy = {}
    negotiation_provider_user_id = None
    try:
        if type(body) is dict:
            upcast_object_graph = Graph().parse(data=body, format="json-ld")
            upcast_object = body
        elif type(body) is str:
            upcast_object = json.loads(body.replace("'", '"'))
            upcast_object_graph = Graph().parse(data=upcast_object, format="json-ld")


        pc = UpcastPolicyConverter(upcast_object_graph, upcast_object)

        upcast_policy = pc.convert_to_policy()

    except BaseException as b:
        raise HTTPException(status_code=400, detail="UPCAST object could not be parsed")
    try:
        try:
            upcast_policy["resource_description_object"].pop("raw_object")
        except:
            pass

        upo = UpcastPolicyObject.parse_obj(upcast_policy)

        # If necessary, make changes on Upcast policy object
        upo.consumer_id = ObjectId(current_user_id)
        now = datetime.utcnow()
        upo.created_at = now
        upo.updated_at = now
        # Insert the cloned policy into the policy collection
        result = await policy_collection.insert_one(pydantic_to_dict(upo))
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

        # Retrieve the offer from the database using the converted ObjectId
        offer = await policy_collection.find_one({"_id": offer_id})

        # Check if the offer exists
        if offer is None:
            raise HTTPException(status_code=404, detail="Offer not found")

        return UpcastPolicyObject(**pydantic_to_dict(offer, True))

    except BaseException as e:
        error_message = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Exception: {str(e)}. Traceback: {error_message}")

@router.get("/users_list", summary="Get all users list")
async def get_all_users(current_user: User = Depends(get_current_user)):

        users = await users_collection.find().to_list(length=None)
        for user in users:
            user["id"] = str(user.pop("_id"))
            user.pop("password")# Convert _id to id and stringify
        users = [user for user in users if not user.get("is_admin", False)]
        return JSONResponse(content=users)

@router.get("/provider/offer/{offer_id}", summary="Get an existing offer", response_model=UpcastPolicyObject)
async def get_upcast_offer(
        offer_id: str = Path(..., description="The ID of the offer"),
        current_user: User = Depends(get_current_user)
):
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

    return UpcastPolicyObject(**pydantic_to_dict(offer, True))

@router.delete("/offer/{offer_id}", summary="Delete an offer")
async def delete_upcast_offer(
        offer_id: str = Path(..., description="The ID of the offer"),
        current_user: User = Depends(get_current_user)
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

        return {"message": "Offer deleted successfully", "offer_id": offer_object_id, "negotiation_id": str(offer["negotiation_id"])}
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

@router.get("/contract/{negotiation_id}", summary="Get a contract", response_model=Union[dict, UpcastContractObject])
async def get_upcast_contract(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(get_current_user)
):
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

        request = await policy_collection.find_one({"_id": ObjectId(negotiations_list[-1])})
        
        last_policy = negotiations_list[-1]
        return UpcastContractObject(**pydantic_to_dict(request, True))
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


#
# @router.post("/contract/sign", summary="Sign a contract (Under Construction)")
# async def sign_upcast_contract(
#     current_user: User = Depends(get_current_user),
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
        current_user: User = Depends(get_current_user)
):
    # negotiation_id = await get_negotiation_id(offer_id, negotiation_id)
    try:
        update_result = await negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$set": {"negotiation_status": NegotiationStatus.ACCEPTED.value,
                "updated_at": datetime.utcnow()}}
        )
        message = {"message" : "Offer accepted successfully", "negotiation_id" : negotiation_id, "negotiation_status" : NegotiationStatus.ACCEPTED.value}
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
        current_user: User = Depends(get_current_user)
):
    # negotiation_id = await get_negotiation_id(offer_id, negotiation_id)
    try:
        update_result = await negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$set": {"negotiation_status": NegotiationStatus.VERIFIED.value,
                "updated_at": datetime.utcnow()}}
        )
        message = {"message" : "Offer verified successfully", "negotiation_id" : negotiation_id, "negotiation_status" : NegotiationStatus.VERIFIED.value}
        await push_messages("update", message)
        return message
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")
@router.post("/negotiation/provider/agree/{negotiation_id}", summary = "Agree on a request")
async def agree_upcast_offer(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(get_current_user)
):
    # negotiation_id = await get_negotiation_id(request_id, negotiation_id)
    try:
        update_result = await negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$set": {"negotiation_status": NegotiationStatus.AGREED.value,
                "updated_at": datetime.utcnow()}}
        )
        message = {"message": "Request agreed successfully", "negotiation_id": str(negotiation_id), "negotiation_status" : NegotiationStatus.AGREED.value}
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
        current_user: User = Depends(get_current_user)
):
    # negotiation_id = await get_negotiation_id(offer_id, negotiation_id)
    try:
        update_result = await negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$set": {"negotiation_status": NegotiationStatus.FINALIZED.value,
                "updated_at": datetime.utcnow()}}
        )
        message = {"message": "Offer finalized successfully", "negotiation_id": str(negotiation_id), "negotiation_status" : NegotiationStatus.FINALIZED.value}
        await push_messages("update", message)
        return message
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")

@router.post("/negotiation/terminate/{negotiation_id}", summary="Terminate a negotiation")
async def terminate_upcast_negotiation(
    negotiation_id: str = Path(..., description="The ID of the negotiation"),
    current_user: User = Depends(get_current_user)
):
    try:
        update_result = await negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$set": {"negotiation_status": NegotiationStatus.TERMINATED.value,
                "updated_at": datetime.utcnow()}}
        )

        if update_result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Negotiation not found or you do not have permission to terminate this negotiation")
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
        print(f'negotiations list {negotiations_list}')
        
        negotiations_list_no_duplicates = list(dict.fromkeys(negotiations_list))
        print(f'negotiations list no duplicates {negotiations_list_no_duplicates}')
        
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

        #if preferences isn't already a list, make preferences into a list of one
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
        
        return {"message": "agent created successfully", "agent_id": str(inserted_id), "recommender_agent_record": recommender_agent_record}

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
@router.get("/agent/latest/{negotiation_id}", summary="Get latest recommender agent record for a specified user ID and negotiation ID")
async def get_latest_recommender_agent_record(
        user_id: str = Header(..., description="The ID of the user"),
        negotiation_id: str = Path(..., description="The ID of the negotiation")
):
    try:
        agent_record = await agent_records_collection.find_one({"user_id": user_id,
                                                             "negotiation_id": negotiation_id},
                                                             sort=[("created_at", -1)] # Sort descending by creation time
                                                             )
        if not agent_record:
            raise HTTPException(status_code=404, detail="No agent records found for this user in this negotiation")

        return RecommenderAgentRecord(**pydantic_to_dict(agent_record))
    
    except BaseException as e:
        error_message = traceback.format_exc()




async def push_messages(action, message):
    start = time.perf_counter()
    await push_provider_dashboard_message(action, message)
    logging.debug(f"push_provider_dashboard_message took {time.perf_counter() - start:.3f} seconds")

    start = time.perf_counter()
    await push_consumer_dashboard_message(action, message)
    logging.debug(f"push_consumer_dashboard_message took {time.perf_counter() - start:.3f} seconds")

    start = time.perf_counter()
    await push_kafka_message(action, message)
    logging.debug(f"push_kafka_message took {time.perf_counter() - start:.3f} seconds")

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
            #producer.flush()  # Ensure all messages are delivered before exiting
            await asyncio.to_thread(producer.flush)
            logging.debug(f"Successful push to kafka. action:{action}")

    except BaseException as b:
        print(b)
        logging.error("Failed to push Kafka message", exc_info=True)


def convert_all(obj):
    if isinstance(obj, dict):
        return {k: convert_all(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_all(i) for i in obj]
    elif isinstance(obj, (ObjectId, datetime)):
        return str(obj)
    return obj

async def push_consumer_dashboard_message(action,object):
    try:
        if push_consumer_enabled:
            username = os.getenv("CONSUMER_DASHBOARD_USERNAME")
            password = os.getenv("CONSUMER_DASHBOARD_PASSWORD")
            username_encoded = urllib.parse.quote(username)
            password_encoded = urllib.parse.quote(password)
            url = "https://sso.ict-abovo.gr/realms/goodflows/protocol/openid-connect/token"

            payload = f'grant_type=password&client_id=goodflows-api&username={username_encoded}&password={password_encoded}&client_secret=imPnW4YevqTWmUBx6NSCC2v4kad7Xphp'
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'cache-control': 'no-cache'
            }

            response = requests.request("POST", url, headers=headers, data=payload)
            access_token = json.loads(response.content.decode("UTF-8"))["access_token"]

            url = "https://upcast-api.ict-abovo.gr/negotiation"

            negotiation = await negotiations_collection.find_one({"_id": ObjectId(object["negotiation_id"])})
            if negotiation:
#                clean_obj = convert_all(negotiation)
#                payload = json.dumps(negotiation, indent=2)
                neg_object = pydantic_to_dict(negotiation, True)
                payload = json.dumps(neg_object, default=str)
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f"Bearer {access_token}"
                }

                response = requests.put(url, headers=headers, data=payload)
                if response.status_code == 200:
                    logging.debug(
                        f"Successful push to consumer dashboard. Status: {response.status_code}, Response: {response.text}")
                else:
                    logging.error(
                        f"Error consumer push. Status: {response.status_code}, Response: {response.text}, payload:{payload}, headers: {headers} ")

            #     return True
            # else:
            #     return False
        # else:
        #     return False
    except BaseException as b:
        print(b)
        logging.error("Failed to push message to consumer dashboard", exc_info=True)


async def push_provider_dashboard_message(action, object):
    try:
        if push_provider_enabled:
            username = os.getenv("PROVIDER_DASHBOARD_USERNAME")
            password = os.getenv("PROVIDER_DASHBOARD_PASSWORD")

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

                        # Debug the resource description
                        if "resource_description" in neg_object and "uri" in neg_object["resource_description"]:
                            uri = neg_object["resource_description"]["uri"]
                            logging.debug(f"URI extracted: {uri}")
                        else:
                            logging.error(
                                f"Missing resource_description.uri in negotiation object: {neg_object.keys()}")
                            return

                        url = "https://dev.upcast.maggioli-research.gr/upcast-service/api/negotiationplugin/create"
                        payload = {
                            "negotiationId": negotiation_id,
                            "url": uri
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
                            logging.error(f"Error pushing to provider dashboard. Status: {st}, Response: {resp}")
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
        # Check if the token is blacklisted
        if await is_token_blacklisted(token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Decode and validate the token
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            email: str = payload.get("sub")
            exp: int = payload.get("exp")

            if email is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token: missing subject",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Fetch the user from the database
        user = await users_collection.find_one({"username_email": email})
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Convert ObjectId to string and remove password for security
        user_response = {
            "id": str(user["_id"]),
            "username_email": user["username_email"],
            "type": user.get("type"),
            "is_admin": user.get("is_admin", False)
        }

        # Calculate token expiration time
        expiration_time = datetime.fromtimestamp(exp, tz=timezone.utc)

        return {
            "valid": True,
            "user": user_response,
            "expires_at": expiration_time.isoformat(),
            "message": "Token is valid"
        }

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        error_message = traceback.format_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to verify token: {str(e)}. Traceback: {error_message}"
        )


@router.get("/user/verify-token/")
async def verify_token_get(current_user: User = Depends(get_current_user)):
    """
    Verify the token from Authorization header (GET method).

    This endpoint uses the existing authentication dependency to verify
    the token from the Authorization header.

    Returns:
        dict: User information and token validity status
    """
    try:
        user_response = {
            "id": str(current_user.id),
            "username_email": current_user.username_email,
            "type": current_user.type,
            "is_admin": getattr(current_user, 'is_admin', False)
        }

        return {
            "valid": True,
            "user": user_response,
            "message": "Token is valid"
        }

    except Exception as e:
        error_message = traceback.format_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to verify token: {str(e)}. Traceback: {error_message}"
        )
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
