import json
import os
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
from pydantic import BaseModel
from pydantic import Field, EmailStr
from pydantic import field_validator
from rdflib import Graph
from starlette.responses import JSONResponse

from PolicyConverter import UpcastPolicyConverter
from data_model import User, UpcastNegotiationObject, UpcastPolicyObject, UpcastResourceDescriptionObject, \
    PolicyDiffObject, UpcastContractObject, PolicyChange, PolicyDiffResponse, UpcastPolicyConverter, PolicyType, \
    PartyType, NegotiationStatus, pydantic_to_dict
from recommender.agent import Proposal, RecommenderAgentRecord
from recommender.agent import new_offer, new_request

# Load environment variables from .env file
root_path="/negotiation-api"
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
           "http://62.171.168.208:8002"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables from .env file
load_dotenv()

# Define Kafka broker configuration
#kafka_conf = {'bootstrap.servers': os.getenv("KAFKA_BOOTSTRAP_SERVERS")}

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
    producer = None  # Ensure the producer is not used further

MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = os.getenv("MONGO_PORT")
if MONGO_PORT: # Assumption: A local or remote installation of MongoDB is provided.
    MONGO_PORT = int(MONGO_PORT)
    MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}"
else: # Assumption: The database is stored in mongodb cloud.
    MONGO_URI = f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}/?retryWrites=true&w=majority&appName=Cluster0"

client = AsyncIOMotorClient(MONGO_URI)
db = client.upcast
negotiations_collection = db.negotiations
requests_collection = db.requests
offers_collection = db.offers
policy_collection = db.policies
contracts_collection = db.contracts
users_collection = db.users

SECRET_KEY = os.getenv("SECRET_KEY", "fallback_key")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

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

