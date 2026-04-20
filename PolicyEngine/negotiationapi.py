from fastapi import FastAPI, Header, Path, Body
from typing import List, Dict
from enum import Enum
from pydantic import BaseModel, Field, validator, field_validator

from fastapi import FastAPI, HTTPException, Header, Body
from typing import List, Dict, Optional, Any
from enum import Enum
from pydantic import BaseModel, Field, root_validator
from motor.motor_asyncio import AsyncIOMotorClient
import uuid
from datetime import datetime
from bson import ObjectId
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request


app = FastAPI(
    title="Negotiation Plugin API",
    description="UPCAST Negotiation Plugin API",
    version="1.0",
)

origins = ["*",
           "http://127.0.0.1:8000",
           "http://localhost:8000",
           "http://62.171.168.208:8000" # Adjust this to your frontend's address
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

class PolicyType(str, Enum):
    OFFER = 'offer'
    REQUEST = 'request'


class PartyType(str, Enum):
    CONSUMER = 'consumer'
    PRODUCER = 'producer'


class User(MongoObject):
    name: Optional[str] = None
    type: PartyType

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
    data_processing_workflow_object: List
    natural_language_document: str
    resource_description_object: UpcastResourceDescriptionObject
    odrl_policy: Dict
    negotiation_id: Optional[object] = None
    is_read_only: bool = Field(default=False, description="Indicates whether the policy is locked for editing.")
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)



class UpcastNegotiationObject(MongoObject):
    title: Optional[str] = None
    consumer_id: object
    producer_id: object
    negotiation_status: str  # Assuming NegotiationStatus is a string for this example
    resource_description: Dict
    dpw: List  # Data Process Workflow
    nlp: str  # Natural Language Part
    conflict_status: str  # Any detected conflict
    negotiations: List[object]  # List of UPCAST Request or UPCAST Offer
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

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



user = "semih"
password = "a8Spt66DKqGh2V0T"
host = "cluster0.btnpvyy.mongodb.net"
MONGO_DETAILS = f"mongodb+srv://{user}:{password}@{host}/?retryWrites=true&w=majority&appName=Cluster0"

client = AsyncIOMotorClient(MONGO_DETAILS)
db = client.datapack
negotiations_collection = db.negotiations
requests_collection = db.requests
offers_collection = db.offers
policy_collection = db.policies
contracts_collection = db.contracts
users_collection = db.users


@app.post("/negotiation/create", summary="Create a negotiation")
async def create_upcast_negotiation(
        user_id: str = Header(..., description="The ID of the user"),
        body: UpcastPolicyObject = Body(..., description="The request object")
):
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
        negotiations=[ObjectId(body.id)]
    )

    result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
    if result.inserted_id:
        return {"negotiation_id": str(result.inserted_id)}

    raise HTTPException(status_code=500, detail="Negotiation could not be created")



@app.get("/negotiation/{negotiation_id}", summary="Get a negotiation", response_model=UpcastNegotiationObject)
async def get_upcast_negotiation(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(..., description="The ID of the user")
):

    negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id)})
    if negotiation:
        return UpcastNegotiationObject(**pydantic_to_dict(negotiation, True))

    raise HTTPException(status_code=404, detail="Negotiation not found")

@app.get("/negotiation", summary="Get negotiations", response_model=List[UpcastNegotiationObject])
async def get_upcast_negotiations(
    user_id: str = Header(..., description="The ID of the user")
):
    # Fetch the user object based on the user_id
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Retrieve negotiations where the user is either a consumer or a producer
    negotiations = await negotiations_collection.find(
        {"$or": [{"consumer_id": ObjectId(user["_id"])}, {"producer_id": ObjectId(user["_id"])}]}
    ).to_list(length=None)

    if not negotiations:
        return []
        # raise HTTPException(status_code=404, detail="No negotiations found for this user")

    return [UpcastNegotiationObject(**pydantic_to_dict(negotiation, True)) for negotiation in negotiations]

@app.put("/negotiation", summary="Update a negotiation")
async def update_upcast_negotiation(
    user_id: str = Header(..., description="The ID of the user"),
    body: UpcastNegotiationObject = Body(..., description="The negotiation object")
):
    update_result = await negotiations_collection.update_one({"_id":ObjectId(body.id)},
        {"$set": pydantic_to_dict(body)}
    )

    if update_result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Negotiation not found or you do not have permission to update this negotiation")

    if update_result.modified_count == 0:
        raise HTTPException(status_code=400, detail="No changes")

    return {"message": "Negotiation updated successfully", "negotiation_id": body.id}


