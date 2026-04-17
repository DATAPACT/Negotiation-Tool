import asyncio
import logging
import os
from datetime import datetime
from enum import Enum
from typing import Dict
from typing import Optional
import json
import httpx
import requests
from bson import ObjectId
from dotenv import load_dotenv
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pydantic import field_validator
from typing import Any, Dict, List, Literal, Optional

# Configure root logger once (e.g. at program entrypoint)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

load_dotenv()

API_CONTRACT_SERVICE_URL = os.environ.get("API_CONTRACT_SERVICE_URL")

if not API_CONTRACT_SERVICE_URL:
    raise ValueError("API_CONTRACT_SERVICE_URL environment variable is not set.")

MONGO_USER = os.getenv("MONGO_USER")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD")
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = os.getenv("MONGO_PORT")
if MONGO_PORT:  # Assumption: A local or remote installation of MongoDB is provided.
    MONGO_PORT = int(MONGO_PORT)
    MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}"
else:  # Assumption: The database is stored in mongodb cloud.
    MONGO_URI = f"mongodb+srv://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}/?retryWrites=true&w=majority&appName=Cluster0"


# client = AsyncIOMotorClient(MONGO_URI)
# db = client.upcast
# contracts_collection = db.contracts
# users_collection = db.users
# negotiations_collection = db.negotiations


def pydantic_to_dict(obj, clean_id=False):
    if isinstance(obj, list):
        return [pydantic_to_dict(item, clean_id) for item in obj]
    if isinstance(obj, dict):
        return {k: pydantic_to_dict(v, clean_id) for k, v in obj.items()}
    if isinstance(obj, BaseModel):
        return pydantic_to_dict(obj.dict(), clean_id)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, ObjectId) and clean_id:
        return str(obj)
    return obj


class MongoObject(BaseModel):
    id: Optional[object] = Field(None, alias="_id")

    @field_validator("id")
    def process_id(cls, value, values):
        if isinstance(value, ObjectId):
            return str(value)
        return value


class ClientOptionalInfo(BaseModel):
    client_pid: Optional[str] = Field(None, alias="negotiation_id" or "consent_id")
    policy_id: Optional[str] = Field(None)
    type: Optional[str] = Field(None)
    updated_at: Optional[datetime] = Field(None)


class UpcastSignatureObject(MongoObject):
    user_id: Optional[str] = None
    user_role: Optional[str] = None
    provider_signature: Optional[str] = None
    consumer_signature: Optional[str] = None
    provider_signature_date: Optional[datetime] = Field(default_factory=datetime.utcnow)
    consumer_signature_date: Optional[datetime] = Field(default_factory=datetime.utcnow)


_client = None
_client_loop = None


def _get_db():
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop or (_client_loop and _client_loop.is_closed()):
        _client = AsyncIOMotorClient(MONGO_URI)
        _client_loop = loop
    return _client.upcast


