import os
import traceback
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Dict, Optional, Any

import jwt
from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends
from fastapi import FastAPI
from fastapi import Header, Body
from fastapi import Path
from fastapi import status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from pydantic import BaseModel
from pydantic import Field, EmailStr
from pydantic import field_validator

# Load environment variables from .env file
load_dotenv()

app = FastAPI(
    title="Negotiation Plugin API",
    description="UPCAST Negotiation Plugin API",
    version="1.0",
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")  # Adjusted to match the login route

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


class MongoObject(BaseModel):
    id: Optional[object] = Field(None, alias="_id")
    @field_validator("id")
    def process_id(cls, value, values):
        if isinstance(value, ObjectId):
            return str(value)
        return value

class NegotiationStatus(str, Enum):
    AGREED = 'agreed'
    ACCEPTED = 'accepted'
    VERIFIED = 'verified'
    FINALIZED = 'finalized'
    TERMINATED = 'terminated'
    REQUESTED = 'requested'
    OFFERED = 'offered'
    DRAFT = 'draft'

class PolicyType(str, Enum):
    OFFER = 'offer'
    REQUEST = 'request'


class PartyType(str, Enum):
    CONSUMER = 'consumer'
    PRODUCER = 'producer'

class User(MongoObject):
    name: Optional[str] = None
    type: PartyType
    username_email: Optional[EmailStr] = None
    hashed_password: Optional[str] = Field(default=None)

class UpcastResourceDescriptionObject(BaseModel):
    title: Optional[str] = None
    price: float
    price_unit: Optional[str] = None
    uri: Optional[str] = None
    policy_url: Optional[str] = None
    environmental_cost_of_generation: Optional[Dict[str, str]] = None
    environmental_cost_of_serving: Optional[Dict[str, str]] = None
    description: Optional[str] = None
    type_of_data: Optional[str] = None
    data_format: Optional[str] = None
    data_size: Optional[str] = None
    geographic_scope: Optional[str] = None
    tags: Optional[str] = None
    publisher: Optional[str] = None
    theme: Optional[list] = None
    distribution: Optional[Dict[str, str]] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

class UpcastPolicyObject(MongoObject):
    title: Optional[str] = None
    type: str  # Assuming PolicyType is a string for this example
    consumer_id: Optional[object]
    producer_id: object
    data_processing_workflow_object: Dict
    natural_language_document: str
    resource_description_object: UpcastResourceDescriptionObject
    odrl_policy: Dict
    negotiation_id: Optional[object] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


class UpcastNegotiationObject(MongoObject):
    title: Optional[str] = None
    consumer_id: object
    producer_id: object
    negotiation_status: str  # Assuming NegotiationStatus is a string for this example
    resource_description: Dict
    dpw: Dict  # Data Process Workflow
    nlp: str  # Natural Language Part
    conflict_status: str  # Any detected conflict
    negotiations: List[object]  # List of UPCAST Request or UPCAST Offer
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    original_offer_id: Optional[object]=None
    class Config:
        use_enum_values = True  # Ensures the enum values are used instead of the enum type


class UpcastContractObject(MongoObject):
    title: Optional[str] = None
    corresponding_parties: Dict
    data_processing_workflow_object: Dict
    natural_language_document: str
    resource_description_object: UpcastResourceDescriptionObject
    metadata: Dict
    status: str
    negotiation_id: object
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

def pydantic_to_dict(obj, clean_id=False):
    if isinstance(obj, list):
        return [pydantic_to_dict(item,clean_id) for item in obj]
    if isinstance(obj, dict):
        return {k: pydantic_to_dict(v,clean_id) for k, v in obj.items()}
    if isinstance(obj, BaseModel):
        return pydantic_to_dict(obj.dict(),clean_id)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, ObjectId) and clean_id:
        return str(obj)
    return obj

# Load environment variables from .env file
load_dotenv()

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

SECRET_KEY = "YOUR_SECRET_KEY"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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