@app.delete("/negotiation/{negotiation_id}", summary="Delete a negotiation")
async def delete_upcast_negotiation(
    negotiation_id: str = Path(..., description="The ID of the negotiation"),
    user_id: str = Header(..., description="The ID of the user")
):
    # Fetch the user object based on the user_id
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Delete the negotiation
    delete_result = await negotiations_collection.delete_one(
        {"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": str(user["_id"])}, {"producer_id": str(user["_id"])}]}
    )

    if delete_result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Negotiation not found or you do not have permission to delete this negotiation")

    # Delete corresponding requests
    await policy_collection.delete_many({"negotiation_id": ObjectId(negotiation_id)})

    # Delete corresponding offers
    await policy_collection.delete_many({"negotiation_id": ObjectId(negotiation_id)})

    return {"message": "Negotiation and corresponding requests and offers deleted successfully", "negotiation_id": negotiation_id}


# New endpoint
@app.get("/negotiation/{negotiation_id}/last-policy", summary="Get the last policy", response_model=Dict)
async def get_last_policy(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(..., description="The ID of the user")
):
    negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": ObjectId(user_id)}, {"producer_id": ObjectId(user_id)}]})
    if not negotiation:
        raise HTTPException(status_code=404, detail="Negotiation not found")

    negotiations_list = negotiation.get("negotiations", [])
    if not negotiations_list:
        raise HTTPException(status_code=404, detail="No policies found in the negotiations")

    request = await policy_collection.find_one({"_id": ObjectId(negotiations_list[-1])})
    last_policy = negotiations_list[-1]
    return pydantic_to_dict(request,True)



# Recursive function to find changes in nested dictionaries
def find_changes(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    changes = {}
    for key in new:
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
        if key not in new:
            changes[key] = {"from": old[key], "to": None}
    return changes


# Endpoint to get the last policy and the changes between the last two policies
@app.get("/negotiation/{negotiation_id}/last-policy-diff", summary="Get the last policy", response_model=Dict[str, Any])
async def get_last_policy(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(..., description="The ID of the user")
):
    negotiation = await negotiations_collection.find_one(
        {"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": ObjectId(user_id)}, {"producer_id": ObjectId(user_id)}]}
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

@app.post("/consumer/request/new", summary="Create a new request")
async def create_new_upcast_request(
        user_id: str = Header(..., description="The ID of the user"),
        body: UpcastPolicyObject = Body(..., description="The request object")
):
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
        # Update existing negotiation by appending the request to negotiations list
        await negotiations_collection.update_one(
            {"_id": ObjectId(body.negotiation_id)},
            {"$push": {"negotiations": ObjectId(request_id)}}
        )
        negotiation_id = body.negotiation_id
    return {"message": "Request sent successfully", "request_id": request_id, "negotiation_id": str(negotiation_id)}

@app.get("/consumer/request/{request_id}", summary="Get an existing request", response_model=UpcastPolicyObject)
async def get_upcast_request(
    request_id: str = Path(..., description="The ID of the request"),
    user_id: str = Header(..., description="The ID of the user")
):
    request = await policy_collection.find_one({"_id": ObjectId(request_id)})
    if request:
        return UpcastPolicyObject(**pydantic_to_dict(request, True))
    else:
        raise HTTPException(status_code=404, detail="Request not found")


@app.put("/consumer/request", summary="Update an existing request")
async def update_upcast_request(
    user_id: str = Header(..., description="The ID of the user"),
    body: UpcastPolicyObject = Body(..., description="The request object")
):
    update_result = await policy_collection.update_one({"_id":ObjectId(body.id)},
        {"$set": pydantic_to_dict(body)}
    )

    if update_result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Request not found or you do not have permission to update this request")

    if update_result.modified_count == 0:
        raise HTTPException(status_code=400, detail="No changes")

    return {"message": "Request updated successfully", "request_id": body.id}


    await policy_collection.replace_one({"_id": body.id}, pydantic_to_dict(body))
    return {"message": "Request updated successfully", "request_id": body.id}


