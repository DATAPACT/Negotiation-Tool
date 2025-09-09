import os
import traceback

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
from dotenv import load_dotenv

from data_model import User, UpcastNegotiationObject, UpcastPolicyObject, UpcastResourceDescriptionObject, PolicyDiffObject, UpcastContractObject, PolicyChange, PolicyDiffResponse, UpcastPolicyConverter, PolicyType, NegotiationStatus
from data_model import PartyType, Preference, PolicyKey, RecommenderAgentRecord
from recommender.agent import new_offer, new_request


app = FastAPI(
    title="Negotiation Plugin API",
    description="UPCAST Negotiation Plugin API",
    version="1.0",
)

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


class MongoObject(BaseModel):
    id: Optional[object] = Field(None, alias="_id")
    @field_validator("id")
    def process_id(cls, value, values):
        if isinstance(value, ObjectId):
            return str(value)
        return value



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
print(f'MONGO_USER {MONGO_USER}')
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
print(f'MONGO_PASSWORD {MONGO_PASSWORD}')
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
print(f'MONGO_HOST {MONGO_HOST}')
# MONGO_PORT = os.getenv("MONGO_PORT")
# if MONGO_PORT: # Assumption: A local or remote installation of MongoDB is provided.
#     MONGO_PORT = int(MONGO_PORT)
#     MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}"
# else: # Assumption: The database is stored in mongodb cloud.
#     MONGO_URI = f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}/?retryWrites=true&w=majority&appName=Cluster0"

MONGO_URI = "mongodb://root:rootpassword@localhost:27017/"
print(f'MONGO_URI {MONGO_URI}')

client = AsyncIOMotorClient(MONGO_URI)
print(f'client {client}')
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

@app.post("/negotiation/create", summary="Create a negotiation")
async def create_upcast_negotiation(
        user_id: str = Header(..., description="The ID of the user"),
        body: UpcastPolicyObject = Body(..., description="The request object")
):
    try:
        conflict_status = "no conflict"

        # Retrieve consumer and provider objects from users_collection
        consumer = await users_collection.find_one({"_id": ObjectId(body.consumer_id)})
        provider = await users_collection.find_one({"_id": ObjectId(body.provider_id)})

        if consumer is None or provider is None:
            raise HTTPException(status_code=404, detail="Consumer or provider not found")

        body.consumer_id = ObjectId(str(body.consumer_id))
        body.provider_id = ObjectId(str(body.provider_id))

        negotiation = UpcastNegotiationObject(
            user_id=user_id,
            consumer_id=ObjectId(consumer["_id"]),
            provider_id=ObjectId(provider["_id"]),
            negotiation_status=NegotiationStatus.REQUESTED,
            resource_description=body.resource_description_object.dict(),
            dpw=body.data_processing_workflow_object,
            nlp=body.natural_language_document,
            conflict_status=conflict_status,
            negotiations=[ObjectId(body.id)],
            original_offer_id=ObjectId(body.id),
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

@app.get("/negotiation/{negotiation_id}", summary="Get a negotiation", response_model=UpcastNegotiationObject)
async def get_upcast_negotiation(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(..., description="The ID of the user")
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


@app.get("/negotiation/policies/{negotiation_id}", summary="Get policies related to a negotiation", response_model=List[UpcastPolicyObject])
async def get_policies_for_negotiation(
    negotiation_id: str = Path(..., description="The ID of the negotiation")
):
    try:
        object_id = ObjectId(negotiation_id)
    except:
        raise HTTPException(status_code=400, detail="Invalid negotiation_id format")

    policies = await policy_collection.find({"negotiation_id": object_id}).to_list(length=None)

    if not policies:
        raise HTTPException(status_code=404, detail="No policies found for this negotiation")

    return [UpcastPolicyObject(**pydantic_to_dict(policy, True)) for policy in policies]



@app.get("/negotiation", summary="Get negotiations", response_model=List[UpcastNegotiationObject])
async def get_upcast_negotiations(
    user_id: str = Header(..., description="The ID of the user")
):
    # Fetch the user object based on the user_id
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Retrieve negotiations where the user is either a consumer or a provider
    negotiations = await negotiations_collection.find(
        {"$or": [{"consumer_id": ObjectId(user["_id"])}, {"provider_id": ObjectId(user["_id"])}]}
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
    user_id: str = Header(..., description="The ID of the user")
):
    try:
        # Fetch the user object based on the user_id
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Delete the negotiation
        delete_result = await negotiations_collection.delete_one(
            {"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": str(user["_id"])}, {"provider_id": str(user["_id"])}]}
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
@app.get("/negotiation/{negotiation_id}/last-policy", summary="Get the last policy", response_model=Dict)
async def get_last_policy(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(..., description="The ID of the user")
):
    try:
        negotiation = await negotiations_collection.find_one({"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": ObjectId(user_id)}, {"provider_id": ObjectId(user_id)}]})
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
@app.get("/negotiation/{negotiation_id}/last-policy-diff", summary="Get the last policy", response_model=Dict[str, Any])
async def get_last_policy(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(..., description="The ID of the user")
):
    try:
        negotiation = await negotiations_collection.find_one(
            {"_id": ObjectId(negotiation_id), "$or": [{"consumer_id": ObjectId(user_id)}, {"provider_id": ObjectId(user_id)}]}
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
            "changes": changes,
        }

        return result
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")

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