class ContractAPIService():
    def __init__(self):
        self.base_api_url = f"{API_CONTRACT_SERVICE_URL}/contract/"
        self.endpoint_url = ""

    def _build_auth_headers(self, access_token: Optional[str], extra_headers: Optional[Dict[str, str]] = None):
        # Old code sent only custom headers/content-type to contract-service.
        # New code forwards the same bearer token received by the caller.
        headers = dict(extra_headers or {})
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        return headers

    def _raise_contract_service_error(self, exc: requests.exceptions.RequestException):
        # Old code returned only the generic requests exception text, which hid
        # the detail payload returned by contract-service on 4xx/5xx responses.
        # Keep the upstream body when available so debugging the real backend
        # failure is straightforward from Negotiation-Tool logs and responses.
        detail = f"Error calling agreement API: {exc}"
        response = getattr(exc, "response", None)
        if response is not None:
            response_body = ""
            try:
                response_body = response.text.strip()
            except Exception:
                response_body = ""
            if response_body:
                detail = f"{detail}. Contract service response: {response_body}"
        raise HTTPException(status_code=502, detail=detail)

    @property
    def contracts_collection(self):
        return _get_db().contracts

    @property
    def users_collection(self):
        return _get_db().users

    @property
    def negotiations_collection(self):
        return _get_db().negotiations

    # varify the user and negotiation
    async def _varify_user_and_negotiation(self,
                                           user_id: str,
                                           negotiation_id: str
                                           ):
        """
        Load & validate user and, if provided, negotiation.
        Raises HTTPException on error.
        Returns: (user, negotiation or None)
        """
        try:
            uid = ObjectId(user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid user_id format")
        user = await self.users_collection.find_one({"_id": uid})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # validate & load negotiation
        try:
            nid = ObjectId(negotiation_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid negotiation_id format")

        negotiation = await self.negotiations_collection.find_one(
            {
                "_id": nid,
                "$or": [
                    {"consumer_id": uid},
                    {"provider_id": uid},
                    {"producer_id": uid},
                ],
            }
        )
        if not negotiation:
            raise HTTPException(status_code=404, detail="Negotiation not found")

        return user, negotiation

    # varify the user and negotiation
    async def _verify_user(self, user_id: str):

        try:
            uid = ObjectId(user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid user_id format")
        user = await self.users_collection.find_one({"_id": uid})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return user

    async def _varify_negotiation(self, negotiation_id: str):
        """
        Load & validate negotiation.
        Raises HTTPException on error.
        Returns: (user, negotiation or None)
        """
        # validate & load negotiation
        try:
            nid = ObjectId(negotiation_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid negotiation_id format")

        negotiation = await self.negotiations_collection.find_one({"_id": nid, })
        if not negotiation:
            raise HTTPException(status_code=404, detail="Negotiation not found")

        return negotiation

    # update negotiation_id on an existing agreement document
    async def insert_negotiation_id_into_contract_collection(self, contract_id, negotiation_id):

        if not contract_id or not negotiation_id:
            raise HTTPException(status_code=400, detail="Both agreement_id and negotiation_id must be provided")

        try:
            cid = ObjectId(contract_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid agreement_id format")

        # 4. Perform the update
        result = await self.contracts_collection.update_one(
            {"_id": cid},
            {"$set": {"negotiation_id": negotiation_id}}
        )

        # 5. Handle not found
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Agreement not found")

        return {"updated": result.modified_count}

    # generate legal agreement by calling external API and verifying user
    def create_contract(self, user_id: str, json_data: dict, access_token: Optional[str] = None):

        self.endpoint_url = f"{self.base_api_url}create"
        # Old code:
        # headers = {
        #     "user-id": user_id,
        #     "Content-Type": "application/json",
        # }
        headers = self._build_auth_headers(access_token, {
            "user-id": user_id,
            "Content-Type": "application/json",
        })

        try:
            response = requests.post(
                self.endpoint_url,
                json=json_data,
                headers=headers,
                timeout=30.0
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self._raise_contract_service_error(e)

        result = response.json()
        # inject generated natural language document
        json_data["natural_language_document"] = result.get('legal_contract')
        json_data["contract_id"] = result.get('contract_id')
        return json_data

    def update_contract(self, contract_id: str, json_data: dict, access_token: Optional[str] = None):

        print("update contract", contract_id, json_data.keys())
        self.endpoint_url = f"{self.base_api_url}update/{contract_id}"
        headers = self._build_auth_headers(access_token, {
            "Content-Type": "application/json",
        })

        try:
            response = requests.put(
                self.endpoint_url,
                json=json_data,
                headers=headers,
                timeout=10.0
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self._raise_contract_service_error(e)

        return response.json()

    def _get_contract(self, contract_id, access_token: Optional[str] = None):
        self.endpoint_url = f"{self.base_api_url}get_contract/{contract_id}"
        headers = self._build_auth_headers(access_token, {
            "contract_id": contract_id,
            "Content-Type": "application/json",
        })

        try:
            response = requests.get(
                self.endpoint_url,
                headers=headers,
                timeout=5.0
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self._raise_contract_service_error(e)

        return response.json()

    async def get_contract(self, user_id, negotiation_id, contract_index=-1, access_token: Optional[str] = None):
        # get a contract with respect a negotiation
        # verify user exists (no negotiation required)

        """
        Fetch a contract using 1-based indexing for positive indices (1=first contract),
        and standard Python negative indexing for negative indices (-1=last contract).
        Returns the contract, or None if the index is out of range or no contracts exist.
        """
        logger.info(
            "Fetching contract for user_id=%s, negotiation_id=%s, contract_index=%s",
            user_id, negotiation_id, contract_index
        )

        user, negotiation = await self._varify_user_and_negotiation(user_id, negotiation_id)

        contracts = negotiation.get("negotiation_contracts", [])
        num_contracts = len(contracts)

        if num_contracts == 0:
            logger.warning("No contracts found for negotiation_id=%s", negotiation_id)
            return None  # Or raise an appropriate exception

        # 1-based indexing for positive indices
        if contract_index > 0:
            index = contract_index - 1
        else:
            # negative indices remain as is
            index = contract_index

        # Check index validity
        if index < 0:
            index += num_contracts
        if index < 0 or index >= num_contracts:
            logger.error(
                "Invalid contract_index=%s for negotiation_id=%s (number of contracts: %s)",
                contract_index, negotiation_id, num_contracts
            )
            return None  # Or raise an appropriate exception

        contract_id = str(contracts[index])
        logger.info("Selected contract_id %s", contract_id)

        res = self._get_contract(contract_id, access_token=access_token)
        return res

    async def get_related_contracts(self, related_id: str, access_token: Optional[str] = None):

        # get all contract with respect a user or a negotiation
        # 1. verfy the related_id is a user_id or negotiation_id
        # 2. if it is a negotiation_id, get negotiation_contracts
        # 3. get a list of contract ids, to call self.endpoint_url = f"{self.base_api_url}/contract_list"
        # or
        # 2. if the related_id is a user_id, get related negotiations, then for each negotiation, get final contract in the list of negotiation_contracts
        #
        # 3. get a list of contract ids, to call self.endpoint_url = f"{self.base_api_url}/contract_list"

        logger.info("Fetching related contracts for id=%s", related_id)

        # 1) Validate related_id
        try:
            rid = ObjectId(related_id)
        except Exception:
            logger.error("Invalid related_id format: %s", related_id)
            raise HTTPException(status_code=400, detail="Invalid related_id format")

        # 2) Gather contract_ids
        contract_ids = []
        negotiation = await self.negotiations_collection.find_one({"_id": rid})
        if negotiation:
            logger.info("Found negotiation %s; extracting contracts", related_id)
            raw = negotiation.get("negotiation_contracts", [])
            contract_ids = [str(c) for c in raw]
        else:
            user = await self.users_collection.find_one({"_id": rid})
            if not user:
                logger.warning("No negotiation or user found for id %s", related_id)
                raise HTTPException(status_code=404, detail="Related resource not found")

            cursor = self.negotiations_collection.find({
                "$or": [{"consumer_id": rid},
                        {"provider_id": rid},
                        {"producer_id": rid}]
            })
            async for neg in cursor:
                raw = neg.get("negotiation_contracts", [])
                if raw:
                    contract_ids.append(str(raw[-1]))
            logger.info("User %s has %d related contracts", related_id, len(contract_ids))

        if not contract_ids:
            logger.info("No contracts to fetch for %s", related_id)
            return []

        # 3) Call the FastAPI endpoint
        res_contract_list = []
        for contract_id in contract_ids:
            _res = self._get_contract(contract_id, access_token=access_token)
            logger.info(f"\n{contract_id} : {_res}")
            res_contract_list.append(_res)

        logger.info(f"Found {len(res_contract_list)} related contracts")

        return res_contract_list

    async def sign_contract(self, negotiation_id: str, dataform: dict, access_token: Optional[str] = None):
        negotiation = await self._varify_negotiation(negotiation_id)

        if len(negotiation.get("negotiation_contracts", [])) == 0:
            print("no contract available, do not need to save into contract document")
            return {
                "message": "no contract available, do not need to save into contract document",
                "contract_id": "",
            }

        else:
            contract_id = str(negotiation.get("negotiation_contracts", [])[-1])

        print("contract_id", contract_id)
        print("dataform", dataform)

        self.endpoint_url = f"{self.base_api_url}sign_contract/{contract_id}"
        async with httpx.AsyncClient() as client:
            headers = self._build_auth_headers(access_token, {"Content-Type": "application/json"})
            resp = await client.put(self.endpoint_url, json=dataform, headers=headers,
                                    timeout=5.0)
            resp.raise_for_status()
            return resp.json()

    async def get_last_contract(self, user_id, negotiation_id):

        logger.info("Fetching contract for user_id=%s, negotiation_id=%s", user_id, negotiation_id)

        user, negotiation = await self._varify_user_and_negotiation(user_id, negotiation_id)

        contract_id = str(negotiation.get("negotiation_contracts", [])[-1])

        logger.info("contract_id %s", contract_id)

    async def get_contract_diff(self, user_id, negotiation_id, first_index=-1, second_index=-2,
                                access_token: Optional[str] = None):

        # obtain two contracts
        user, negotiation = await self._varify_user_and_negotiation(user_id, negotiation_id)

        contract_ids = negotiation.get("negotiation_contracts", [])
        print("contract_ids", contract_ids)

        if len(contract_ids) < 2:
            raise HTTPException(
                status_code=400,
                detail="Need at least two contracts to compute a diff"
            )

            # 3. Convert ObjectIds (or whatever) to strings
        str_ids = [str(cid) for cid in contract_ids]

        # a test example in my mongodb
        first_contract_id = str_ids[first_index]
        headers = self._build_auth_headers(access_token, {
            "Content-Type": "application/json",
            "first-contract-id": first_contract_id,
            "second-contract-id": str_ids[second_index]
        })

        self.endpoint_url = f"{self.base_api_url}get_diffs"
        resp = requests.get(self.endpoint_url, headers=headers)

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # Bubble up meaningful errors
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Error from contract-diff endpoint: {e.response.text}"
            )

        # 5. Return the parsed JSON diff
        return resp.json()

    async def down_contract(self, user_id, negotiation_id, access_token: Optional[str] = None):
        logger.info("Fetching contract for user_id=%s, negotiation_id=%s", user_id, negotiation_id)

        user, negotiation = await self._varify_user_and_negotiation(user_id, negotiation_id)

        contract_id = str(negotiation.get("negotiation_contracts", [])[-1])

        logger.info("contract_id %s", contract_id)

        # prepare API request
        self.endpoint_url = f"{self.base_api_url}download/{contract_id}"
        async with httpx.AsyncClient() as client:
            headers = self._build_auth_headers(access_token)
            resp = await client.get(self.endpoint_url, headers=headers, timeout=10.0)
            resp.raise_for_status()
            return resp.content

    async def delete_contract(self, user_id, negotiation_id, access_token: Optional[str] = None):

        logger.info("Fetching contract for user_id=%s, negotiation_id=%s", user_id, negotiation_id)

        user, negotiation = await self._varify_user_and_negotiation(user_id, negotiation_id)

        contract_id = str(negotiation.get("negotiation_contracts", [])[-1])

        # delete the contract_id from negotiation
        await self.negotiations_collection.update_one(
            {"_id": ObjectId(negotiation_id)},
            {"$pull": {"negotiation_contracts": ObjectId(contract_id)}}
        )

        logger.info("contract_id %s", contract_id)
        self.endpoint_url = f"{self.base_api_url}delete_contract/{contract_id}"
        headers = self._build_auth_headers(access_token)
        res = requests.delete(self.endpoint_url, headers=headers)
        res.raise_for_status()
        return res.json()

    def get_des_by_odrl_translation(self, odrl_dic):

        """
        Aiming to translate the ODRL rules to natural language  into a list of dictionaries
        Also, get definitions of vocabulary, which are included in the ODRL rules

        Call /odrl_translation with a JSON body and return:
        {
            "odrl_des" = {"key":"value", },
            "definitions" = {
                "permission": [],
                "prohibition": [],
                "obligation": [],
                "duty": []
            }
        }
        """

        self.endpoint_url = f"{self.base_api_url}odrl_translation"

        try:
            response = requests.get(
                self.endpoint_url,
                json=odrl_dic,
                timeout=5.0
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error calling agreement API: {e}"
            )

        # Validate JSON shape
        try:
            data = response.json()
        except ValueError:
            raise HTTPException(status_code=502, detail="Agreement API returned non-JSON response.")

        if not isinstance(data, dict) or "definitions" not in data or "odrl_des" not in data:
            raise HTTPException(
                status_code=502,
                detail="Agreement API returned unexpected payload; expected keys: 'definitions' and 'odrl_des'."
            )

        return data

    def get_text_diffs(self, text1, text2, normalize_unicode: bool = True):

        payload = {
            "first_text": text1 or "",
            "second_text": text2 or "",
            "normalize_unicode": normalize_unicode
        }

        # matches: @app.post("/contract/get_text_diffs", ...)
        self.endpoint_url = f"{self.base_api_url}get_text_diffs"

        try:
            resp = requests.post(  # <-- POST, not GET
                self.endpoint_url,
                json=payload,  # send JSON body
                timeout=10.0  # give it a touch more time if diffs get big
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise HTTPException(status_code=502, detail=f"Error calling agreement API: {e}")

        # Parse JSON
        try:
            data = resp.json()
        except ValueError:
            raise HTTPException(status_code=502, detail="Agreement API returned non-JSON response.")

        # Validate expected keys from TextDiffResponse
        expected_keys = {"diff_html", "change_segments", "changes", "stats"}
        if not isinstance(data, dict) or not expected_keys.issubset(data.keys()):
            raise HTTPException(
                status_code=502,
                detail=f"Agreement API returned unexpected payload; expected keys: {sorted(expected_keys)}."
            )

        # The HTML already includes your legend + diff snippet per server code.
        print(data.get("diff_html"))
        return data


async def main():
    service = ContractAPIService()
    # """ get a contract """
    # user_id = "67ee4911c118465adf6df279"
    # negotiation_id = "687502566ed9051d525e5ab3"
    # res = await  service.get_contract(user_id, negotiation_id)
    # print("Final result:", res)

    # """ get a set of contract with respect to a user or negotiation """
    # user_id = "67ee4911c118465adf6df279"
    # negotiation_id = "687502566ed9051d525e5ab3"
    # res = await service.get_related_contracts(related_id=negotiation_id)
    # print("Final result:", res)

    # sign a contract
    # signature_data = "hjkfahkldjflkdjlkajklfd"
    # user_role = "consumer"
    # dataform = {
    #     f"user_id": "68821fc7eeea3fe76612e027",
    #     f"user_role": "consumer",
    #     f"{user_role}_signature": signature_data,
    #     f"{user_role}_signature_date": str(datetime.utcnow()),
    # }
    #
    # nid = "68878723a62982a292b58246"
    # res = await service.sign_contract(nid, dataform)
    # print(res)

    # download a contract
    # negotiation_id = "68779068039f4b87391e549e"
    # user_mongo_id = "67ee4911c118465adf6df279"
    # # 1. fetch the PDF bytes
    # pdf_bytes = await service.down_contract(user_mongo_id, negotiation_id)
    # # 2. choose a path & filename
    # filename = f"contract_{negotiation_id}.pdf"
    # filepath = f"../demo_src/{filename}"
    #
    # # 3. write to disk
    # with open(filepath, "wb") as f:
    #     f.write(pdf_bytes)
    #
    # print(f"Saved PDF to {filepath}")

    # # get difference
    negotiation_id = "68878520a62982a292b58241"
    user_mongo_id = "68821fc7eeea3fe76612e027"
    res = await service.get_contract_diff(user_id=user_mongo_id, negotiation_id=negotiation_id)
    print("res", res)


if __name__ == "__main__":
    asyncio.run(main())
