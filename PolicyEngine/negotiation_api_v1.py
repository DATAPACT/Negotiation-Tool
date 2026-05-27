from fastapi import FastAPI, Header, Path, Body
from pydantic import BaseModel
from typing import List
from enum import Enum
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Negotiation Plugin API",
    description="UPCAST Negotiation Plugin API",
    version="1.0",
)

# MongoDB connection
client = AsyncIOMotorClient("mongodb://localhost:27017")
db = client.upcast_database


class UpcastPolicyObject(BaseModel):
    pass


class NegotiationStatus(Enum):
    AGREED = 'agreed'
    ACCEPTED = 'accepted'
    VERIFIED = 'verified'
    FINALIZED = 'finalized'
    TERMINATED = 'terminated'


class UpcastResourceDescriptionObject(BaseModel):
    price: int
    environmental_effect: str
    naturalLanguageDocument: str
    resourceDescriptionObject: dict
    status: str
    negotiationList: list


class UpcastRequestObject(BaseModel):
    correspondingParties: dict
    dataProcessingWorkflowObject: dict
    naturalLanguageDocument: str
    resourceDescriptionObject: UpcastResourceDescriptionObject
    odrlRequest: dict
    status: str


class UpcastOfferObject(BaseModel):
    correspondingParties: dict
    dataProcessingWorkflowObject: dict
    naturalLanguageDocument: str
    resourceDescriptionObject: UpcastResourceDescriptionObject
    status: str
    negotiationList: list


class UpcastNegotiationObject(BaseModel):
    neg_ID: str
    neg_status: NegotiationStatus
    resource_description: dict
    DPW: dict  # Data Process Work Flow
    NLP: str  # Natural Language Part
    conflict_status: str  # Any detected conflict
    negotiation: List[dict]  # List of UPCAST Request or UPCAST Offer

    class Config:
        use_enum_values = True  # Ensures the enum values are used instead of the enum type


class UpcastContractObject(BaseModel):
    correspondingParties: dict
    dataProcessingWorkflowObject: dict
    naturalLanguageDocument: str
    resourceDescriptionObject: dict
    status: str
    negotiationList: list


@app.get("/negotiation/{negotiation_id}", summary="Get a negotiation")
async def get_upcast_negotiation(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(..., description="The ID of the user")
):
    negotiation = await db.negotiations.find_one({"neg_ID": negotiation_id})
    if negotiation:
        return JSONResponse(content=jsonable_encoder(negotiation))
    return JSONResponse(status_code=404, content={"message": "Negotiation not found"})


@app.put("/negotiation/{negotiation_id}", summary="Update a negotiation")
async def update_upcast_negotiation(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(..., description="The ID of the user"),
        body: UpcastNegotiationObject = Body(..., description="The negotiation object")
):
    update_result = await db.negotiations.update_one({"neg_ID": negotiation_id}, {"$set": jsonable_encoder(body)})
    if update_result.modified_count == 1:
        return JSONResponse(content={"message": "Negotiation updated successfully"})
    return JSONResponse(status_code=404, content={"message": "Negotiation not found"})


@app.post("/negotiation/create", summary="Create a negotiation")
async def create_upcast_negotiation(
        user_id: str = Header(..., description="The ID of the user"),
        body: UpcastNegotiationObject = Body(..., description="The negotiation object")
):
    new_negotiation = jsonable_encoder(body)
    result = await db.negotiations.insert_one(new_negotiation)
    return JSONResponse(content={"message": "Negotiation created successfully", "id": str(result.inserted_id)})


@app.delete("/negotiation/{negotiation_id}", summary="Delete a negotiation")
async def delete_upcast_negotiation(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(..., description="The ID of the user")
):
    delete_result = await db.negotiations.delete_one({"neg_ID": negotiation_id})
    if delete_result.deleted_count == 1:
        return JSONResponse(content={"message": "Negotiation deleted successfully"})
    return JSONResponse(status_code=404, content={"message": "Negotiation not found"})