@app.post("/consumer/request/new_old", summary="Create a new request")
async def create_new_upcast_request(
        user_id: str = Header(..., description="The ID of the user"),
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
                user_id=user_id,
                consumer_id=ObjectId(body.consumer_id),
                provider_id=ObjectId(body.provider_id),  # Assuming provider_id is available in the request object
                negotiation_status=NegotiationStatus.REQUESTED,
                resource_description=body.resource_description_object.dict(),
                dpw=body.data_processing_workflow_object,
                nlp=body.natural_language_document,
                conflict_status="",  # Initialize with an empty string
                negotiations=[ObjectId(request_id)], # Add the request to negotiations list
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

@app.post("/consumer/request/new", summary="Create a new request")
async def create_new_upcast_request(
        user_id: str = Header(..., description="The ID of the user"),
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
        
        print(f'policy negotiation_id {body.negotiation_id}')

        if not body.negotiation_id:  # If negotiation_id is empty, create a new negotiation
            print('no negotiation id')
            negotiation = UpcastNegotiationObject(
                user_id=user_id,
                title = body.title,
                consumer_id=ObjectId(body.consumer_id),
                provider_id=ObjectId(body.provider_id),  # Assuming provider_id is available in the request object
                negotiation_status=NegotiationStatus.REQUESTED,
                resource_description=body.resource_description_object.dict(),
                dpw=body.data_processing_workflow_object,
                nlp=body.natural_language_document,
                conflict_status="",  # Initialize with an empty string
                negotiations=[ObjectId(request_id)],  # Add the request to negotiations list
            )

            result = await negotiations_collection.insert_one(pydantic_to_dict(negotiation))
            print(f'result of inserting negotiation into negotiations collection {result}')
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
    user_id: str = Header(..., description="The ID of the user"),
    body: UpcastPolicyObject = Body(..., description="The request object")
):
    try:
 
        
        # Change the policy type to "offer"
        body.type = PolicyType.OFFER
        body.provider_id = user_id
        # Save the offer to MongoDB
        result = await policy_collection.insert_one(pydantic_to_dict(body))

        # Retrieve the generated _id
        request_id = str(result.inserted_id)

        body.type = PolicyType.REQUEST
        if not body.negotiation_id:  # If negotiation_id is empty, create a new negotiation
            negotiation = UpcastNegotiationObject(
                user_id=user_id,
                title = body.title,
                consumer_id=ObjectId(body.consumer_id),
                provider_id=ObjectId(body.provider_id),  # Assuming provider_id is available in the request object
                negotiation_status=NegotiationStatus.REQUESTED,
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


        return {"message": "Request sent successfully", "request_id": request_id, "negotiation_id": str(negotiation_id)}
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")

@app.put("/provider/offer", summary="Update an existing offer")
async def update_upcast_offer(
    user_id: str = Header(..., description="The ID of the user"),
    body: UpcastPolicyObject = Body(..., description="The request object")
):
    try:
        
        # Change the policy type to "offer"
        body.type = PolicyType.OFFER
        body.consumer_id = user_id

        plc = pydantic_to_dict(body)
        plc.pop("id")
        # Save the offer to MongoDB
        
        print('policy negotiation_id', body.negotiation_id)

        if not body.negotiation_id:
            result = await policy_collection.insert_one(pydantic_to_dict(body))
            # Retrieve the generated _id
            request_id = str(result.inserted_id)
            negotiation = UpcastNegotiationObject(
                user_id=user_id,
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

    return [UpcastPolicyObject(**{**offer, "_id": str(offer["_id"])}) for offer in offers]



@app.post("/provider/offer/new", summary="Create a new offer")
async def create_new_upcast_offer(
        user_id: str = Header(..., description="The ID of the user"),
        body: UpcastPolicyObject = Body(..., description="The offer object")
):
    try:               
        
        # Change the policy type to "offer"
        body.type = PolicyType.OFFER
        

        # Save the offer to MongoDB
        result = await policy_collection.insert_one(pydantic_to_dict(body))
        print(f'result {result}')

        # Retrieve the generated _id
        offer_id = str(result.inserted_id)
        print(f'offer_id {offer_id}')

        # If negotiation_id is not provided, create a new negotiation
        print(f'policy negotiation_id {body.negotiation_id}')
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


@app.get("/provider/offer/{offer_id}", summary="Get an existing offer", response_model=UpcastPolicyObject)
async def get_upcast_offer(
        offer_id: str = Path(..., description="The ID of the offer"),
        user_id: str = Header(..., description="The ID of the user")
):
    # Convert offer_id to ObjectId
    offer_object_id = ObjectId(offer_id)
    
    print('offer_object_id', offer_object_id)

    # Retrieve the offer from the database using the converted ObjectId
    offer = await policy_collection.find_one({"_id": offer_object_id})
    print('offer', offer)

    # Check if the offer exists
    if offer is None:
        raise HTTPException(status_code=404, detail="Offer not found")

    return UpcastPolicyObject(**{**offer, "_id": str(offer["_id"])})



@app.delete("/offer/{offer_id}", summary="Delete an offer")
async def delete_upcast_offer(
        offer_id: str = Path(..., description="The ID of the offer"),
        user_id: str = Header(..., description="The ID of the user")
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
# @app.post("/provider/offer/finalize", summary="Accept an offer")
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
    try:
        user_obj = await users_collection.insert_one(pydantic_to_dict(user))
        created_user = await users_collection.find_one({"_id": user_obj.inserted_id})
        if created_user is None:
            raise HTTPException(status_code=500, detail="Failed to create user")
        return User(**created_user)
    except BaseException as e:
        error_message = traceback.format_exc()  # get the full traceback
        raise HTTPException(status_code=500,
                            detail=f"Exception: {str(e)}. Traceback: {error_message}")
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

@app.post("/consumer/offer/verify/{negotiation_id}", summary="Verify a request")
async def verify_upcast_request(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        # offer_id: str = Path(..., description="The ID of the request"),
        user_id: str = Header(None, description="The ID of the user")
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
@app.post("/provider/request/agree/{negotiation_id}", summary = "Agree on a request")
async def agree_upcast_offer(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(None, description="The ID of the user")
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

@app.post("/provider/offer/finalize/{negotiation_id}", summary="Accept an offer")
async def finalize_upcast_offer(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        # offer_id: str = Path(..., description="The ID of the offer"),
        user_id: str = Header(None, description="The ID of the user")
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

@app.post("/negotiation/terminate/{negotiation_id}", summary="Terminate a negotiation")
async def terminate_upcast_negotiation(
    negotiation_id: str = Path(..., description="The ID of the negotiation"),
    user_id: str = Header(None, description="The ID of the user")
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
        
        
        
@app.post("/agent/new", summary="Create a new agent")
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
@app.get("/agent", summary="Get recommender agent records by user ID")
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
@app.get("/agent/{negotiation_id}", summary="Get recommender agent records by user ID")
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
@app.get("/agent/latest/{negotiation_id}", summary="Get recommender agent records by user ID")
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

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)


