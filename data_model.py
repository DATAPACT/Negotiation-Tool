import json
import os
import traceback
import urllib.parse
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Dict, Optional, Any, Union
from typing import Optional, Union, Dict, Any, Literal
from datetime import datetime, timedelta
from pydantic import Field, validator
from bson import ObjectId
import requests
from confluent_kafka import Producer, KafkaException
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Depends, Request
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
from rdflib import Graph
from starlette.responses import JSONResponse

from PolicyConverter import UpcastPolicyConverter

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
    PROVIDER = 'provider'

class User(MongoObject):
    name: Optional[str] = None
    type: Optional[PartyType] = None
    username_email: Optional[EmailStr] = None
    password: Optional[str] = Field(default=None)
    # organization: Optional[str] = Field(default=None)
    organization: Optional[Union[List[str], str]] = Field(default=None)
    incorporation: Optional[str] = Field(default=None)
    address: Optional[str] = Field(default=None)
    vat_no: Optional[str] = Field(default=None)  # VAT account if possible
    position_title: Optional[str] = Field(default=None)
    phone: Optional[str] = Field(default=None)

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
    geographic_scope: Optional[Union[List[str], str]] = Field(default=None)
    categories: Optional[Union[List[str], str]] = Field(default=None) # new field for JOT
    tags: Optional[Union[List[str], str]] = Field(default=None)
    languages: Optional[Union[List[str], str]] = Field(default=None)
    temporal_coverage: Optional[List[str]] = Field(default=None)
    publisher: Optional[str] = None
    theme: Optional[Union[List[str], str]] = Field(default=None)
    distribution: Optional[Dict[str, str]] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    raw_object: Optional[Dict] = None


class UpcastPolicyObject(MongoObject):
    id: Optional[str] = Field(alias="_id", default=None)
    title: Optional[str] = None
    type: Optional[str] = None  # Assuming PolicyType is a string for this example
    consumer_id: Optional[object]
    user_id: Optional[object] = None
    provider_id: Optional[object] = None
    data_processing_workflow_object: Optional[Dict]
    natural_language_document: str
    resource_description_object: UpcastResourceDescriptionObject
    validity_period: Optional[object] = None

    odrl_policy: Optional[object] = None
    negotiation_id: Optional[object] = None
    is_read_only: bool = Field(default=False, description="Indicates whether the policy is locked for editing.")
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

    contract_id: Optional[object] = None
    contract_type: Literal["dsa", "pda", "cactus_dsa"] = Field( default="dsa", description="Type of contract.")


class PolicyChange(BaseModel):
    from_value: Optional[Any] = Field(None, alias="from")
    to: Optional[Any] = None

class PolicyDiffObject(BaseModel):
    title: Optional[PolicyChange] = None
    provider_id: Optional[PolicyChange] = None
    data_processing_workflow_object: Optional[Dict[str, Any]] = None
    natural_language_document: Optional[PolicyChange] = None
    resource_description_object: Optional[Dict[str, PolicyChange]] = None
    odrl_policy: Optional[Dict[str, PolicyChange]] = None
    # custom_arrangement_section: Optional[Dict[str, PolicyChange]] = None
    # custom_definitions: Optional[Dict[str, PolicyChange]] = None
    class Config:
        extra = "allow"

class PolicyDiffResponse(BaseModel):
    last_policy: UpcastPolicyObject
    changes: PolicyDiffObject

class PolicyKey(str, Enum):
    PRICE = "price"
    ACTION = "action"
    PURPOSE = "purpose"
    ACTOR = "actor"
    ENVIRONMENTAL = "environmental"


class Preference(BaseModel):
    key: PolicyKey
    upper_value: Any
    lower_value: Any
    class Config:
        arbitrary_types_allowed = True

class RecommenderAgentRecord(BaseModel):
    agent_type: PartyType
    preferences: List[Preference]
    previous_offer: UpcastPolicyObject  # This needs to be defined elsewhere
    previous_request: Optional[UpcastPolicyObject]  # Optional indicates this field can be None
    negotiation_id: object
    user_id: object
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