@app.post("/negotiation/{negotiation_id}/terminate", summary="Terminate a negotiation")
async def terminate_upcast_negotiation(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(..., description="The ID of the user")
):
    update_result = await db.negotiations.update_one({"neg_ID": negotiation_id}, {"$set": {"neg_status": "TERMINATED"}})
    if update_result.modified_count == 1:
        return JSONResponse(content={"message": "Negotiation terminated successfully"})
    return JSONResponse(status_code=404, content={"message": "Negotiation not found"})


@app.post("/request/new", summary="Create a new request")
async def create_new_upcast_request(
        user_id: str = Header(..., description="The ID of the user"),
        body: UpcastRequestObject = Body(..., description="The request object")
):
    new_request = jsonable_encoder(body)
    result = await db.requests.insert_one(new_request)
    return JSONResponse(content={"message": "Request created successfully", "id": str(result.inserted_id)})


@app.post("/request/update", summary="Update a request for an existing negotiation")
async def update_upcast_request(
        user_id: str = Header(..., description="The ID of the user"),
        negotiation_id: str = Header(..., description="The ID of the negotiation"),
        body: UpcastRequestObject = Body(..., description="The request object")
):
    update_result = await db.requests.update_one({"negotiation_id": negotiation_id}, {"$set": jsonable_encoder(body)})
    if update_result.modified_count == 1:
        return JSONResponse(content={"message": "Request updated successfully"})
    return JSONResponse(status_code=404, content={"message": "Request not found"})


@app.post("/request/accept", summary="Accept a request")
async def accept_upcast_request(
        user_id: str = Header(..., description="The ID of the user"),
        body: UpcastRequestObject = Body(..., description="The request object")
):
    # Custom logic to accept a request can be added here
    return JSONResponse(content={"successMessage": "success", "acceptedPolicy": UpcastPolicyObject()})


@app.post("/offer/new", summary="Send an offer and create a new negotiation")
async def create_new_upcast_offer(
        user_id: str = Header(..., description="The ID of the user"),
        body: UpcastOfferObject = Body(..., description="The offer object")
):
    new_offer = jsonable_encoder(body)
    result = await db.offers.insert_one(new_offer)
    return JSONResponse(content={"message": "Offer created successfully", "id": str(result.inserted_id)})


@app.post("/offer/update", summary="Update an offer for an existing negotiation")
async def update_upcast_offer(
        user_id: str = Header(..., description="The ID of the user"),
        negotiation_id: str = Header(..., description="The ID of the negotiation"),
        body: UpcastOfferObject = Body(..., description="The offer object")
):
    update_result = await db.offers.update_one({"negotiation_id": negotiation_id}, {"$set": jsonable_encoder(body)})
    if update_result.modified_count == 1:
        return JSONResponse(content={"message": "Offer updated successfully"})
    return JSONResponse(status_code=404, content={"message": "Offer not found"})


@app.post("/offer/accept", summary="Accept an offer")
async def accept_upcast_offer(
        user_id: str = Header(..., description="The ID of the user"),
        negotiation_id: str = Header(..., description="The ID of the negotiation"),
        body: UpcastOfferObject = Body(..., description="The offer object")
):
    # Custom logic to accept an offer can be added here
    return JSONResponse(content={"successMessage": "success", "acceptedPolicy": UpcastPolicyObject()})


@app.get("/contract/{negotiation_id}", summary="Get a contract")
async def get_upcast_contract(
        negotiation_id: str = Path(..., description="The ID of the negotiation"),
        user_id: str = Header(..., description="The ID of the user")
):
    contract = await db.contracts.find_one({"negotiation_id": negotiation_id})
    if contract:
        return JSONResponse(content=jsonable_encoder(contract))
    return JSONResponse(status_code=404, content={"message": "Contract not found"})


@app.post("/contract/sign", summary="Sign a contract")
async def sign_upcast_contract(
        user_id: str = Header(..., description="The ID of the user"),
        body: UpcastContractObject = Body(..., description="The contract sign object")
):
    new_contract = jsonable_encoder(body)
    result = await db.contracts.insert_one(new_contract)
    return JSONResponse(content={"message": "Contract signed successfully", "id": str(result.inserted_id)})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)
