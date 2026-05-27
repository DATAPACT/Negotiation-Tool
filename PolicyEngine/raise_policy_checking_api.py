import json

import rdflib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Union
from motor.motor_asyncio import AsyncIOMotorClient
from rdflib import Graph, BNode
from rdflib.namespace import Namespace
from rdflib.plugins.sparql import prepareQuery

app = FastAPI()

# Define the namespaces
ODRL = Namespace("http://www.w3.org/ns/odrl/2/")
DPV = Namespace("https://w3id.org/dpv/owl#")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")


# MongoDB connection setup
user = "semih"
password = "a8Spt66DKqGh2V0T"
host = "cluster0.btnpvyy.mongodb.net"
MONGO_DETAILS = f"mongodb+srv://{user}:{password}@{host}/?retryWrites=true&w=majority&appName=Cluster0"

client = AsyncIOMotorClient(MONGO_DETAILS)
db = client['policy_database']
collection = db['policies']

# Define the SPARQL query to find matching nodes
sparql_query = """
PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
PREFIX dpv: <https://w3id.org/dpv/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?action ?assignee ?target_source ?purpose 
WHERE {
  ?node odrl:action ?action ;
        odrl:assignee ?assignee ;
        odrl:target ?target ;
        odrl:constraint ?constraint .
        ?constraint odrl:leftOperand odrl:purpose ;
                    odrl:operator odrl:eq ;
                    odrl:rightOperand ?purpose .
        ?target odrl:source ?target_source.
}
"""

example_permission_policy = request_policy= {
    "permission": [
        {
            "action": "http://www.w3.org/ns/odrl/2/appendTo",
            "assignee": "https://w3id.org/dpv/owl#Citizen",
            "target": {
                "source": "http://example.org/datasets/climateChangeData",
                "refinement": [
                    {
                        "leftOperand": "http://example.org/datasets/title",
                        "operator": "http://www.w3.org/ns/odrl/2/eq",
                        "rightOperand": "6"
                    }
                ]
            },
            "constraint": [
                {
                    "leftOperand": "purpose",
                    "operator": "http://www.w3.org/ns/odrl/2/eq",
                    "rightOperand": "https://w3id.org/dpv/owl#Personalisation"
                }
            ]
        }
    ],
    "uid": "http://example.org/policy-79f7e6ba-daff-4919-940f-a1ad1344a97b",
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "http://www.w3.org/ns/odrl/2/Policy"
}

example_prohibition_policy = {
    "prohibition": [
        {
            "action": "http://www.w3.org/ns/odrl/2/appendTo",
            "assignee": "https://w3id.org/dpv/owl#Citizen",
            "target": {
                "source": "http://example.org/datasets/climateChangeData",
                "refinement": [
                    {
                        "leftOperand": "http://example.org/datasets/title",
                        "operator": "http://www.w3.org/ns/odrl/2/eq",
                        "rightOperand": "6"
                    }
                ]
            },
            "constraint": [
                {
                    "leftOperand": "purpose",
                    "operator": "http://www.w3.org/ns/odrl/2/eq",
                    "rightOperand": "https://w3id.org/dpv/owl#Personalisation"
                }
            ]
        }
    ],
    "uid": "http://example.org/policy-79f7e6ba-daff-4919-940f-a1ad1344a97a",
    "@context": "http://www.w3.org/ns/odrl.jsonld",
    "@type": "http://www.w3.org/ns/odrl/2/Policy"
}

class Policy(BaseModel):
    odrl_policy: Dict = Field(
        ...,
        example=example_prohibition_policy
    )

class RequestPolicy(BaseModel):
    dataset_id: str = Field(
        ...,
        example="example_dataset_id"
    )
    request_odrl_policy: Dict = Field(
        ...,
        example=example_permission_policy
    )

class ConflictReport(BaseModel):
    conflict_details: Union[Dict, str] = Field(..., example="No conflicts")


# Endpoint: /get_policy/{dataset_id}
@app.get("/get_policy/{dataset_id}", response_model=Policy)
async def get_policy(dataset_id: str):
    """
    Retrieves the ODRL policy for a specific dataset ID from the policies database.

    Parameters:
    - dataset_id: Path parameter specifying the ID of the dataset for which the policy needs to be retrieved.

    Returns:
    - Success (200 OK): Returns a JSON object containing the ODRL policy for the specified dataset_id: {"odrl_policy": policies[dataset_id]}

    - Failure (404 Not Found): If the specified dataset_id is not found in the policies database.
      Returns an HTTP 404 error with details: "Policy not found"

    Example Usage:
    ```
    GET /get_policy/example_dataset HTTP/1.1
    ```
    Replace example_dataset with the actual dataset ID to retrieve its policy.
    """
    policy = await collection.find_one({"dataset_id": dataset_id})
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    return {"odrl_policy": policy["odrl_policy"]}