class UpcastNegotiationObject(MongoObject):
    title: Optional[str] = None
    user_id: Optional[object] = None
    consumer_id: object
    provider_id: object
    negotiation_status: str  # Assuming NegotiationStatus is a string for this example
    resource_description: Dict
    dpw: Dict  # Data Process Workflow
    nlp: str  # Natural Language Part
    conflict_status: str  # Any detected conflict
    negotiations: List[object]  # List of UPCAST Request or UPCAST Offer
    negotiation_contracts: Optional[List[object]] = Field(default_factory=list)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    original_offer_id: Optional[object] = None

    class Config:
        use_enum_values = True  # Ensures the enum values are used instead of the enum type


class UpcastContractObject(MongoObject):
    id: Optional[str] = Field(alias="_id", default=None)
    title: Optional[str] = None
    type: str  # Assuming PolicyType is a string for this example
    consumer_id: Optional[object]
    provider_id: object
    data_processing_workflow_object: Optional[Dict]
    natural_language_document: str
    resource_description_object: UpcastResourceDescriptionObject
    odrl_policy: Dict
    negotiation_id: Optional[object] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)




class NegotiationCreationRequest(BaseModel):
    """
    Model for creating a negotiation with initial offer and request policies.
    """
    provider_id: str = Field(..., description="ID of the provider user")
    consumer_id: str = Field(..., description="ID of the consumer user")
    initial_offer: UpcastPolicyObject = Field(..., description="Initial offer policy object")
    initial_request: UpcastPolicyObject = Field(..., description="Initial request policy object")
    negotiation_status: NegotiationStatus = Field(..., description="Initial status of the negotiation")
    title: Optional[str] = Field(None, description="Optional negotiation title override")
    resource_description: Optional[Dict[str, Any]] = Field(None, description="Optional resource description override")
    dpw: Optional[Dict[str, Any]] = Field(None, description="Optional data processing workflow override")
    nlp: Optional[str] = Field(None, description="Optional natural language document override")

    class Config:
        schema_extra = {
            "example": {
                "provider_id": "507f1f77bcf86cd799439011",
                "consumer_id": "507f1f77bcf86cd799439012",
                "negotiation_status": "requested",
                "initial_offer": {
                    "title": "Data Access Offer",
                    "natural_language_document": "Offering access to customer data for analytics",
                    "resource_description_object": {
                        "title": "Customer Analytics Dataset",
                        "price": 100.0,
                        "price_unit": "EUR",
                        "uri": "https://example.com/dataset",
                        "description": "Customer behavior analytics data"
                    },
                    "odrl_policy": {},
                    "data_processing_workflow_object": {}
                },
                "initial_request": {
                    "title": "Data Access Request",
                    "natural_language_document": "Requesting access to customer data for machine learning",
                    "resource_description_object": {
                        "title": "Customer Analytics Dataset Request",
                        "price": 80.0,
                        "price_unit": "EUR",
                        "uri": "https://example.com/dataset",
                        "description": "Need customer data for ML training"
                    },
                    "odrl_policy": {},
                    "data_processing_workflow_object": {}
                },
                "title": "Customer Data Negotiation",
                "resource_description": {
                    "custom_field": "custom_value"
                },
                "dpw": {
                    "workflow_step": "data_processing"
                },
                "nlp": "Custom negotiation description"
            }
        }

def pydantic_to_dict(obj, clean_id=False):
    if isinstance(obj, UpcastPolicyObject):
        try:
            obj.consumer_id = ObjectId(obj.consumer_id)
        except:
            pass
        try:
            obj.provider_id = ObjectId(obj.provider_id)
        except:
            pass
    if isinstance(obj, UpcastNegotiationObject):
        try:
            obj.consumer_id = ObjectId(obj.consumer_id)
        except:
            pass
        try:
            obj.provider_id = ObjectId(obj.provider_id)
        except:
            pass
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
    if isinstance(obj, datetime):
        return obj.isoformat()

    return obj
