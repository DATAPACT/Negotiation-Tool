# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------



from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.contrib.auth import get_user_model
from six import text_type


def merge_dictionaries(dict1, dict2):
    merged_dict = dict1.copy()
    for key, value in dict2.items():
        if key in merged_dict:
            if isinstance(value, dict):
                merge_dictionaries(merged_dict[key], value)
            elif isinstance(value, list):
                merged_dict[key].extend(value)
            else:
                merged_dict[key] = value
        else:
            merged_dict[key] = value
    return merged_dict


def convert_to_list(node):
    result = []
    if "node_name" in node and node["node_name"] != "DataSource":
        result.append(node["node_name"].upper())
    if "children" in node:
        for child in node["children"]:
            result.extend(convert_to_list(child))
    return result


def convert_user_consent_to_odrl(data):
    # code from Jaime
    policy = {"permission": [], "prohibition": []}
    user_consent = data["consent"]
    additional_constraints = data["additional_constraints"]
    targets = user_consent["consent_data"]
    actions = user_consent["consent_operations"]
    consent_date_start = user_consent["consent_date_start"]
    consent_date_end = user_consent["consent_date_end"]
    consent_purpose = user_consent["consent_purpose"]
    consent_requested_by = user_consent["consent_requested_by"]
    odrl_jsonld = {
        "assignee": consent_requested_by,
        "action": actions,
        "target": targets,
        "constraint": [],
    }
    odrl_jsonld["constraint"].append(
        {
            "leftOperand": "datetime",
            "operator": "gt",
            "rightOperand": consent_date_start,
        }
    )
    odrl_jsonld["constraint"].append(
        {"leftOperand": "datetime", "operator": "lt", "rightOperand": consent_date_end}
    )
    odrl_jsonld["refinement"] = {
        "leftOperand": "Purpose",
        "operator": "eq",
        "rightOperand": consent_purpose,
    }
    policy["permission"].append(odrl_jsonld)

    for constraint in additional_constraints:
        odrl_jsonld = {
            "assignee": consent_requested_by,
            "action": constraint["action"],
            "target": targets,
            "constraint": [],
        }
        odrl_jsonld["constraint"].append(
            {
                "leftOperand": constraint["constraint"]["leftOperand"],
                "operator": constraint["constraint"]["operator"],
                "rightOperand": constraint["constraint"]["rightOperand"],
            }
        )
        odrl_jsonld["refinement"] = {
            "leftOperand": "Purpose",
            "operator": "eq",
            "rightOperand": consent_purpose,
        }
        if constraint["permission_status"] == "Permission":
            policy["permission"].append(odrl_jsonld)
        elif constraint["permission_status"] == "Prohibition":
            policy["prohibition"].append(odrl_jsonld)
    return policy


def check_match(lista, listb):
    total_matches = 0
    for requested_data in lista:
        for user_data in listb:
            if requested_data.lower() == user_data.lower():
                total_matches += 1
                break  # Found a match, no need to continue checking this element in list2
    print(total_matches, len(lista))
    return True if total_matches == len(lista) else False


def match_user_data_with_controller_request_data(datalist1, datalist2):
    if len(datalist1) > len(datalist2):
        return check_match(lista=datalist2, listb=datalist1)
    else:
        return check_match(lista=datalist1, listb=datalist2)


def get_all_users():
    """
    Get all the users from the database who are of type DATA_PROVIDER
    and are active, i.e., the user is activated to use the system.
    :return: Users
    @type: QuerySet
    """
    User = get_user_model()
    all_users = User.objects.filter(is_active=True).filter(role="DATA_PROVIDER")
    return all_users


def sentence_rule_permission_status(custom_restrictions):
    list_of_rules = []
    for restriction in custom_restrictions:
        for condition in restriction["constraint"]:
            print("###########")
            print(condition, restriction["constraint"])
            print("#####--######")
            values_for_list_of_rules = {
                "action": restriction["action"],
                "assignee": restriction["assignee"],
                "constraint": {
                    "leftOperand": condition["leftOperand"],
                    "operator": condition["operator"],
                    "rightOperand": condition["rightOperand"],
                },
            }

            sentence = f"Would you like to give permission on a {restriction['action']} action by {restriction['assignee']}, with the constraint that the {condition['leftOperand']} {condition['operator']} {condition['rightOperand']}?"
            list_of_rules.append(
                [sentence, values_for_list_of_rules]
            )  # append the sentence and the values for the sentence
    return list_of_rules


def sentence_rule_permission_status_revoke(custom_restrictions):
    list_of_rules = []
    print("###########")
    print(custom_restrictions)
    for item in custom_restrictions:
        values_for_list_of_rules = {
            "action": item["action"],
            "assignee": item["assignee"],
            "constraint": {
                "leftOperand": item["constraint"]["leftOperand"],
                "operator": item["constraint"]["operator"],
                "rightOperand": item["constraint"]["rightOperand"],
            },
        }
        sentence = f"Would you like to give permission on a {item['action']} action by {item['assignee']}, with the constraint that the {item['constraint']['leftOperand']} {item['constraint']['operator']} {item['constraint']['rightOperand']}?"
        list_of_rules.append(
            [sentence, values_for_list_of_rules, item["permission_status"]]
        )  # append the sentence and the values for the sentence

    return list_of_rules


class GenerateRandomToken(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        return text_type(user.pk) + text_type(timestamp)


generate_token = GenerateRandomToken()