@router.post("/producer/recommend", summary="Recommend a request", response_model=Proposal)
def producer_recommend(
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

        # Retrieve consumer and producer objects from users_collection
        consumer = await users_collection.find_one({"_id": ObjectId(body.consumer_id)})
        producer = await users_collection.find_one({"_id": ObjectId(body.producer_id)})

        if consumer is None or producer is None:
            raise HTTPException(status_code=404, detail="Consumer or producer not found")

        body.type = PolicyType.REQUEST
        # Save the offer to MongoDB
        result = await policy_collection.insert_one(pydantic_to_dict(body))
        # Retrieve the generated _id
        request_id = str(result.inserted_id)

        body.consumer_id = ObjectId(str(body.consumer_id))
        body.producer_id = ObjectId(str(body.producer_id))

        negotiation = UpcastNegotiationObject(
            user_id=ObjectId(current_user.id),
            consumer_id=ObjectId(consumer["_id"]),
            producer_id=ObjectId(producer["_id"]),
            negotiation_status=NegotiationStatus.REQUESTED,
            resource_description=body.resource_description_object.dict(),
            dpw=body.data_processing_workflow_object,
            nlp=body.natural_language_document,
            conflict_status=conflict_status,
            negotiations=[request_id],
            original_offer_id=request_id
        )

        result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
        if result.inserted_id:

            # Update the request object and cloned policy (if any) with the existing negotiation_id
            await policy_collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": {"negotiation_id": result.inserted_id}}
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

    # Retrieve negotiations where the user is either a consumer or a producer
    #negotiations = await negotiations_collection.find(
    #    {"$or": [{"consumer_id": ObjectId(current_user.id)}, {"producer_id": ObjectId(current_user.id)}, {"user_id": ObjectId(current_user.id)}]}
    #).to_list(length=None)
    negotiations = await negotiations_collection.find(
        {"$or": [{"consumer_id": ObjectId(current_user.id)}, {"producer_id": ObjectId(current_user.id)}, {"user_id": ObjectId(current_user.id)}]}
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
    try:
        update_result = await negotiations_collection.update_one({"_id":ObjectId(body.id)},
            {"$set": pydantic_to_dict(body)}
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
            {"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": ObjectId(current_user.id)}, {"producer_id": ObjectId(current_user.id)}, {"user_id": ObjectId(current_user.id)}]}
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
#        negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": ObjectId(current_user.id)}, {"producer_id": ObjectId(current_user.id)}, {"user_id": ObjectId(current_user.id)}]})
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
#        negotiation = await negotiations_collection.find_one(
#            {"_id": ObjectId(negotiation_id),
#             "$or": [{"consumer_id": ObjectId(current_user.id)}, {"producer_id": ObjectId(current_user.id)},
#                     {"user_id": ObjectId(current_user.id)}]}
#        )
        negotiation = await negotiations_collection.find_one(
            {"_id": ObjectId(negotiation_id)}
        )

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

        result = {
            "last_policy": last_policy_dict,
            "changes": changes
        }

        return result
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")

@router.get("/consumer/request/{request_id}", summary="Get an existing request", response_model=UpcastPolicyObject)
async def get_upcast_request(
    current_user: User = Depends(get_current_user),
    request_id: str = Path(..., description="The ID of the request")
):
    request = await policy_collection.find_one({"_id": ObjectId(request_id)})
    if request:
        return UpcastPolicyObject(**pydantic_to_dict(request, True))
    else:
        raise HTTPException(status_code=404, detail="Request not found")

@router.post("/consumer/request/new", summary="Create a new request")
async def create_new_upcast_request(
        current_user: User = Depends(get_current_user),
        previous_policy_id: Optional[str] = Header(None, description="The ID of the previous offer"),
        body: UpcastPolicyObject = Body(..., description="The request object")
):
    try:
        cloned_policy_id = None

        if not body.negotiation_id:
            # Clone the policy with id = previous_policy_id
            previous_policy = await policy_collection.find_one({"_id": ObjectId(previous_policy_id)})
            if not previous_policy:
                raise HTTPException(status_code=404, detail="Previous policy not found")

            # Remove the _id field from the cloned policy
            previous_policy.pop("_id")

            # Create a new policy object from the cloned policy
            cloned_policy = UpcastPolicyObject(**previous_policy)
            cloned_policy.type = PolicyType.REQUEST  # Change the policy type to "offer"

            # Insert the cloned policy into the policy collection
            result = await policy_collection.insert_one(pydantic_to_dict(cloned_policy))
            cloned_policy_id = str(result.inserted_id)

        # Change the policy type of the original body to "offer"
        body.type = PolicyType.REQUEST

        # Save the offer to MongoDB
        result = await policy_collection.insert_one(pydantic_to_dict(body))

        # Retrieve the generated _id
        request_id = str(result.inserted_id)

        if not body.negotiation_id:  # If negotiation_id is empty, create a new negotiation

            negotiation = UpcastNegotiationObject(
                user_id=ObjectId(current_user.id),
                title=body.title,
                consumer_id=ObjectId(body.consumer_id),
                producer_id=ObjectId(body.producer_id),  # Assuming producer_id is available in the request object
                negotiation_status=NegotiationStatus.REQUESTED,
                resource_description=body.resource_description_object.dict(),
                dpw=body.data_processing_workflow_object,
                nlp=body.natural_language_document,
                conflict_status="",  # Initialize with an empty string
                negotiations=[ObjectId(cloned_policy_id), ObjectId(request_id)], # Add the request to negotiations list
                original_offer_id=ObjectId(cloned_policy_id)
            )

            result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
            negotiation_id = result.inserted_id

            # Update the request object and cloned policy (if any) with the new negotiation_id
            await policy_collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": {"negotiation_id": negotiation_id}}
            )
            if cloned_policy_id:
                await policy_collection.update_one(
                    {"_id": ObjectId(cloned_policy_id)},
                    {"$set": {"negotiation_id": negotiation_id}}
                )
        else:
            # Update existing negotiation by appending the offer and cloned policy (if any) to negotiations list
            updates = {
                "$set": {"negotiation_status": NegotiationStatus.REQUESTED},
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
                {"$set": {"negotiation_id": negotiation_id}}
            )
            if cloned_policy_id:
                await policy_collection.update_one(
                    {"_id": ObjectId(cloned_policy_id)},
                    {"$set": {"negotiation_id": negotiation_id}}
                )
        message = {"message": "Request sent successfully", "request_id": request_id, "negotiation_id": str(negotiation_id)}
        await push_messages("create", message)
        return message
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.put("/consumer/request", summary="Update an existing request")
async def update_upcast_request(
    current_user: User = Depends(get_current_user),
    body: UpcastPolicyObject = Body(..., description="The request object")
):
    try:
        # Change the policy type to "offer"
        body.type = PolicyType.OFFER
        body.producer_id = current_user.id
        # Save the offer to MongoDB
        result = await policy_collection.insert_one(pydantic_to_dict(body))

        # Retrieve the generated _id
        request_id = str(result.inserted_id)

        body.type = PolicyType.REQUEST
        if not body.negotiation_id:  # If negotiation_id is empty, create a new negotiation
            negotiation = UpcastNegotiationObject(
                user_id=ObjectId(current_user.id),
                title = body.title,
                consumer_id=ObjectId(body.consumer_id),
                producer_id=ObjectId(body.producer_id),  # Assuming producer_id is available in the request object
                negotiation_status=NegotiationStatus.REQUESTED,
                resource_description=body.resource_description_object.dict(),
                dpw=body.data_processing_workflow_object,
                nlp=body.natural_language_document,
                conflict_status="",  # Initialize with an empty string
                negotiations=[ObjectId(request_id)]  # Add the request to negotiations list
            )
            result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
            negotiation_id = result.inserted_id

            # Update the request object with the new negotiation_id
            await policy_collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": {"negotiation_id": negotiation_id}}
            )
        else:

            if body.negotiation_id:
                # Update existing negotiation by appending the offer to negotiations list
                await negotiations_collection.update_one(
                    {"_id": ObjectId(str(body.negotiation_id))},
                    {
                        "$set": {"negotiation_status": NegotiationStatus.REQUESTED},
                        "$push": {"negotiations": ObjectId(request_id)}
                    }
                )
                negotiation_id = body.negotiation_id

                # Update the offer object with the existing negotiation_id
                await policy_collection.update_one(
                    {"_id": ObjectId(request_id)},
                    {"$set": {"negotiation_id": negotiation_id}}
                )
            negotiation_id = body.negotiation_id
        return {"message": "Request sent successfully", "request_id": request_id, "negotiation_id": str(negotiation_id)}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")

