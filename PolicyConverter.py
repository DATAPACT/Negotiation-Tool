from typing import Dict, Optional, List, Any, Union
from datetime import datetime
import uuid

from bson import ObjectId
from rdflib import Graph, URIRef
import json
import logging

logger = logging.getLogger(__name__)


class UpcastPolicyConverter:
    """
    Class for converting JSON-LD data in UPCAST format to Upcast policy objects.

    This converter takes JSON-LD data that follows the UPCAST vocabulary and
    transforms it into a structured Upcast policy object with resource descriptions
    and ODRL policies.
    """

    def __init__(self, graph: Optional[Graph] = None, json_object: Optional[Dict] = None):
        """
        Initialize the converter with an optional RDF graph.

        Args:
            graph: An optional RDF graph containing JSON-LD data
        """
        self.graph = graph
        self.json_object = json_object

    def set_graph(self, graph: Graph) -> None:
        """
        Set the RDF graph to use for conversion.

        Args:
            graph: The RDF graph to use
        """
        self.graph = graph

    def convert_from_json_ld(self, json_ld_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert JSON-LD data directly to an Upcast policy object.

        Args:
            json_ld_data: The JSON-LD data as a dictionary

        Returns:
            A dictionary representing an Upcast policy object
        """
        # Create a new graph and parse the JSON-LD data
        g = Graph()
        g.parse(data=json.dumps(json_ld_data), format='json-ld')
        self.set_graph(g)

        return self.convert_to_policy()

    def convert_to_policy(self) -> Dict[str, Any]:
        """
        Convert the current RDF graph to an Upcast policy object.

        Returns:
            A dictionary representing an Upcast policy object

        Raises:
            ValueError: If no graph is available for conversion
        """
        if not self.graph:
            raise ValueError("No graph available for conversion. Set a graph first.")

        # Extract resource description data
        resource_description = self._extract_resource_description()

        # Extract ODRL policy - use actual policy if available, otherwise use default
        dataset_info = self._extract_dataset_info()
        policy_uri = self._get_policy_uri(dataset_info.get("id"))

        odrl_policy = self._extract_odrl_policy(policy_uri) if policy_uri else self._create_default_odrl_policy()

        # Create a base policy object
        policy_object = {
            "id": str(uuid.uuid4()),
            "title": dataset_info.get("title", "Untitled Policy"),
            "type": "offer",  # Default type, adjust based on policy if found
            "consumer_id": None,  # Usually set during negotiation
            "provider_id": ObjectId(dataset_info.get("contactPoint")),
            "data_processing_workflow_object": self._create_default_workflow(),
            "natural_language_document": self._generate_natural_language_description(dataset_info),
            "resource_description_object": resource_description,
            "odrl_policy": odrl_policy,
            "negotiation_id": None,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }

        return policy_object

    def _extract_resource_description(self) -> Dict[str, Any]:
        """
        Extract resource description data from the RDF graph.

        Returns:
            A dictionary representing an UpcastResourceDescriptionObject
        """
        # Extract dataset information with UPCAST-specific fields
        dataset_info = self._extract_dataset_info()

        # Extract distribution information
        distribution_info = self._extract_distribution_info()

        # Extract themes
        themes = self._extract_themes(dataset_info.get("id"))

        # Combine into resource description
        resource_description = {
            "title": dataset_info.get("title"),
            "price": dataset_info.get("price", 0.0),  # Extract price from upcast:price if available
            "price_unit": dataset_info.get("priceUnit", "EUR"),  # Extract price unit from upcast:priceUnit
            "uri": dataset_info.get("id"),
            "policy_url": self._get_policy_uri(dataset_info.get("id")),
            "environmental_cost_of_generation": {},  # To be populated if available
            "environmental_cost_of_serving": {},  # To be populated if available
            "description": dataset_info.get("description"),
            "type_of_data": themes[0] if themes else None,  # Use first theme as type if available
            "data_format": distribution_info.get("format") if distribution_info else None,
            "data_size": str(
                distribution_info.get("byteSize")) if distribution_info and "byteSize" in distribution_info else None,
            "geographic_scope": dataset_info.get("spatial"),
            "tags": ", ".join(themes) if themes else None,  # Join themes as tags
            "publisher": dataset_info.get("publisher"),
            "theme": themes,
            "distribution": self._create_distribution_dict(distribution_info) if distribution_info else None,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "raw_object": self._serialize_graph_to_dict()
        }

        return resource_description

    def _extract_dataset_info(self) -> Dict[str, Any]:
        """
        Extract dataset information from the RDF graph including UPCAST-specific fields.

        Returns:
            A dictionary containing dataset metadata
        """
        dataset_info = {}

        query = """
            PREFIX dcat: <http://www.w3.org/ns/dcat#>
            PREFIX dct: <http://purl.org/dc/terms/>
            PREFIX upcast: <https://www.upcast-project.eu/upcast-vocab/1.0/>

            SELECT ?dataset ?title ?description ?spatial ?publisher ?creator ?price ?priceUnit ?contactPoint
            WHERE {
                ?dataset a dcat:Dataset .
                OPTIONAL { ?dataset dct:title ?title }
                OPTIONAL { ?dataset dct:description ?description }
                OPTIONAL { ?dataset dct:spatial ?spatial }
                OPTIONAL { ?dataset dct:publisher ?publisher }
                OPTIONAL { ?dataset dct:creator ?creator }
                OPTIONAL { ?dataset upcast:price ?price }
                OPTIONAL { ?dataset upcast:priceUnit ?priceUnit }
                OPTIONAL { ?dataset dcat:contactPoint ?contactPoint }
            }
            LIMIT 1
        """

        results = self.graph.query(query)
        for row in results:
            dataset_info = {
                "id": str(row.dataset) if row.dataset else None,
                "title": str(row.title) if row.title else None,
                "description": str(row.description) if row.description else None,
                "spatial": str(row.spatial) if row.spatial else None,
                "publisher": str(row.publisher) if row.publisher else None,
                "contactPoint": str(row.contactPoint) if row.contactPoint else None,
                "creator": str(row.creator) if row.creator else None,
                "price": float(row.price) if row.price else 0.0,
                "priceUnit": str(row.priceUnit) if row.priceUnit else "EUR"
            }

        return dataset_info

    def _extract_themes(self, dataset_uri: Optional[str]) -> List[str]:
        """
        Extract themes for a dataset.

        Args:
            dataset_uri: The URI of the dataset

        Returns:
            A list of theme strings
        """
        if not dataset_uri:
            return []

        themes = []

        query = f"""
            PREFIX dcat: <http://www.w3.org/ns/dcat#>

            SELECT ?theme
            WHERE {{
                <{dataset_uri}> dcat:theme ?theme .
            }}
        """

        results = self.graph.query(query)
        for row in results:
            # Extract theme name from URI
            theme_uri = str(row.theme)
            theme_name = theme_uri.split('/')[-1]
            if ':' in theme_name:
                theme_name = theme_name.split(':')[-1]
            themes.append(theme_name)

        return themes

    def _extract_distribution_info(self) -> Optional[Dict[str, Any]]:
        """
        Extract distribution information from the RDF graph.

        Returns:
            A dictionary containing distribution metadata or None if not found
        """
        distribution_info = None

        query = """
            PREFIX dcat: <http://www.w3.org/ns/dcat#>
            PREFIX dct: <http://purl.org/dc/terms/>

            SELECT ?dist ?title ?description ?format ?byteSize ?mediaType
            WHERE {
                ?dist a dcat:Distribution .
                OPTIONAL { ?dist dct:title ?title }
                OPTIONAL { ?dist dct:description ?description }
                OPTIONAL { ?dist dct:format ?format }
                OPTIONAL { ?dist dcat:byteSize ?byteSize }
                OPTIONAL { ?dist dcat:mediaType ?mediaType }
            }
            LIMIT 1
        """

        results = self.graph.query(query)
        for row in results:
            distribution_info = {
                "id": str(row.dist) if row.dist else None,
                "title": str(row.title) if row.title else None,
                "description": str(row.description) if row.description else None,
                "format": str(row.format) if row.format else None,
                "byteSize": int(row.byteSize) if row.byteSize else None,
                "mediaType": str(row.mediaType) if row.mediaType else None
            }

        return distribution_info

    def _get_policy_uri(self, dataset_uri: Optional[str]) -> Optional[str]:
        """
        Get the policy URI associated with a dataset.

        Args:
            dataset_uri: The URI of the dataset

        Returns:
            The policy URI as a string or None if not found
        """
        if not dataset_uri:
            return None

        query = f"""
            PREFIX odrl: <http://www.w3.org/ns/odrl/2/>

            SELECT ?policy
            WHERE {{
                <{dataset_uri}> odrl:hasPolicy ?policy .
            }}
            LIMIT 1
        """

        results = self.graph.query(query)
        for row in results:
            return str(row.policy) if row.policy else None

        return None


    def _extract_odrl_policy(self, policy_uri: Optional[str]) -> Dict[str, Any]:
        for i in self.json_object.get("@graph"):
            if "Policy" in i.get("@type"):
                return i
        return self._create_default_odrl_policy()
    def _extract_odrl_policy_graph(self, policy_uri: Optional[str]) -> Dict[str, Any]:
        """
        Extract ODRL policy information from the RDF graph using the policy URI.

        Args:
            policy_uri: The URI of the policy

        Returns:
            A dictionary representing the ODRL policy
        """
        if not policy_uri:
            return self._create_default_odrl_policy()

        # Get policy type
        query = f"""
            PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

            SELECT ?type
            WHERE {{
                <{policy_uri}> rdf:type ?type .
            }}
            LIMIT 1
        """

        policy_type = "offer"  # Default
        results = self.graph.query(query)
        for row in results:
            type_uri = str(row.type)
            if "odrl:" in type_uri or "/odrl/" in type_uri:
                policy_type = type_uri.split('/')[-1]
                if ":" in policy_type:
                    policy_type = policy_type.split(':')[-1]

        # Create base policy
        policy = {
            "@context": "http://www.w3.org/ns/odrl.jsonld",
            "@type": policy_type,
            "@id": policy_uri,
            "permission": self._extract_permissions(policy_uri),
            "prohibition": self._extract_prohibitions(policy_uri),
            "obligation": self._extract_obligations(policy_uri)
        }

        # Remove empty arrays
        if not policy["permission"]:
            del policy["permission"]
        if not policy["prohibition"]:
            del policy["prohibition"]
        if not policy["obligation"]:
            del policy["obligation"]

        return policy

    def _extract_permissions(self, policy_uri: str) -> List[Dict[str, Any]]:
        """
        Extract permissions from an ODRL policy.

        Args:
            policy_uri: The URI of the policy

        Returns:
            A list of permission dictionaries
        """
        permissions = []

        query = f"""
            PREFIX odrl: <http://www.w3.org/ns/odrl/2/>

            SELECT ?permission ?action ?target ?assigner ?assignee
            WHERE {{
                <{policy_uri}> odrl:permission ?permission .
                OPTIONAL {{ ?permission odrl:action ?action }}
                OPTIONAL {{ ?permission odrl:target ?target }}
                OPTIONAL {{ ?permission odrl:assigner ?assigner }}
                OPTIONAL {{ ?permission odrl:assignee ?assignee }}
            }}
        """

        results = self.graph.query(query)
        for row in results:
            permission = {}

            # Handle action (could be a direct value or a reference)
            if row.action:
                action_value = self._extract_action_value(row.action)
                permission["action"] = action_value

            if row.target:
                permission["target"] = str(row.target)

            if row.assigner:
                permission["assigner"] = str(row.assigner)

            if row.assignee:
                permission["assignee"] = str(row.assignee)

            # Extract constraints
            constraints = self._extract_constraints(str(row.permission))
            if constraints:
                permission["constraint"] = constraints

            if permission:  # Only add if not empty
                permissions.append(permission)

        return permissions

    def _extract_prohibitions(self, policy_uri: str) -> List[Dict[str, Any]]:
        """
        Extract prohibitions from an ODRL policy.

        Args:
            policy_uri: The URI of the policy

        Returns:
            A list of prohibition dictionaries
        """
        prohibitions = []

        query = f"""
            PREFIX odrl: <http://www.w3.org/ns/odrl/2/>

            SELECT ?prohibition ?action ?target ?assigner ?assignee
            WHERE {{
                <{policy_uri}> odrl:prohibition ?prohibition .
                OPTIONAL {{ ?prohibition odrl:action ?action }}
                OPTIONAL {{ ?prohibition odrl:target ?target }}
                OPTIONAL {{ ?prohibition odrl:assigner ?assigner }}
                OPTIONAL {{ ?prohibition odrl:assignee ?assignee }}
            }}
        """

        results = self.graph.query(query)
        for row in results:
            prohibition = {}

            # Handle action (could be a direct value or a reference)
            if row.action:
                action_value = self._extract_action_value(row.action)
                prohibition["action"] = action_value

            if row.target:
                prohibition["target"] = str(row.target)

            if row.assigner:
                prohibition["assigner"] = str(row.assigner)

            if row.assignee:
                prohibition["assignee"] = str(row.assignee)

            # Extract constraints
            constraints = self._extract_constraints(str(row.prohibition))
            if constraints:
                prohibition["constraint"] = constraints

            if prohibition:  # Only add if not empty
                prohibitions.append(prohibition)

        return prohibitions

    def _extract_obligations(self, policy_uri: str) -> List[Dict[str, Any]]:
        """
        Extract obligations from an ODRL policy.

        Args:
            policy_uri: The URI of the policy

        Returns:
            A list of obligation dictionaries
        """
        obligations = []

        query = f"""
            PREFIX odrl: <http://www.w3.org/ns/odrl/2/>

            SELECT ?obligation ?action ?target ?assigner ?assignee
            WHERE {{
                <{policy_uri}> odrl:obligation ?obligation .
                OPTIONAL {{ ?obligation odrl:action ?action }}
                OPTIONAL {{ ?obligation odrl:target ?target }}
                OPTIONAL {{ ?obligation odrl:assigner ?assigner }}
                OPTIONAL {{ ?obligation odrl:assignee ?assignee }}
            }}
        """

        results = self.graph.query(query)
        for row in results:
            obligation = {}

            # Handle action (could be a direct value or a reference)
            if row.action:
                action_value = self._extract_action_value(row.action)
                obligation["action"] = action_value

            if row.target:
                obligation["target"] = str(row.target)

            if row.assigner:
                obligation["assigner"] = str(row.assigner)

            if row.assignee:
                obligation["assignee"] = str(row.assignee)

            # Extract constraints
            constraints = self._extract_constraints(str(row.obligation))
            if constraints:
                obligation["constraint"] = constraints

            if obligation:  # Only add if not empty
                obligations.append(obligation)

        return obligations

    def _extract_constraints(self, rule_uri: str) -> List[Dict[str, Any]]:
        """
        Extract constraints for a rule.

        Args:
            rule_uri: The URI of the rule

        Returns:
            A list of constraint dictionaries
        """
        constraints = []

        query = f"""
            PREFIX odrl: <http://www.w3.org/ns/odrl/2/>

            SELECT ?constraint ?leftOperand ?operator ?rightOperand ?datatype ?unit
            WHERE {{
                <{rule_uri}> odrl:constraint ?constraint .
                OPTIONAL {{ ?constraint odrl:leftOperand ?leftOperand }}
                OPTIONAL {{ ?constraint odrl:operator ?operator }}
                OPTIONAL {{ ?constraint odrl:rightOperand ?rightOperand }}
                OPTIONAL {{ ?constraint odrl:datatype ?datatype }}
                OPTIONAL {{ ?constraint odrl:unit ?unit }}
            }}
        """

        results = self.graph.query(query)
        for row in results:
            constraint = {}

            if row.leftOperand:
                constraint["leftOperand"] = self._extract_term_value(row.leftOperand)

            if row.operator:
                constraint["operator"] = self._extract_term_value(row.operator)

            if row.rightOperand:
                constraint["rightOperand"] = str(row.rightOperand)

            if row.datatype:
                constraint["datatype"] = str(row.datatype)

            if row.unit:
                constraint["unit"] = str(row.unit)

            if constraint:  # Only add if not empty
                constraints.append(constraint)

        return constraints

    def _extract_action_value(self, action) -> Union[str, Dict[str, str]]:
        """
        Extract the action value, handling both URIs and nested objects.

        Args:
            action: The action URI or node

        Returns:
            Either a string action value or a dict with "@id" for referenced actions
        """
        # Check if action is a URI or a blank node
        if isinstance(action, URIRef):
            # It's a URI, extract the value
            action_uri = str(action)
            if "/odrl/" in action_uri or "odrl:" in action_uri:
                action_name = action_uri.split('/')[-1]
                if ":" in action_name:
                    action_name = action_name.split(':')[-1]
                return action_name
            return {"@id": action_uri}

        # It might be a blank node, try to get its properties
        query = f"""
            PREFIX odrl: <http://www.w3.org/ns/odrl/2/>

            SELECT ?actionId
            WHERE {{
                {action.n3()} odrl:id ?actionId .
            }}
            LIMIT 1
        """

        results = self.graph.query(query)
        for row in results:
            return {"@id": str(row.actionId)}

        # Fallback: return the node's string representation
        return str(action)

    def _extract_term_value(self, term) -> Union[str, Dict[str, str]]:
        """
        Extract a term value, handling both URIs and literals.

        Args:
            term: The term URI or literal

        Returns:
            Either a string term value or a dict with "@id" for referenced terms
        """
        if isinstance(term, URIRef):
            term_uri = str(term)
            if "/odrl/" in term_uri or "odrl:" in term_uri:
                term_name = term_uri.split('/')[-1]
                if ":" in term_name:
                    term_name = term_name.split(':')[-1]
                return term_name
            return {"@id": term_uri}

        # For literals, return the string value
        return str(term)

    def _create_distribution_dict(self, distribution_info: Dict[str, Any]) -> Dict[str, str]:
        """
        Create a distribution dictionary from distribution information.

        Args:
            distribution_info: Dictionary containing distribution metadata

        Returns:
            A dictionary with distribution details formatted for the Upcast policy
        """
        if not distribution_info:
            return {}

        return {
            "format": distribution_info.get("format", ""),
            "mediaType": distribution_info.get("mediaType", ""),
            "url": distribution_info.get("id", "")
        }

    def _create_default_workflow(self) -> Dict[str, Any]:
        """
        Create a default data processing workflow object.

        Returns:
            A dictionary representing a data processing workflow
        """
        return {
            "description": "Default data processing workflow",
            "data_processing_stages": [],
            "processing_purpose": "General data processing"
        }

    def _generate_natural_language_description(self, dataset_info: Dict[str, Any]) -> str:
        """
        Generate a natural language description based on the dataset information.

        Args:
            dataset_info: Dictionary containing dataset metadata

        Returns:
            A human-readable description of the data policy
        """
        if not dataset_info:
            return "Data sharing policy document"

        title = dataset_info.get("title", "Unnamed dataset")
        description = dataset_info.get("description", "No description provided")
        price = dataset_info.get("price", 0.0)
        price_unit = dataset_info.get("priceUnit", "EUR")

        # Extract policy details if available
        policy_uri = self._get_policy_uri(dataset_info.get("id"))
        policy_details = ""

        # if policy_uri:
        #     permissions = self._extract_permissions(policy_uri)
        #     prohibitions = self._extract_prohibitions(policy_uri)
        #
        #     if permissions:
        #         actions = [p.get("action") for p in permissions if p.get("action")]
        #         if actions:
        #             policy_details += f"\nThe data can be used for: {', '.join(actions)}."
        #
        #     if prohibitions:
        #         actions = [p.get("action") for p in prohibitions if p.get("action")]
        #         if actions:
        #             policy_details += f"\nThe data cannot be used for: {', '.join(actions)}."

        return f"""
        This is a data sharing policy for the dataset titled "{title}", which contains data related to {description}.
        The price for accessing this data is {price} {price_unit}.
        {policy_details}

        This policy specifies the terms and conditions under which this data can be accessed and used.
        """

    def _create_default_odrl_policy(self) -> Dict[str, Any]:
        """
        Create a default ODRL policy.

        Returns:
            A dictionary representing an ODRL policy
        """
        return {
            "@context": "http://www.w3.org/ns/odrl.jsonld",
            "@type": "offer",
            "permission": [
                {
                    "action": "use",
                    "constraint": [
                        {
                            "leftOperand": "purpose",
                            "operator": "eq",
                            "rightOperand": "research"
                        }
                    ]
                }
            ],
            "prohibition": [
                {
                    "action": "distribute"
                }
            ],
            "obligation": [
                {
                    "action": "compensate",
                    "target": "data-owner"
                }
            ]
        }

    def _serialize_graph_to_dict(self) -> Dict[str, Any]:
        """
        Serialize the RDF graph back to a dictionary for storage.

        Returns:
            A dictionary representation of the RDF graph in JSON-LD format
        """
        json_ld = self.graph.serialize(format="json-ld", indent=2)
        return json.loads(json_ld)

    def extract_datasets(self) -> List[Dict[str, Any]]:
        """
        Extract dataset information from the RDF graph for API responses.

        Returns:
            A list of dictionaries containing dataset metadata
        """
        datasets = []

        # Query for datasets with UPCAST-specific fields
        query = """
            PREFIX dcat: <http://www.w3.org/ns/dcat#>
            PREFIX dct: <http://purl.org/dc/terms/>
            PREFIX upcast: <https://www.upcast-project.eu/upcast-vocab/1.0/>
            PREFIX idsa-core: <https://w3id.org/idsa/core/>

            SELECT ?dataset ?title ?description ?spatial ?publisher ?creator ?price ?priceUnit ?provider
            WHERE {
                ?dataset a dcat:Dataset .
                OPTIONAL { ?dataset dct:title ?title }
                OPTIONAL { ?dataset dct:description ?description }
                OPTIONAL { ?dataset dct:spatial ?spatial }
                OPTIONAL { ?dataset dct:publisher ?publisher }
                OPTIONAL { ?dataset dct:creator ?creator }
                OPTIONAL { ?dataset upcast:price ?price }
                OPTIONAL { ?dataset upcast:priceUnit ?priceUnit }
                OPTIONAL { ?dataset idsa-core:Provider ?provider }
            }
        """

        results = self.graph.query(query)
        for row in results:
            dataset = {
                "id": str(row.dataset) if row.dataset else None,
                "title": str(row.title) if row.title else None,
                "description": str(row.description) if row.description else None,
                "spatial": str(row.spatial) if row.spatial else None,
                "publisher": str(row.publisher) if row.publisher else None,
                "creator": str(row.creator) if row.creator else None,
                "price": float(row.price) if row.price else None,
                "priceUnit": str(row.priceUnit) if row.priceUnit else None,
                "provider": str(row.provider) if row.provider else None
            }

            # Add themes to the dataset
            themes = self._extract_themes(dataset["id"])
            if themes:
                dataset["themes"] = themes

            # Add policy URI if available
            policy_uri = self._get_policy_uri(dataset["id"])
            if policy_uri:
                dataset["policyUri"] = policy_uri

            datasets.append(dataset)

        return datasets

    def extract_distributions(self) -> List[Dict[str, Any]]:
        """
        Extract distribution information from the RDF graph for API responses.

        Returns:
            A list of dictionaries containing distribution metadata
        """
        distributions = []

        # Query for distributions
        query = """
            PREFIX dcat: <http://www.w3.org/ns/dcat#>
            PREFIX dct: <http://purl.org/dc/terms/>

            SELECT ?dist ?title ?description ?format ?byteSize ?mediaType
            WHERE {
                ?dist a dcat:Distribution .
                OPTIONAL { ?dist dct:title ?title }
                OPTIONAL { ?dist dct:description ?description }
                OPTIONAL { ?dist dct:format ?format }
                OPTIONAL { ?dist dcat:byteSize ?byteSize }
                OPTIONAL { ?dist dcat:mediaType ?mediaType }
            }
        """

        results = self.graph.query(query)
        for row in results:
            distribution = {
                "id": str(row.dist) if row.dist else None,
                "title": str(row.title) if row.title else None,
                "description": str(row.description) if row.description else None,
                "format": str(row.format) if row.format else None,
                "byteSize": int(row.byteSize) if row.byteSize else None,
                "mediaType": str(row.mediaType) if row.mediaType else None
            }

            # Remove None values
            distribution = {k: v for k, v in distribution.items() if v is not None}

            distributions.append(distribution)

        return distributions

    def extract_agents(self) -> List[Dict[str, Any]]:
        """
        Extract agent information from the RDF graph for API responses.

        Returns:
            A list of dictionaries containing agent metadata
        """
        agents = []

        # Query for agents (organizations and persons)
        query = """
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>

            SELECT ?agent ?name ?type
            WHERE {
                ?agent foaf:name ?name .
                ?agent a ?type .
                FILTER(?type IN (foaf:Agent, foaf:Organization, foaf:Person))
            }
        """

        results = self.graph.query(query)
        for row in results:
            agent_type = str(row.type).split('/')[-1] if row.type else None
            if ":" in agent_type:
                agent_type = agent_type.split(':')[-1]

            agent = {
                "id": str(row.agent) if row.agent else None,
                "name": str(row.name) if row.name else None,
                "type": agent_type
            }

            agents.append(agent)

        return agents

    def extract_policies(self) -> List[Dict[str, Any]]:
        """
        Extract policy information from the RDF graph for API responses.

        Returns:
            A list of dictionaries containing policy metadata
        """
        policies = []

        # Query for policies
        query = """
            PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

            SELECT ?policy ?type
            WHERE {
                ?policy rdf:type ?type .
                FILTER(STRSTARTS(STR(?type), STR(odrl:)) || STRSTARTS(STR(?type), "http://www.w3.org/ns/odrl/2/"))
            }
        """

        results = self.graph.query(query)
        for row in results:
            policy_uri = str(row.policy)
            policy_type = str(row.type).split('/')[-1]
            if ":" in policy_type:
                policy_type = policy_type.split(':')[-1]

            # Get basic policy information
            policy = {
                "id": policy_uri,
                "type": policy_type,
                "permissions": len(self._extract_permissions(policy_uri)),
                "prohibitions": len(self._extract_prohibitions(policy_uri)),
                "obligations": len(self._extract_obligations(policy_uri))
            }

            # Find associated datasets
            associated_datasets = self._find_datasets_with_policy(policy_uri)
            if associated_datasets:
                policy["associatedDatasets"] = associated_datasets

            policies.append(policy)

        return policies

    def _find_datasets_with_policy(self, policy_uri: str) -> List[str]:
        """
        Find datasets that are associated with a specific policy.

        Args:
            policy_uri: The URI of the policy

        Returns:
            A list of dataset URIs
        """
        datasets = []

        query = f"""
            PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
            PREFIX dcat: <http://www.w3.org/ns/dcat#>

            SELECT ?dataset
            WHERE {{
                ?dataset a dcat:Dataset .
                ?dataset odrl:hasPolicy <{policy_uri}> .
            }}
        """

        results = self.graph.query(query)
        for row in results:
            datasets.append(str(row.dataset))

        return datasets

    def get_full_policy_details(self, policy_uri: str) -> Dict[str, Any]:
        """
        Get complete details for a specific policy.

        Args:
            policy_uri: The URI of the policy

        Returns:
            A dictionary with full policy details
        """
        # Extract the ODRL policy
        policy = self._extract_odrl_policy(policy_uri)

        # Find associated datasets
        associated_datasets = self._find_datasets_with_policy(policy_uri)

        # Add dataset information
        datasets_info = []
        for dataset_uri in associated_datasets:
            # Create temporary graph with just this dataset
            for dataset in self.extract_datasets():
                if dataset["id"] == dataset_uri:
                    datasets_info.append(dataset)
                    break

        # Return combined result
        return {
            "policy": policy,
            "associatedDatasets": datasets_info
        }

    def validate_policy(self, policy_uri: str) -> Dict[str, Any]:
        """
        Validate a policy structure and return validation results.

        Args:
            policy_uri: The URI of the policy to validate

        Returns:
            A dictionary with validation results
        """
        validation_results = {
            "isValid": True,
            "errors": [],
            "warnings": []
        }

        # Check policy permissions
        permissions = self._extract_permissions(policy_uri)
        if not permissions:
            validation_results["warnings"].append("Policy has no permissions defined")

        # Check for conflicting rules
        prohibitions = self._extract_prohibitions(policy_uri)
        if permissions and prohibitions:
            permission_actions = [p.get("action") for p in permissions if isinstance(p.get("action"), str)]
            prohibition_actions = [p.get("action") for p in prohibitions if isinstance(p.get("action"), str)]

            # Check for direct conflicts
            conflicts = set(permission_actions).intersection(set(prohibition_actions))
            if conflicts:
                validation_results["isValid"] = False
                validation_results["errors"].append(f"Policy has conflicting rules for actions: {', '.join(conflicts)}")

        # Check target validity
        associated_datasets = self._find_datasets_with_policy(policy_uri)
        if not associated_datasets:
            validation_results["warnings"].append("Policy is not associated with any dataset")

        return validation_results

    def get_simplified_policy(self, policy_uri: str) -> Dict[str, Any]:
        """
        Get a simplified human-readable version of a policy.

        Args:
            policy_uri: The URI of the policy

        Returns:
            A dictionary with simplified policy information
        """
        permissions = self._extract_permissions(policy_uri)
        prohibitions = self._extract_prohibitions(policy_uri)
        obligations = self._extract_obligations(policy_uri)

        # Extract action names
        permission_actions = []
        for p in permissions:
            action = p.get("action")
            if isinstance(action, str):
                permission_actions.append(action)
            elif isinstance(action, dict) and "@id" in action:
                permission_actions.append(action["@id"].split('/')[-1])

        prohibition_actions = []
        for p in prohibitions:
            action = p.get("action")
            if isinstance(action, str):
                prohibition_actions.append(action)
            elif isinstance(action, dict) and "@id" in action:
                prohibition_actions.append(action["@id"].split('/')[-1])

        obligation_actions = []
        for o in obligations:
            action = o.get("action")
            if isinstance(action, str):
                obligation_actions.append(action)
            elif isinstance(action, dict) and "@id" in action:
                obligation_actions.append(action["@id"].split('/')[-1])

        # Get assignees if available
        assignees = set()
        for rules in [permissions, prohibitions, obligations]:
            for rule in rules:
                if rule.get("assignee"):
                    assignee = rule.get("assignee")
                    if isinstance(assignee, str):
                        assignees.add(assignee.split('/')[-1])
                    elif isinstance(assignee, dict) and "@id" in assignee:
                        assignees.add(assignee["@id"].split('/')[-1])

        return {
            "id": policy_uri,
            "allowed": permission_actions,
            "forbidden": prohibition_actions,
            "required": obligation_actions,
            "forUsers": list(assignees) if assignees else ["Everyone"],
            "summary": self._generate_policy_summary(permission_actions, prohibition_actions, obligation_actions)
        }

    def _generate_policy_summary(self, permissions: List[str], prohibitions: List[str], obligations: List[str]) -> str:
        """
        Generate a human-readable summary of a policy.

        Args:
            permissions: List of permitted actions
            prohibitions: List of prohibited actions
            obligations: List of required actions

        Returns:
            A human-readable summary
        """
        parts = []

        if permissions:
            parts.append(f"You may {', '.join(permissions)}")

        if prohibitions:
            parts.append(f"You may not {', '.join(prohibitions)}")

        if obligations:
            parts.append(f"You must {', '.join(obligations)}")

        if not parts:
            return "No specific actions defined in this policy."

        return ". ".join(parts) + "."