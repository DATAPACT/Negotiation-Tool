import json
from copy import deepcopy
from typing import Any, Dict, Optional, Union

from rdflib import Namespace

from custom_accounts.ajax_ontology import custom_convert_odrl_policy, convert_list_to_odrl_jsonld_no_user
from data_model import UpcastPolicyObject

ODRL = Namespace("http://www.w3.org/ns/odrl/2/")
DPV = Namespace("https://w3id.org/dpv/dpv-owl#")
EX = Namespace("http://example.org/resource/")


def isJsonBlankNodesGraphFormat(json_ld_obj):
    """
    Returns True if the JSON-LD object contains explicitly defined blank nodes
    (e.g., "@id": "_:b0"), otherwise False.
    """

    # Ensure input is a dictionary
    if not isinstance(json_ld_obj, dict):
        return False

    # Extract the "@graph" key if it exists
    graph_data = json_ld_obj.get("@graph", None)

    if not graph_data or not isinstance(graph_data, list):
        return False

    # Helper function to recursively search for blank node identifiers
    def contains_blank_node(obj):
        if isinstance(obj, dict):
            # Check if the dict has an @id starting with "_:"
            if "@id" in obj and isinstance(obj["@id"], str) and obj["@id"].startswith("_:"):
                return True
            # Otherwise, recurse into values
            return any(contains_blank_node(v) for v in obj.values())
        elif isinstance(obj, list):
            return any(contains_blank_node(i) for i in obj)
        return False

    # Check all objects in @graph for blank nodes
    return any(contains_blank_node(item) for item in graph_data)


def has_none_value_on_first_level(d):
    """ Check if dictionary d has at least one None value on the first level """
    return any((value is None) or (value == '' and key == "value") for key, value in d.items())


def filter_dicts_with_none_values(data):
    """
    Recursively filter out dictionaries from data that have at least one None value on the first level.
    Handles nested lists and dictionaries.
    """
    if isinstance(data, list):
        filtered_list = []
        for item in data:
            if isinstance(item, dict):
                if not has_none_value_on_first_level(item):
                    filtered_list.append(filter_dicts_with_none_values(item))
            elif isinstance(item, list):
                filtered_list.append(filter_dicts_with_none_values(item))
            else:
                filtered_list.append(item)
        return filtered_list
    elif isinstance(data, dict):
        filtered_dict = {}
        for key, value in data.items():
            if isinstance(value, dict):
                if not has_none_value_on_first_level(value):
                    filtered_dict[key] = filter_dicts_with_none_values(value)
            elif isinstance(value, list):
                filtered_dict[key] = filter_dicts_with_none_values(value)
            else:
                filtered_dict[key] = value
        return filtered_dict
    else:
        return data


def _as_dict(value: Any) -> Optional[Dict[str, Any]]:
    """
    Try to turn the input value into a dictionary.
    Accepts dictionaries or JSON strings.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return None
        return deepcopy(parsed) if isinstance(parsed, dict) else None
    return None


def _ensure_odrl_string(value: Any) -> Optional[str]:
    """
    Returns a JSON string representation suitable for rdflib parsing.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return None


def odrl_convertor(policy: Union[UpcastPolicyObject, Dict[str, Any]]) -> UpcastPolicyObject:
    """
    Normalise the ODRL representation inside a policy object.

    Accepts either an UpcastPolicyObject (preferred) or a dictionary that can be
    used to instantiate one, and always returns an UpcastPolicyObject.
    """
    if policy is None:
        raise ValueError("policy is required for ODRL conversion")

    if isinstance(policy, UpcastPolicyObject):
        policy_obj = policy
    elif isinstance(policy, dict):
        policy_obj = UpcastPolicyObject(**policy)
    else:
        raise TypeError("Unsupported policy type for ODRL conversion")

    policy_copy = policy_obj.copy(deep=True)
    odrl_payload = policy_copy.odrl_policy

    odrl_dict = _as_dict(odrl_payload)
    if odrl_dict is None:
        # Nothing to convert or payload not recognised
        return policy_copy

    updated_odrl = odrl_dict

    if isJsonBlankNodesGraphFormat(odrl_dict):
        cactus_format = deepcopy(odrl_dict)
        json_payload = _ensure_odrl_string(cactus_format)
        if json_payload:
            negotiation_front_format = custom_convert_odrl_policy(json_payload)

            # filtered_data = filter_dicts_with_none_values(negotiation_front_format)
            # odrl_format = convert_list_to_odrl_jsonld_no_user(filtered_data)
            # cactus_format["data"] = filtered_data

            # filtered_data = filter_dicts_with_none_values(negotiation_front_format)
            odrl_format = convert_list_to_odrl_jsonld_no_user(negotiation_front_format)
            cactus_format["data"] = negotiation_front_format

            print(cactus_format["data"])
            cactus_format["odrl"] = odrl_format
            updated_odrl = cactus_format
    elif "data" not in odrl_dict and "odrl" in odrl_dict:
        odrl_source = odrl_dict["odrl"]
        json_payload = _ensure_odrl_string(odrl_source)
        if json_payload:
            # negotiation_front_format = custom_convert_odrl_policy(json_payload)
            # filtered_data = filter_dicts_with_none_values(negotiation_front_format)

            negotiation_front_format = custom_convert_odrl_policy(json_payload)
            odrl_format = convert_list_to_odrl_jsonld_no_user(negotiation_front_format)
            odrl_dict = deepcopy(odrl_dict)
            odrl_dict["data"] = negotiation_front_format
            odrl_dict["odrl"] = odrl_format
            updated_odrl = odrl_dict

    elif "data" not in odrl_dict and "odrl" not in odrl_dict and odrl_dict:
        json_payload = _ensure_odrl_string(odrl_dict)
        if json_payload:
            negotiation_front_format = custom_convert_odrl_policy(json_payload)
            # filtered_data = filter_dicts_with_none_values(negotiation_front_format)
            odrl_format = convert_list_to_odrl_jsonld_no_user(negotiation_front_format)

            odrl_dict = {}
            odrl_dict["data"] = negotiation_front_format
            odrl_dict["odrl"] = odrl_format
            updated_odrl = odrl_dict

    policy_copy.odrl_policy = updated_odrl

    # try:
    #     demo_dir = Path(__file__).resolve().parent / "demo"
    #     demo_dir.mkdir(exist_ok=True)
    #     timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    #     output_path = demo_dir / f"odrl_policy_{timestamp}.json"
    #     with output_path.open("w", encoding="utf-8") as output_file:
    #         json.dump(
    #             policy_copy.model_dump(by_alias=True),
    #             output_file,
    #             default=str,
    #             indent=2,
    #         )
    # except Exception as file_error:
    #     logging.getLogger(__name__).warning(
    #         "Failed to persist converted policy: %s", file_error
    #     )

    return policy_copy