@router.put("/producer/offer", summary="Update an existing offer")
async def update_upcast_offer(
    current_user: User = Depends(get_current_user),
    body: UpcastPolicyObject = Body(..., description="The offer object")
):
    try:
        # Change the policy type to "offer"
        body.type = PolicyType.REQUEST
        body.consumer_id = current_user.id

        plc = pydantic_to_dict(body)
        plc.pop("id")
        # Save the offer to MongoDB


        body.type = PolicyType.REQUEST
        if not body.negotiation_id:
            result = await policy_collection.insert_one(pydantic_to_dict(body))
            # Retrieve the generated _id
            request_id = str(result.inserted_id)
            negotiation = UpcastNegotiationObject(
                user_id=ObjectId(current_user.id),
                title = body.title,
                consumer_id=ObjectId(body.consumer_id),
                producer_id=ObjectId(body.producer_id),  # Assuming producer_id is available in the request object
                negotiation_status=NegotiationStatus.DRAFT,
                resource_description=body.resource_description_object.dict(),
                dpw=body.data_processing_workflow_object,
                nlp=body.natural_language_document,
                conflict_status="",  # Initialize with an empty string
                negotiations=[ObjectId(request_id)]  # Add the request to negotiations list
            )
            result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
            negotiation_id = result.inserted_id

            # Update the request object with the new negotiation_id
            await policy_collection.update_one(
                {"_id": ObjectId(request_id)},
                {"$set": {"negotiation_id": negotiation_id}}
            )
        else:
            if body.negotiation_id:
                result = await policy_collection.update_one({"_id": ObjectId(body.id)}, {"$set": plc})
                # Retrieve the generated _id
                request_id = str(body.id)


                # Update existing negotiation by appending the offer to negotiations list
                # await negotiations_collection.update_one(
                #     {"_id": ObjectId(str(body.negotiation_id))},
                #     {
                #         "$set": {"negotiation_status": NegotiationStatus.OFFERED},
                #         "$push": {"negotiations": ObjectId(request_id)}
                #     }
                # )
                # negotiation_id = body.negotiation_id
                #
                # # Update the offer object with the existing negotiation_id
                # await policy_collection.update_one(
                #     {"_id": ObjectId(request_id)},
                #     {"$set": {"negotiation_id": negotiation_id}}
                # )
                pass

            negotiation_id = body.negotiation_id
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
    # Find the request
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


@router.post("/producer/offer/new", summary="Create a new offer")
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
        body_dict["type"] = PolicyType.OFFER

        # Insert into MongoDB
        result = await policy_collection.insert_one(body_dict)

        offer_id = body.id if body.id else str(result.inserted_id)

        # Handle negotiation if applicable
        if body.negotiation_id:
            await negotiations_collection.update_one(
                {"_id": ObjectId(str(body.negotiation_id))},
                {
                    "$set": {"negotiation_status": NegotiationStatus.OFFERED},
                    "$push": {"negotiations": offer_id}
                }
            )
            await policy_collection.update_one(
                {"_id": offer_id},
                {"$set": {"negotiation_id": body.negotiation_id}}
            )

        return {"message": "Offer created successfully", "offer_id": offer_id, "negotiation_id": str(body.negotiation_id)}

    except BaseException as e:
        error_message = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Exception: {str(e)}. Traceback: {error_message}")