@app.delete("/consumer/request/{request_id}", summary="Delete a request")
async def delete_upcast_request(
        request_id: str = Path(..., description="The ID of the request"),
        user_id: str = Header(..., description="The ID of the user")
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


@app.get("/consumer/offer", summary="Get available offers", response_model=List[UpcastPolicyObject])
async def get_upcast_offers(
        user_id: str = Header(..., description="The ID of the user")
):
    offers = await policy_collection.find({'type':'offer'}).to_list(length=None)

    if not offers:
        raise HTTPException(status_code=404, detail="No offers found")

    return [UpcastPolicyObject(**offer) for offer in offers]






@app.post("/producer/offer/new", summary="Create a new offer")
async def create_new_upcast_offer(
        user_id: str = Header(..., description="The ID of the user"),
        body: UpcastPolicyObject = Body(..., description="The offer object")
):
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



@app.get("/producer/offer/{offer_id}", summary="Get an existing offer", response_model=UpcastPolicyObject)
async def get_upcast_offer(
        offer_id: str = Path(..., description="The ID of the offer"),
        user_id: str = Header(..., description="The ID of the user")
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
        user_id: str = Header(..., description="The ID of the user")
):
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


#
# @app.post("/producer/offer/finalize", summary="Accept an offer")
# async def accept_upcast_offer(
#     user_id: str = Header(..., description="The ID of the user"),
#     offer_id: str = Header(..., description="The ID of the offer")
# ):
#     return {"message": "Offer finalized successfully", "offer_id": offer_id}


@app.get("/contract/{negotiation_id}", summary="Get a contract (Under Construction)")
async def get_upcast_contract(
    negotiation_id: str = Path(..., description="The ID of the negotiation"),
    user_id: str = Header(..., description="The ID of the user")
):
    # Under Construction
    return {"message": "This endpoint is under construction"}


@app.post("/contract/sign", summary="Sign a contract (Under Construction)")
async def sign_upcast_contract(
    user_id: str = Header(..., description="The ID of the user"),
    body: UpcastContractObject = Body(..., description="The contract sign object")
):
    # Under Construction
    return {"message": "This endpoint is under construction"}


@app.post("/user/new", summary="Create a new user", response_model=User)
async def create_user(user: User):
    user_obj = await users_collection.insert_one(pydantic_to_dict(user))
    created_user = await users_collection.find_one({"_id": user_obj.inserted_id})
    if created_user is None:
        raise HTTPException(status_code=500, detail="Failed to create user")
    return User(**created_user)

@app.get("/user/{user_id}", summary="Get a user by ID", response_model=User)
async def get_user(user_id: str):
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return User(**user)

@app.get("/users", summary="Get all users", response_model=List[User])
async def get_all_users():
    users = await users_collection.find().to_list(length=None)
    return [User(**user) for user in users]

@app.put("/user/{user_id}", summary="Update a user by ID", response_model=User)
async def update_user(user_id: str, user: User):
    await users_collection.update_one({"_id": ObjectId(user_id)}, {"$set": pydantic_to_dict(user)})
    updated_user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if updated_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return User(**updated_user)


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

@app.post("/consumer/offer/accept/{negotiation_id}", summary="Accept an offer")
async def accept_upcast_request(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        # offer_id: str = Path(..., description="The ID of the offer"),
        user_id: str = Header(None, description="The ID of the user")
):
    # negotiation_id = await get_negotiation_id(offer_id, negotiation_id)

    update_result = await negotiations_collection.update_one(
        {"_id": ObjectId(negotiation_id)},
        {"$set": {"negotiation_status": NegotiationStatus.ACCEPTED.value}}
    )

    return {"message" : "Offer accepted successfully", "negotiation_id" : negotiation_id, "negotiation_status" : NegotiationStatus.ACCEPTED.value}

@app.post("/consumer/offer/verify/{negotiation_id}", summary="Verify a request")
async def verify_upcast_request(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        # offer_id: str = Path(..., description="The ID of the request"),
        user_id: str = Header(None, description="The ID of the user")
):
    # negotiation_id = await get_negotiation_id(offer_id, negotiation_id)

    update_result = await negotiations_collection.update_one(
        {"_id": ObjectId(negotiation_id)},
        {"$set": {"negotiation_status": NegotiationStatus.VERIFIED.value}}
    )

    return {"message" : "Offer verified successfully", "negotiation_id" : negotiation_id, "negotiation_status" : NegotiationStatus.VERIFIED.value}

@app.post("/producer/request/agree/{negotiation_id}", summary = "Agree on a request")
async def agree_upcast_offer(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(None, description="The ID of the user")
):
    # negotiation_id = await get_negotiation_id(request_id, negotiation_id)

    update_result = await negotiations_collection.update_one(
        {"_id": ObjectId(negotiation_id)},
        {"$set": {"negotiation_status": NegotiationStatus.AGREED.value}}
    )

    return {"message": "Request agreed successfully", "negotiation_id": str(negotiation_id), "negotiation_status" : NegotiationStatus.AGREED.value}

@app.post("/producer/offer/finalize/{negotiation_id}", summary="Accept an offer")
async def finalize_upcast_offer(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        # offer_id: str = Path(..., description="The ID of the offer"),
        user_id: str = Header(None, description="The ID of the user")
):
    # negotiation_id = await get_negotiation_id(offer_id, negotiation_id)

    update_result = await negotiations_collection.update_one(
        {"_id": ObjectId(negotiation_id)},
        {"$set": {"negotiation_status": NegotiationStatus.FINALIZED.value}}
    )

    return {"message": "Offer finalized successfully", "negotiation_id": str(negotiation_id), "negotiation_status" : NegotiationStatus.FINALIZED.value}

@app.post("/negotiation/terminate/{negotiation_id}", summary="Terminate a negotiation")
async def terminate_upcast_negotiation(
    negotiation_id: str = Path(..., description="The ID of the negotiation"),
    user_id: str = Header(None, description="The ID of the user")
):
    update_result = await negotiations_collection.update_one(
        {"_id": ObjectId(negotiation_id)},
        {"$set": {"negotiation_status": NegotiationStatus.TERMINATED.value}}
    )

    if update_result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Negotiation not found or you do not have permission to terminate this negotiation")

    return {"message": "Negotiation terminated successfully", "negotiation_id": negotiation_id, "negotiation_status": NegotiationStatus.TERMINATED.value}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