# Endpoint: /set_policy/{dataset_id}
@app.post("/set_policy/{dataset_id}", status_code=201)
async def set_policy(dataset_id: str, policy: Policy):
    """
    Sets or updates the ODRL policy for a specific dataset ID in the policies database.

    Parameters:
    - dataset_id: Path parameter specifying the ID of the dataset for which the policy is to be set.
    - policy: Request body containing the new ODRL policy to be set for the dataset.

    Returns:
    - Success (201 Created): Returns a JSON object with a success message indicating the policy was set successfully: {"message": "Policy set successfully"}

    Example Usage:
    ```
    POST /set_policy/example_dataset HTTP/1.1
    Content-Type: application/json

    {
      "odrl_policy": {...}
    }
    ```
    Replace example_dataset with the actual dataset ID and provide the appropriate odrl_policy details in the request body.
    """
    await collection.update_one(
        {"dataset_id": dataset_id},
        {"$set": {"odrl_policy": policy.odrl_policy}},
        upsert=True
    )
    return {"message": "Policy set successfully"}

# Endpoint: /remove_policy/{dataset_id}
@app.delete("/remove_policy/{dataset_id}")
async def remove_policy(dataset_id: str):
    """
    Removes the ODRL policy for a specific dataset ID from the policies database.

    Parameters:
    - dataset_id: Path parameter specifying the ID of the dataset for which the policy is to be removed.

    Returns:
    - Success (200 OK): Returns a JSON object with a success message indicating the policy was removed successfully: {"message": "Policy removed successfully"}

    - Failure (404 Not Found): If the specified dataset_id is not found in the policies database.
      Returns an HTTP 404 error with details: "Policy not found"

    Example Usage:
    ```
    DELETE /remove_policy/example_dataset HTTP/1.1
    ```
    Replace example_dataset with the actual dataset ID to remove its policy.
    """
    result = await collection.delete_one({"dataset_id": dataset_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Policy not found")
    return {"message": "Policy removed successfully"}

@app.post("/validate_access_request", response_model=ConflictReport)
async def validate_access_request(request_policy: RequestPolicy):
    """
    Validates an access request against existing policies for a dataset using ODRL (Open Digital Rights Language).

    Parameters:
    - request_policy: Request body containing the requested policy details  (odrl_policy) and the existing dataset_id
    to validate against existing dataset policy.

    Returns:
    - Success (200 OK): Access granted if no conflicts are found between the request policy and existing dataset policies.
      Returns a JSON object with a success message: {"message": "Access granted"}

    - Failure (404 Not Found): If the specified dataset_id is not found in the policies database.
      Returns an HTTP 404 error with details: "Policy not found"

    - Conflict (200 OK with ConflictReport): If the request policy conflicts with an existing policy for the dataset.
      Returns a JSON object with conflict details: {"conflict_details": "Request policy conflicts with existing policy"}
    """
    policy = await collection.find_one({"dataset_id": request_policy.dataset_id})
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")

    existing_policy_graph = policy_to_graph(policy["odrl_policy"])
    request_policy_graph = policy_to_graph(request_policy.request_odrl_policy)

    conflict_message = check_policy_conflict(existing_policy_graph, request_policy_graph)
    matching_nodes = find_matching_nodes(existing_policy_graph, request_policy_graph)
    print(matching_nodes)
    # if conflict_message:
    #     return {"conflict_details": conflict_message}
    # return {"message": "Access granted"}
    if bool(matching_nodes):
        return ConflictReport(conflict_details=matching_nodes)
    return ConflictReport(conflict_details="No conflicts")

def policy_to_graph(policy: Dict) -> Graph:
    graph = Graph()
    graph.parse(data=json.dumps(policy), format="json-ld")
    return graph



def find_matching_nodes(existing_policy: Graph, request_policy: Graph) -> bool:
    """
    Find matching nodes between existing and request policies using SPARQL.

    Parameters:
    - existing_policy: RDF graph representing the existing policy (prohibition).
    - request_policy: RDF graph representing the request policy (permission).

    Returns:
    - Boolean indicating if there are matching nodes between the two policies.
    """


    # Prepare the SPARQL query
    query = prepareQuery(sparql_query, initNs={"odrl": ODRL, "dpv": DPV, "rdfs": RDFS})

    # Execute the query on the existing and request policies
    existing_results = set(existing_policy.query(query))
    request_results = set(request_policy.query(query))

    # Extract non-BNode parts of the results for comparison
    def extract_non_bnode_parts(rdf_set):
        return {node for node in rdf_set if not isinstance(node, rdflib.term.BNode)}

    # Extract non-blank nodes
    existing_non_blank_nodes = extract_non_bnode_parts(existing_results)
    request_non_blank_nodes = extract_non_bnode_parts(request_results)

    existing_non_bnode_parts = extract_non_bnode_parts(existing_results)
    request_non_bnode_parts = extract_non_bnode_parts(request_results)
    # Find matching nodes
    matching_nodes = existing_non_blank_nodes.intersection(request_non_blank_nodes)
    # Debug output
    print("Existing Results (non-BNode parts):", existing_non_bnode_parts)
    print("Request Results (non-BNode parts):", request_non_bnode_parts)
    print("Matching Nodes:", matching_nodes)

    # Return whether there are any matching nodes
    if bool(matching_nodes):
        conflicts = []
        for matching_node in matching_nodes:
            conflicts.append({
                'action': matching_node[0],
                'assignee': matching_node[1],
                'target_source': matching_node[2],
                'purpose': matching_node[3]
            })
        return {"conflicts" : matching_nodes}
    else:
        return

def find_matching_nodes2(existing_policy: Graph, request_policy: Graph) -> bool:
    """
    Find matching nodes between existing and request policies using SPARQL.

    Parameters:
    - existing_policy: RDF graph representing the existing policy (prohibition).
    - request_policy: RDF graph representing the request policy (permission).

    Returns:
    - Boolean indicating if there are matching nodes between the two policies.
    """
    # Define the SPARQL query to find matching nodes
    sparql_query = """
    PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
    PREFIX dpv: <https://w3id.org/dpv/owl#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?action ?assignee ?target ?constraint 
    WHERE {
      {
        ?node odrl:action ?action ;
              odrl:assignee ?assignee ;
              odrl:target ?target ;
              odrl:constraint ?constraint .
      }
     
    }
    """

    # Prepare the SPARQL query
    query = prepareQuery(sparql_query, initNs={"odrl": ODRL, "dpv": DPV, "rdfs": RDFS})

    # Execute the query on the existing and request policies
    existing_results = set(existing_policy.query(query))
    request_results = set(request_policy.query(query))

    # Find matching nodes
    matching_nodes = existing_results.intersection(request_results)

    return matching_nodes

def check_policy_conflict(existing_policy: Graph, request_policy: Graph) -> Union[None, str]:
    """
    Checks for conflicts between existing and request policies using SPARQL.

    Parameters:
    - existing_policy: RDF graph representing the existing policy (prohibition).
    - request_policy: RDF graph representing the request policy (permission).

    Returns:
    - Conflict message if conflicts are found, None otherwise.
    """
    # Define the SPARQL query
    sparql_query = """
    PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
    PREFIX dpv: <https://w3id.org/dpv/owl#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?policy ?conflictingPolicy
    WHERE {
      ?policy a odrl:Policy ;
              odrl:permission ?permission .
      ?permission odrl:action ?action ;
                  odrl:target ?target ;
                  odrl:constraint ?constraint .

      ?conflictingPolicy a odrl:Policy ;
                         odrl:prohibition ?prohibition .
      ?prohibition odrl:action ?prohibitionAction ;
                   odrl:target ?target ;
                   odrl:constraint ?constraint .

    }
    """

    # Prepare the SPARQL query
    query = prepareQuery(sparql_query, initNs={"odrl": ODRL, "dpv": DPV, "rdfs": RDFS})

    # Execute the query on the existing and request policies
    results = existing_policy.query(query, initBindings={'permission': request_policy})

    # Process results to determine conflicts
    for row in results:
        return f"Conflict detected between policy {row.policy} and conflicting policy {row.conflictingPolicy}"

    return None

def check_policy_conflict_2(existing_policy: Dict, request_policy: Dict) -> Union[None, str]:
    """
    Compares the existing policy (prohibition) and the request policy (permission)
    to determine if there is a conflict. Returns a conflict message if there is a conflict.
    """
    # Convert policies to RDF
    existing_graph = convert_to_rdf(existing_policy)
    request_graph = convert_to_rdf(request_policy)

    # Define the SPARQL query to check for conflicts
    sparql_query = """
    PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
    PREFIX dpv: <https://w3id.org/dpv/owl#>

    SELECT ?action ?assignee ?target ?purpose
    WHERE {
        ?proh odrl:action ?action ;
              odrl:assignee ?assignee ;
              odrl:target ?target ;
              odrl:constraint ?constraint .
        ?constraint odrl:leftOperand "purpose" ;
                    odrl:operator odrl:eq ;
                    odrl:rightOperand ?purpose .

        ?perm odrl:action ?action ;
              odrl:assignee ?assignee ;
              odrl:target ?target ;
              odrl:constraint ?req_constraint .
        ?req_constraint odrl:leftOperand "purpose" ;
                        odrl:operator odrl:eq ;
                        odrl:rightOperand ?purpose .
    }
    """

    # Check for conflicts using SPARQL
    conflict_results = existing_graph.query(sparql_query, initBindings={'perm': request_graph})

    if conflict_results:
        conflict_message = "Conflicts detected for actions, assignees, and targets with purposes: "
        for row in conflict_results:
            conflict_message += f"Action: {row.action}, Assignee: {row.assignee}, Target: {row.target}, Purpose: {row.purpose}. "
        return conflict_message
    return None

def convert_to_rdf(policy: Dict) -> Graph:
    """
    Converts the given policy dictionary to an RDF graph.
    """
    g = Graph()
    g.parse(data=policy, format="json-ld")
    return g
# To run the app, use: uvicorn filename:app --reload