@app.post("/producer/offer/initial", summary="Create a new initial offer")
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
        body_dict["type"] = PolicyType.OFFER

        # Insert into MongoDB
        result = await policy_collection.insert_one(body_dict)

        offer_id = body.id if body.id else str(result.inserted_id)

        # Handle negotiation if applicable
        if body.negotiation_id:
            await negotiations_collection.update_one(
                {"_id": ObjectId(str(body.negotiation_id))},
                {
                    "$set": {"negotiation_status": NegotiationStatus.OFFERED},
                    "$push": {"negotiations": offer_id}
                }
            )
            await policy_collection.update_one(
                {"_id": offer_id},
                {"$set": {"negotiation_id": body.negotiation_id}}
            )

        return {"message": "Offer created successfully", "offer_id": offer_id, "negotiation_id": str(body.negotiation_id)}

    except BaseException as e:
        error_message = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Exception: {str(e)}. Traceback: {error_message}")


@router.post("/producer/offer/initial_dataset", summary="Create a new initial offer from a dataset", response_model=UpcastPolicyObject)
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
        # Insert the cloned policy into the policy collection
        result = await policy_collection.insert_one(pydantic_to_dict(upo))
        offer_id = result.inserted_id


        negotiation = UpcastNegotiationObject(
            user_id=ObjectId(current_user.id),
            title=upo.title,
            consumer_id=current_user.id,
            producer_id=upo.producer_id,  # Assuming producer_id is available in the request object
            negotiation_status=NegotiationStatus.REQUESTED,
            resource_description=upo.resource_description_object.dict(),
            dpw=upo.data_processing_workflow_object,
            nlp=upo.natural_language_document,
            conflict_status="",  # Initialize with an empty string
            negotiations=[offer_id],  # Add the request to negotiations list
            original_offer_id=offer_id
        )

        result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
        negotiation_id = result.inserted_id

        # Update the request object and cloned policy (if any) with the new negotiation_id
        await policy_collection.update_one(
            {"_id": ObjectId(offer_id)},
            {"$set": {"negotiation_id": negotiation_id}}
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


@router.post("/producer/offer/initial_upcast_dataset", summary="Create a new initial offer from an upcast dataset", response_model=UpcastPolicyObject)
async def create_initial_upcast_offer_from_dataset(
        current_user: User = Depends(get_current_user),
        body: Dict[str, Any] = Body(..., description="The dataset object"),
        ):
    current_user_id = None
#    current_user_id = current_user.id

    negotiation_provider_user_id = None
    try:
        if type(body) is dict:
            upcast_object_graph = Graph().parse(data=body, format="json-ld")
        elif type(body) is str:
            upcast_object = json.loads(body.replace("'", '"'))
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

        upo = UpcastPolicyObject.parse_obj(upcast_policy)

        # If necessary, make changes on Upcast policy object
        upo.consumer_id = ObjectId(current_user_id)
        # Insert the cloned policy into the policy collection
        result = await policy_collection.insert_one(pydantic_to_dict(upo))
        offer_id = result.inserted_id

        negotiation = UpcastNegotiationObject(
            user_id=ObjectId(current_user_id),
            title=upo.title,
            consumer_id=ObjectId(current_user_id),
            producer_id=ObjectId(upo.producer_id),  # Assuming producer_id is available in the request object
            negotiation_status=NegotiationStatus.REQUESTED,
            resource_description=upo.resource_description_object.dict(),
            dpw=upo.data_processing_workflow_object,
            nlp=upo.natural_language_document,
            conflict_status="",  # Initialize with an empty string
            negotiations=[offer_id],  # Add the request to negotiations list
            original_offer_id=offer_id
        )

        result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
        negotiation_id = result.inserted_id

        # Update the request object and cloned policy (if any) with the new negotiation_id
        await policy_collection.update_one(
            {"_id": ObjectId(offer_id)},
            {"$set": {"negotiation_id": negotiation_id}}
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


@router.get("/producer/offer/{offer_id}", summary="Get an existing offer", response_model=UpcastPolicyObject)
async def get_upcast_offer(
        offer_id: str = Path(..., description="The ID of the offer"),
        current_user: User = Depends(get_current_user)
):
    # Convert offer_id to ObjectId
    offer_object_id = ObjectId(offer_id)

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

#
# @router.post("/producer/offer/finalize", summary="Accept an offer")
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
        #        negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": ObjectId(current_user.id)}, {"producer_id": ObjectId(current_user.id)}, {"user_id": ObjectId(current_user.id)}]})
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

@router.get("/users_list", summary="Get all users list")
async def get_all_users(current_user: User = Depends(get_current_user)):

        users = await users_collection.find().to_list(length=None)
        for user in users:
            user["id"] = str(user.pop("_id"))
            user.pop("password")# Convert _id to id and stringify
        users = [user for user in users if not user.get("is_admin", False)]
        return JSONResponse(content=users)

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
            {"$set": {"negotiation_status": NegotiationStatus.ACCEPTED.value}}
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
            {"$set": {"negotiation_status": NegotiationStatus.VERIFIED.value}}
        )
        message = {"message" : "Offer verified successfully", "negotiation_id" : negotiation_id, "negotiation_status" : NegotiationStatus.VERIFIED.value}
        await push_messages("update", message)
        return message
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")
@router.post("/negotiation/producer/agree/{negotiation_id}", summary = "Agree on a request")
async def agree_upcast_offer(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(get_current_user)
):
    # negotiation_id = await get_negotiation_id(request_id, negotiation_id)
    try:
        update_result = await negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$set": {"negotiation_status": NegotiationStatus.AGREED.value}}
        )
        message = {"message": "Request agreed successfully", "negotiation_id": str(negotiation_id), "negotiation_status" : NegotiationStatus.AGREED.value}
        await push_messages("update", message)
        return message
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")