# User Registration
@router.post("/register", response_model=User)
async def register_user(user: User):
    if await users_collection.find_one({"email": user.username_email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    user.hashed_password = get_password_hash(user.hashed_password)
    user_dict = user.dict(by_alias=True, exclude_unset=True)
    result = await users_collection.insert_one(user_dict)
    user_dict["_id"] = result.inserted_id
    return user_dict

# User Login
@router.post("/login/")
async def login_user(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await users_collection.find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["email"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

# Dependency to Get Current User
async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except BaseException:
        raise credentials_exception

    user = await users_collection.find_one({"email": email})
    if user is None:
        raise credentials_exception
    return User(**user)

# Protected Route
@router.get("/protected-route/")
async def protected_route(current_user: User = Depends(get_current_user)):
    return {"message": f"Hello, {current_user.name}"}

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

        body.consumer_id = ObjectId(str(body.consumer_id))
        body.producer_id = ObjectId(str(body.producer_id))

        negotiation = UpcastNegotiationObject(
            consumer_id=ObjectId(consumer["_id"]),
            producer_id=ObjectId(producer["_id"]),
            negotiation_status=NegotiationStatus.REQUESTED,
            resource_description=body.resource_description_object.dict(),
            dpw=body.data_processing_workflow_object,
            nlp=body.natural_language_document,
            conflict_status=conflict_status,
            negotiations=[ObjectId(body.id)],
            original_offer_id=ObjectId(body.id)
        )

        result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
        if result.inserted_id:
            return {"negotiation_id": str(result.inserted_id)}
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


@router.get("/negotiation", summary="Get negotiations", response_model=List[UpcastNegotiationObject])
async def get_upcast_negotiations(
    current_user: User = Depends(get_current_user)
):


    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Retrieve negotiations where the user is either a consumer or a producer
    negotiations = await negotiations_collection.find(
        {"$or": [{"consumer_id": ObjectId(current_user.id)}, {"producer_id": ObjectId(current_user.id)}]}
    ).to_list(length=None)

    if not negotiations:
        return []
        # raise HTTPException(status_code=404, detail="No negotiations found for this user")

    return [UpcastNegotiationObject(**pydantic_to_dict(negotiation, True)) for negotiation in negotiations]


@app.put("/negotiation", summary="Update a negotiation")
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


@app.delete("/negotiation/{negotiation_id}", summary="Delete a negotiation")
async def delete_upcast_negotiation(
    negotiation_id: str = Path(..., description="The ID of the negotiation"),
    current_user: User = Depends(get_current_user)
):
    try:
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Delete the negotiation
        delete_result = await negotiations_collection.delete_one(
            {"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": str(current_user.id)}, {"producer_id": str(current_user.id)}]}
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
@router.get("/negotiation/{negotiation_id}/last-policy", summary="Get the last policy", response_model=Dict)
async def get_last_policy(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(get_current_user)
):
    try:
        negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": ObjectId(current_user.id)}, {"producer_id": ObjectId(current_user.id)}]})
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
@router.get("/negotiation/{negotiation_id}/last-policy-diff", summary="Get the last policy", response_model=Dict[str, Any])
async def get_last_policy(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        current_user: User = Depends(get_current_user)
):
    try:
        negotiation = await negotiations_collection.find_one(
            {"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": ObjectId(current_user.id)}, {"producer_id": ObjectId(current_user.id)}]}
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

@router.post("/consumer/request/new_old", summary="Create a new request")
async def create_new_upcast_request(
        current_user: User = Depends(get_current_user),
        previous_policy_id: str = Header(..., description="The ID of the previous offer"),
        body: UpcastPolicyObject = Body(..., description="The request object")
):
    try:
        # Change the policy type to "offer"
        body.type = PolicyType.REQUEST

        # Save the offer to MongoDB
        result = await policy_collection.insert_one(pydantic_to_dict(body))

        # Retrieve the generated _id
        request_id = str(result.inserted_id)

        body.type = PolicyType.REQUEST
        if not body.negotiation_id:  # If negotiation_id is empty, create a new negotiation
            negotiation = UpcastNegotiationObject(
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

@router.post("/consumer/request/new", summary="Create a new request")
async def create_new_upcast_request(
        current_user: User = Depends(get_current_user),
        previous_policy_id: str = Header(..., description="The ID of the previous offer"),
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

        return {"message": "Request sent successfully", "request_id": request_id, "negotiation_id": str(negotiation_id)}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")

@app.put("/consumer/request", summary="Update an existing request")
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

@app.put("/producer/offer", summary="Update an existing offer")
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

@app.delete("/consumer/request/{request_id}", summary="Delete a request")
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

    return [UpcastPolicyObject(**offer) for offer in offers]






@router.post("/producer/offer/new", summary="Create a new offer")
async def create_new_upcast_offer(
        current_user: User = Depends(get_current_user),
        body: UpcastPolicyObject = Body(..., description="The offer object")
):
    try:
        # Change the policy type to "offer"
        body.type = PolicyType.OFFER

        # Save the offer to MongoDB
        result = await policy_collection.insert_one(pydantic_to_dict(body))

        # Retrieve the generated _id
        offer_id = str(result.inserted_id)

        # If negotiation_id is not provided, create a new negotiation

        if body.negotiation_id:
            # Update existing negotiation by appending the offer to negotiations list
            await negotiations_collection.update_one(
                {"_id": ObjectId(str(body.negotiation_id))},
                {
                    "$set": {"negotiation_status": NegotiationStatus.OFFERED},
                    "$push": {"negotiations": ObjectId(offer_id)}
                }
            )
            negotiation_id = body.negotiation_id

            # Update the offer object with the existing negotiation_id
            await policy_collection.update_one(
                {"_id": ObjectId(offer_id)},
                {"$set": {"negotiation_id": negotiation_id}}
            )

        return {"message": "Offer sent successfully", "offer_id": str(offer_id), "negotiation_id": str(body.negotiation_id)}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")


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

    return UpcastPolicyObject(**offer)

@app.delete("/offer/{offer_id}", summary="Delete an offer")
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


@router.get("/contract/{negotiation_id}", summary="Get a contract (Under Construction)")
async def get_upcast_contract(
    negotiation_id: str = Path(..., description="The ID of the negotiation"),
    current_user: User = Depends(get_current_user)
):
    # Under Construction
    return {"message": "This endpoint is under construction"}


@router.post("/contract/sign", summary="Sign a contract (Under Construction)")
async def sign_upcast_contract(
    current_user: User = Depends(get_current_user),
    body: UpcastContractObject = Body(..., description="The contract sign object")
):
    # Under Construction
    return {"message": "This endpoint is under construction"}

#
# @router.get("/users", summary="Get all users", response_model=List[User])
# async def get_all_users():
#     users = await users_collection.find().to_list(length=None)
#     return [User(**user) for user in users]

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

@router.post("/consumer/offer/accept/{negotiation_id}", summary="Accept an offer")
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

        return {"message" : "Offer accepted successfully", "negotiation_id" : negotiation_id, "negotiation_status" : NegotiationStatus.ACCEPTED.value}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")

@router.post("/consumer/offer/verify/{negotiation_id}", summary="Verify a request")
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

        return {"message" : "Offer verified successfully", "negotiation_id" : negotiation_id, "negotiation_status" : NegotiationStatus.VERIFIED.value}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")
@router.post("/producer/request/agree/{negotiation_id}", summary = "Agree on a request")
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

        return {"message": "Request agreed successfully", "negotiation_id": str(negotiation_id), "negotiation_status" : NegotiationStatus.AGREED.value}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")

@router.post("/producer/offer/finalize/{negotiation_id}", summary="Accept an offer")
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

        return {"message": "Offer finalized successfully", "negotiation_id": str(negotiation_id), "negotiation_status" : NegotiationStatus.FINALIZED.value}
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

        return {"message": "Negotiation terminated successfully", "negotiation_id": negotiation_id, "negotiation_status": NegotiationStatus.TERMINATED.value}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")

app.include_router(router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8005)