@router.post("/negotiation/producer/finalize/{negotiation_id}", summary="Accept an offer")
async def finalize_upcast_offer(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        # offer_id: str = Path(..., description="The ID of the offer"),
        current_user: User = Depends(get_current_user)
):
    # negotiation_id = await get_negotiation_id(offer_id, negotiation_id)
    try:
        update_result = await negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$set": {"negotiation_status": NegotiationStatus.FINALIZED.value}}
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
            {"$set": {"negotiation_status": NegotiationStatus.TERMINATED.value}}
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

async def push_messages(action, message):
    await push_kafka_message(action,message)
    await push_consumer_dashboard_message(action, message)
    await push_provider_dashboard_message(action, message)

async def push_kafka_message(action, message):
    try:
        if kafka_enabled:
            if action == "create":
                action = action
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
            producer.flush()  # Ensure all messages are delivered before exiting
    except BaseException as b:
        print(b)
        pass

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
                neg_object = pydantic_to_dict(negotiation, True)

                payload = json.dumps(neg_object, default=str)
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f"Bearer {access_token}"
                }

                response = requests.request("PUT", url, headers=headers, data=payload)

            #     return True
            # else:
            #     return False
        # else:
        #     return False
    except BaseException as b:
        print(b)
        pass

async def push_provider_dashboard_message(action,object):
    try:
        if push_provider_enabled:
            username = os.getenv("PROVIDER_DASHBOARD_USERNAME")
            password = os.getenv("PROVIDER_DASHBOARD_PASSWORD")
            # Define the URL for Keycloak token endpoint
            url = "https://keycloak.maggioli-research.gr/auth/realms/upcast-dev/protocol/openid-connect/token"

            # Define the payload (form data)
            payload = {
                "client_id": "upcast-angular",
                "username": username,
                "password": password,
                "grant_type": "password"
            }

            # Define headers
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }

            # Send the POST request
            response = requests.post(url, data=payload, headers=headers)

            # Check if the request was successful
            if response.status_code == 200:
                data = response.json()
                access_token = data.get("access_token")
                print("Access Token:", access_token)
            else:
                print("Error:", response.status_code, response.text)


            negotiation_id = str(object["negotiation_id"])
            #
            access_token = os.getenv("PROVIDER_DASHBOARD_TOKEN")
            if action == "create":
                url = "https://dev.upcast.maggioli-research.gr/upcast-service/api/negotiationplugin/create"
                negotiation = await negotiations_collection.find_one({"_id": ObjectId(object["negotiation_id"])})
                if negotiation:
                    neg_object = pydantic_to_dict(negotiation, True)

                    payload = json.dumps({
                        "negotiationId": negotiation_id,
                        "url": neg_object["resource_description"]["uri"]
                    })
                    headers = {
                        'Content-Type': 'application/json',
                        'Authorization': f'Bearer {access_token}'
                    }

                    response = requests.request("POST", url, headers=headers, data=payload)
            else:

                url = f"https://dev.upcast.maggioli-research.gr/upcast-service/api/negotiationplugin/updatestatus/{negotiation_id}/{action}"

                payload = {}
                headers = {
                    'Authorization': f'Bearer {access_token}'
                }

                response = requests.request("POST", url, headers=headers, data=payload)

    except BaseException as b:
        print(b)
        pass

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
