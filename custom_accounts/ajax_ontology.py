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
import os
import time
import uuid
# CM CHANGE telnetlib deprecated at pyton 3.13
import sys
if sys.version_info < (3, 13):
    from telnetlib import EC
else:
    from telnetlib3 import EC

from owlready2 import owl, default_world
import rdflib
from rdflib import Graph, Namespace, BNode, URIRef, RDF, Literal
from rdflib.collection import Collection
from rdflib.namespace import NamespaceManager
from collections import defaultdict

import json

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait

from custom_accounts.predictions import ontology_classes_dict, prettyfy
from privux import settings


def use_case_ontology_classes(ontology_file):
    """Returns the list of classes from the ontology
    :param ontology_file: ontology file
    :type ontology_file: str
    :return: list of classes
    :rtype: list
    Example:
            {
          "Exercise": [
            "CleanAndJerk",
            "Crunch",
            "Deadlift",
            "ImaginaryChair",
            "MachineRow",
            "PushUp",
            "RussianTwist",
            "SplitSquats",
            "Squat",
            "Weightlifting"
          ],
          "DifficultyLevel": [
            "Easy",
            "Hard",
            "Medium"
          ],
          "ExerciseTypes": [
            "AgilityAndPlyometric",
            "Balance",
            "Cardiovascular",
            "CoreTraining",
            "Endurance",
            "Flexibility",
            "FunctionalTraining",
            "HighIntensityIntervalTraining",
            "Isolation",
            "Rehabilitation",
            "Strength"
          ],
          "MuscleGroup": [
            "Abdominals",
            "Abs",
            "Arms",
            "Chest",
            "Legs",
            "Shoulders"
          ]
        }
    """
    thing_subclass = {}
    read_ontology(ontology_file)
    for cls in list(owl.Thing.subclasses()):
        subitems = [
            prettyfy(str(item), False)
            for item in list(cls.subclasses())
            if (len(list(cls.subclasses())) > 0)
        ]
        thing_subclass[prettyfy(str(cls), False)] = subitems
    return thing_subclass


def read_ontology(ontology_file, world=None):
    """Reads the ontology file and returns the ontology
    :param ontology_file: ontology file
    :type ontology_file: str
    :param world: world
    :type world: owlready2.World
    :return: ontology
    :rtype: owlready2.Ontology
    """
    ontology_file = str(os.path.relpath(ontology_file))
    if world is not None:
        ontology = world.get_ontology(
            os.path.join(settings.MEDIA_ROOT, str(ontology_file))
        ).load()
        if ontology_classes_dict(ontology):
            ontology.destroy()
            ontology = world.get_ontology(
                os.path.join(settings.MEDIA_ROOT, str(ontology_file))
            ).load()
    else:
        ontology = default_world.get_ontology(
            os.path.join(settings.MEDIA_ROOT, str(ontology_file))
        ).load()
        if ontology_classes_dict(ontology):
            try:
                ontology.destroy()
            except Exception as e:
                print(f"Ontology classes: {(ontology, e)}")
            ontology = default_world.get_ontology(
                os.path.join(settings.MEDIA_ROOT, str(ontology_file))
            ).load()
    return ontology


class MakeTree:
    def __init__(self, data):
        self.data = data
        self.children = []

    def add_child(self, child_node):
        self.children.append(child_node)


def tree_to_dict(node):
    result = {"node_name": node.data}
    if node.children:
        result["children"] = [tree_to_dict(child) for child in node.children]
    return result


def ontology_data_to_dict_tree(
    ontology,
    root,
    class_first_name=None,
    class_second_name=None,
):
    """Converts the daa classes of an ontology to a dict tree
    :param ontology: Ontology in owl/rdf format
    :type ontology: owlready2.Ontology
    :return: tree of purposes
    :rtype: dict
    """
    class_a = []
    class_b = []

    if root is None:
        return {"error": "Root class is not defined"}

    if class_first_name is not None:
        class_a = list(ontology_classes_dict(ontology)[class_first_name].subclasses())
    if class_second_name is not None:
        class_b = list(ontology_classes_dict(ontology)[class_second_name].subclasses())

    combined_data = class_a + class_b

    if not combined_data:
        return {}

    root = MakeTree(prettyfy(str(ontology_classes_dict(ontology)[root]), False))
    for cls in combined_data:
        root_child = MakeTree(prettyfy(str(cls), False))
        root.children.append(root_child)
        root_child_has_subclasses = list(cls.subclasses())
        if root_child_has_subclasses:
            for childcls in root_child_has_subclasses:
                root_child.children.append(MakeTree(prettyfy(str(childcls), False)))
    dict_tree = tree_to_dict(root)
    return dict_tree


def get_leaf_node_names(node):
    """Returns the list of leaf node names from the ontology
    Input is the tree data constructed based on data_context ontology.
    Example:
      'node_name': 'DataSource',
    'children': [
        {'node_name': 'Humidity'},
        {'node_name': 'Magnetometer'},
        {
            'node_name': 'PersonalData',
            'children': [
                {'node_name': 'Email'},
                {'node_name': 'Name'},
                {'node_name': 'SocialSecurityNumber'}
            ]
        },
        {'node_name': 'IPAddress'}
    ]

    Output:
     ['Humidity', 'Magnetometer', 'Email', 'Name', 'SocialSecurityNumber', 'IPAddress']

    :param node: Tree format
    :type node: MakeTree
    :return:  leaf node names
    :rtype: list
    """
    if "children" not in node:
        return [node["node_name"]]
    else:
        # Recursive case: node has children
        leaf_node_names = []
        for child in node["children"]:
            leaf_node_names.extend(get_leaf_node_names(child))
        return leaf_node_names

def get_fields_from_datasets(dataset):
    global global_graph
    g = global_graph
    # Query actions
    actions_query = f"""
        PREFIX ex: <http://example.org/datasets/>
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT DISTINCT ?columnName ?columnType ?columnDescription ?columnExample
        WHERE {{
            <{dataset}> rdf:type ex:Dataset ;
                ex:hasColumn [ rdf:type ex:Column ;
                               ex:columnName ?columnName ;
                               ex:columnDataType ?columnType ;
                               ex:columnDescription ?columnDescription ;
                               ex:columnExample ?columnExample ] .
        }}
    """

    fields = [
        {"uri": row.columnName.value,"label": row.columnName.value,"columnName": row.columnName.value,"columnType": row.columnType.value,"columnDescription": row.columnDescription.value,"columnExample": row.columnExample.value}
        for row in g.query(actions_query)
    ]

    return fields

global_graph = Graph()

def populate_graph(ttl_file_path, format="xml"):
    g = Graph()
    g.parse(ttl_file_path, format=format)
    global global_graph
    global_graph += g
    print(global_graph)

def populate_content_to_graph(ttl_content, format="xml"):
    try:
        g = Graph()
        g.parse(data=ttl_content, format=format)
        global global_graph
        global_graph += g
    except:
        pass

# def get_actions_from_ttl():
#     global global_graph
#     g = global_graph
#     # Define the relevant namespaces
#     # odrl = Namespace("http://www.w3.org/ns/odrl/2/#")
#     skos = Namespace("http://www.w3.org/2004/02/skos/core#")
#
#     # Query for actions in the skos:Collection
#     actions_query = """
#     SELECT ?action
#     WHERE {
#       ?collection a skos:Collection ;
#                   skos:member ?action .
#     }
#     """
#
#     # Execute the query
#     actions_result = g.query(actions_query, initNs={"skos": skos})
#
#     # Extract and return the list of actions
#     actions_list = [str(action) for action, in actions_result]
#     return actions_list


def get_rules_from_odrl():
    global global_graph
    g = global_graph

    # Define namespace
    # odrl = Namespace(
    #     "http://www.w3.org/ns/odrl/2/#"
    # )  # Replace with the actual namespace
    # rdfs = Namespace("http://www.w3.org/2000/01/rdf-schema#")

    # Query for subclasses of :Rule
    subclasses_query = """
        SELECT ?subClass ?label
        WHERE {
          ?subClass rdfs:subClassOf odrl:Rule ;
                    rdfs:label ?label .
        }
    """

    # Execute the query
    subclasses_result = g.query(subclasses_query)

    # Convert results to a list of dictionaries
    result_list = [
        {"uri": str(row.subClass), "label": str(row.label)} for row in subclasses_result
    ]

    return result_list


def get_actors_from_dpv():
    global global_graph
    g = global_graph
    # dpv = Namespace("https://w3id.org/dpv#")
    skos = Namespace("http://www.w3.org/2004/02/skos/core#")

    # Query for subclasses of :Rule
    subclasses_query = """
        SELECT ?subClass ?label
        WHERE {
          ?subClass rdfs:subClassOf+ <http://www.w3.org/ns/odrl/2/Party> .
          ?subClass ( rdfs:label | skos:prefLabel ) ?label .
        }
    """

    # Execute the query
    subclasses_result = g.query(subclasses_query)

    # Convert results to a list of dictionaries
    result_list = [
        {"uri": str(row.subClass), "label": str(row.label)} for row in subclasses_result
    ]

    return result_list


# def get_purposes_from_dpv_old():
#     global global_graph
#     g = global_graph
#     # Define namespace
#     # dpv = Namespace("https://w3id.org/dpv#")  # Replace with the actual namespace
#     # skos = Namespace("http://www.w3.org/2004/02/skos/core#")
#
#     # Query for subclasses of :Rule
#     subclasses_query = """
#         SELECT ?subClass ?label
#         WHERE {
#           ?subClass rdfs:subClassOf <https://w3id.org/dpv/dpv-owl#Purpose> .
#           ?subClass rdfs:label ?label .
#         }
#     """
#
#     # Execute the query
#     subclasses_result = g.query(subclasses_query)
#
#     # Convert results to a list of dictionaries
#     result_list = [
#         {"uri": str(row.subClass), "label": str(row.label)} for row in subclasses_result
#     ]
#
#     return result_list


def get_constraints_types_from_odrl():
    global global_graph
    g = global_graph
    # Query for subclasses of :Rule
    query = """
        SELECT ?leftoperand ?label
        WHERE {
          ?leftoperand a odrl:LeftOperand, owl:NamedIndividual ;
                    rdfs:label ?label .
        }
    """

    # Execute the query
    result = g.query(query)

    # Convert results to a list of dictionaries
    result_list = [
        {"uri": str(row.leftoperand), "label": str(row.label)} for row in result
    ]

    return result_list


def get_dataset_titles_and_uris():
    global global_graph
    g = global_graph
    # Define the relevant namespaces
    ex = Namespace("http://example.org/datasets/")
    dct = Namespace("http://purl.org/dc/terms/")

    # Query for dataset titles and URIs
    query = """
    SELECT ?dataset ?title
    WHERE {
      ?dataset rdf:type ex:Dataset ;
               dct:title ?title .
    }
    """

    # Execute the query
    result = g.query(query, initNs={"ex": ex, "dct": dct})

    # Extract and return the list of dataset titles and URIs
    dataset_info_list = [
    # CMADD - The URI is now required as the label (done this way to minimise change in profile.html)
        #{"uri": str(dataset), "label": str(title)} for dataset, title in result
        {"uri": str(dataset), "label": str(dataset)} for dataset, title in result
    ]
    return dataset_info_list


def get_action_hierarchy_from_odrl():
    global global_graph
    g = global_graph

    # Define the SPARQL query to get actions and their relationships
    actions_query = """
    SELECT DISTINCT ?action ?label ?sub_action ?sub_label
    WHERE {
        ?action a odrl:Action.
        ?action ( rdfs:label | skos:prefLabel ) ?label.
        { ?sub_action odrl:includedIn | rdfs:subClassOf ?action }
        UNION
        { ?action odrl:includedBy | rdfs:subClassOf ?sub_action }
        ?sub_action ( rdfs:label | skos:prefLabel ) ?sub_label
    }
    """

    # Dictionaries to hold actions and their labels
    uri_label_dict = {}
    action_hierarchy = {}

    # Execute the query and populate the dictionaries
    for row in g.query(actions_query):
        action_uri = str(row.action)
        action_label = str(row.label)
        sub_action_uri = str(row.sub_action)
        sub_action_label = str(row.sub_label)

        # Store labels for each URI
        uri_label_dict[action_uri] = action_label
        uri_label_dict[sub_action_uri] = sub_action_label

        # Organise actions into a hierarchy
        if action_uri not in action_hierarchy:
            action_hierarchy[action_uri] = {"uri": action_uri, "label": action_label, "children": []}
        if sub_action_uri not in action_hierarchy:
            action_hierarchy[sub_action_uri] = {"uri": sub_action_uri, "label": sub_action_label, "children": []}
        action_hierarchy[action_uri]["children"].append(action_hierarchy[sub_action_uri])

    # Filter to include only top-level actions
    top_level_actions = {
        key: value for key, value in action_hierarchy.items()
        if not any(key in item["children"] for item in action_hierarchy.values())
    }

    # Return the hierarchy as a list
    return list(top_level_actions.values())

def get_purpose_hierarchy_from_dpv():
    global global_graph
    g = global_graph

    # Define the SPARQL query to get actions and their relationships
    purpose_query = """
    SELECT DISTINCT ?purpose ?label ?sub_purpose ?sub_label
    WHERE {
        ?purpose (rdf:type |  rdfs:subClassOf)? <https://w3id.org/dpv/owl#Purpose> .
        ?purpose ( rdfs:label | skos:prefLabel ) ?label .
  { ?sub_purpose (skos:broader | rdfs:subClassOf ) ?purpose }
        UNION
  { ?purpose skos:narrower  ?sub_purpose }
        ?sub_purpose ( rdfs:label | skos:prefLabel ) ?sub_label
    
}
    """

    # Dictionaries to hold actions and their labels
    uri_label_dict = {}
    purpose_hierarchy = {}

    # Execute the query and populate the dictionaries
    for row in g.query(purpose_query):
        purpose_uri = str(row.purpose)
        purpose_label = str(row.label)
        sub_purpose_uri = str(row.sub_purpose)
        sub_purpose_label = str(row.sub_label)

        # Store labels for each URI
        uri_label_dict[purpose_uri] = purpose_label
        uri_label_dict[sub_purpose_uri] = sub_purpose_label

        # Organise actions into a hierarchy
        if purpose_uri not in purpose_hierarchy:
            purpose_hierarchy[purpose_uri] = {"uri": purpose_uri, "label": purpose_label, "children": []}
        if sub_purpose_uri not in purpose_hierarchy:
            purpose_hierarchy[sub_purpose_uri] = {"uri": sub_purpose_uri, "label": sub_purpose_label, "children": []}
        purpose_hierarchy[purpose_uri]["children"].append(purpose_hierarchy[sub_purpose_uri])

    # Filter to include only top-level actions
    top_level_purposes = {
        key: value for key, value in purpose_hierarchy.items()
        if not any(key in item["children"] for item in purpose_hierarchy.values())
    }

    # Return the hierarchy as a list
    return list(top_level_purposes.values())


def get_actor_hierarchy_from_dpv():
    print('starting get_actor_hierarchy_from_dpv')
    global global_graph
    g = global_graph

    dpv = Namespace("https://w3id.org/dpv/owl#")
    skos = Namespace("http://www.w3.org/2004/02/skos/core#")
    odrl = Namespace("http://www.w3.org/ns/odrl/2/")
    g.bind("dpv", dpv)
    g.bind("skos", skos)
    g.bind("odrl", odrl)

    # Define the SPARQL query to get actions and their relationships
    actor_query = """
    SELECT DISTINCT ?actor ?label ?sub_actor ?sub_label
    WHERE {
        ?actor rdfs:subClassOf* odrl:Party .
        ?actor skos:prefLabel|rdfs:label ?label .
        ?sub_actor rdfs:subClassOf ?actor .
        ?sub_actor skos:prefLabel|rdfs:label ?sub_label
    }
    """

    # Dictionaries to hold actions and their labels
    uri_label_dict = {}
    actor_hierarchy = {}

    # Execute the query and populate the dictionaries
    for row in g.query(actor_query):
        actor_uri = str(row.actor)
        actor_label = str(row.label)
        sub_actor_uri = str(row.sub_actor)
        sub_actor_label = str(row.sub_label)

        # Store labels for each URI
        uri_label_dict[actor_uri] = actor_label
        uri_label_dict[sub_actor_uri] = sub_actor_label

        # Organise actions into a hierarchy
        if actor_uri not in actor_hierarchy:
            actor_hierarchy[actor_uri] = {"uri": actor_uri, "label": actor_label, "children": []}
        if sub_actor_uri not in actor_hierarchy:
            actor_hierarchy[sub_actor_uri] = {"uri": sub_actor_uri, "label": sub_actor_label, "children": []}
        actor_hierarchy[actor_uri]["children"].append(actor_hierarchy[sub_actor_uri])

    # Filter to include only top-level actions
    top_level_actors = {
        key: value for key, value in actor_hierarchy.items()
        if not any(key in item["children"] for item in actor_hierarchy.values())
    }

    # Return the hierarchy as a list
    return list(top_level_actors.values())

def get_actions_from_odrl():
    global global_graph
    g = global_graph
    # Define namespaces
    # odrl = Namespace("http://www.w3.org/ns/odrl/2/#")

    # Query actions
    actions_query = """
    SELECT ?action ?label ?parent_action ?parent_label
    WHERE {
        ?action a odrl:Action.
        ?action rdfs:label ?label.
        OPTIONAL { ?action odrl:includedIn ?parent_action .
                    ?parent_action rdfs:label ?parent_label . }
    }
    """
    actions = [
        {"uri": str(row.action), "label": str(row.label), "parent_uri" : str(row.parent_action), "parent_label" : str(row.parent_label)}
        for row in g.query(actions_query)
    ]

    return actions

# def get_properties_of_a_class(class_uri, ttl_file_path):
#     # Parse TTL content
#     g = Graph()
#     g.parse(str(ttl_file_path), format="ttl")
#     if "/" in class_uri:
#         class_uri = "<" + class_uri + ">"
#     properties_query = f"""
#         PREFIX dpv: <https://w3id.org/dpv/dpv-owl#>
#         PREFIX cc: <http://creativecommons.org/ns#>
#         PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
#         PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
#         PREFIX owl: <http://www.w3.org/2002/07/owl#>

#         SELECT ?property ?label
#         WHERE {{
#           ?property rdf:type owl:DatatypeProperty ;
#                     rdfs:domain {class_uri} ;
#                     rdfs:label ?label .
#         }}
#     """

#     properties = [
#         {"uri": str(row.property), "label": str(row.label)}
#         for row in g.query(properties_query)
#     ]
#     print("<<<<< We are leaving get_properties_of a_class")
#     return properties

def get_properties_of_a_class(class_uri):
    global global_graph
    g = global_graph
    
    print("<<<<< We are in get_properties_of a_class")

    if "dpv" in class_uri:
        class_uri = "dpv:"+class_uri.split("#")[1]
    if "/" in class_uri:
        class_uri = "<" + class_uri + ">"
    properties_query = f"""
        PREFIX dpv: <https://w3id.org/dpv/owl#>
        PREFIX cc: <http://creativecommons.org/ns#>
        PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

        SELECT ?property ?label
        WHERE {{
        {class_uri} rdf:type? / ( skos:broader? | rdfs:subClassOf? ) ?class .
        ?property ( rdfs:domain | schema:domainIncludes | dcam:domainIncludes ) / ( skos:broader | rdfs:subClassOf)? ?class ;
                    ( rdfs:label | skos:prefLabel ) ?label .
        }}
    """
    properties = [
        {"uri": str(row.property), "label": str(row.label)}
        for row in g.query(properties_query)
    ]
    print("<<<<< We are leaving get_properties_of a_class")
    return properties



def get_constraints_for_instances(instance):
    print('get constraints for instance', instance)
    global global_graph
    g = global_graph
    if "dpv" in instance:
        instance = "dpv:" + instance.split("#")[1]

    if "/" in instance:
        instance = "<" + instance + ">"
    query = f"""
        PREFIX dpv: <https://w3id.org/dpv/owl#>
        PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX : <http://example.org/>

        SELECT DISTINCT ?property ?label
    WHERE {{
              {instance} (<http://www.w3.org/2004/02/skos/core#broader> | <http://www.w3.org/ns/odrl/2/includedIn> )* ?parent .

              ?parent <http://example.org/hasAttribute> ?property .

              ?property rdfs:label ?label .

            }} ORDER BY UCASE(?label)
    """

    # Execute the query
    result = g.query(query)

    # Convert results to a list of dictionaries
    result_list = [
        {"uri": str(row.property), "label": str(row.label)} for row in result
    ]

    return result_list

def get_purposes_from_dpv():
    global global_graph
    g = global_graph

    # Define namespace
    dpv = Namespace("https://w3id.org/dpv/owl#")  # Replace with the actual namespace
    skos = Namespace("http://www.w3.org/2004/02/skos/core#")
    g.bind("dpv",dpv)
    g.bind("skos",skos)

    # Query for subclasses of :Rule
    subclasses_query = """
        SELECT ?subclass ?label ?parent_class ?class_label
        WHERE {
            ?subclass rdf:type dpv:Purpose .
            ?subclass ( rdfs:label | skos:prefLabel ) ?label.
            OPTIONAL { ?subclass ( skos:broader | rdfs:subClassOf) ?parent_class .
                        ?parent_class ( rdfs:label | skos:prefLabel ) ?class_label . }
        }
    """

    # Execute the query
    subclasses_result = g.query(subclasses_query)

    # Convert results to a list of dictionaries
    result_list = [
        {"uri": str(row.subclass), "label": str(row.label), "parent_uri" : str(row.parent_class), "parent_label" : str(row.class_label)} for row in subclasses_result
    ]

    return result_list


def get_operators_from_odrl():
    global global_graph
    g = global_graph

    # Define namespaces
    # odrl = Namespace("http://www.w3.org/ns/odrl/2/#")

    # Query actions
    actions_query = """
    SELECT ?action ?label
    WHERE {
        ?action a odrl:Operator.
        ?action rdfs:label ?label.
    }
    """

    actions = [
        {"uri": str(row.action), "label": str(row.label)}
        for row in g.query(actions_query)
    ]

    return actions

def convert_list_to_odrl_jsonld(data_list):
    odrl_rules = []
    policy = {
        "rule": odrl_rules,
    }
    for data in data_list:
        ruleType = "rule"
        odrl_jsonld = {
            "action": data["action"].split("/")[-1],  # Extract the action type
            "assignee": data["actor"].split("#")[-1],
            "constraint": [],
        }
        for constraint in data["constraints"]:
            odrl_jsonld["constraint"].append(
                {
                    "leftOperand": constraint["type"].split("/")[
                        -1
                    ],  # Extract the constraint type
                    "operator": constraint["operator"].split("/")[-1],
                    "rightOperand": constraint["value"],
                }
            )
        policy[ruleType].append(odrl_jsonld)
    if len(policy["rule"]) == 0:
        del policy["rule"]
    return policy



def convert_list_to_odrl_jsonld_depr(data_list):
    odrl_rules = []
    policy = {
        "rule": odrl_rules,
    }
    for data in data_list:
        if data["action"] is not None and data["actor"] is not None and data["target"] is not None:
            ruleType = "rule"
            targetrefinement = []
            target = ""
            if data["targetrefinements"] is not None:
                target = {"source" : data["target"].split("/")[-1],"refinement": targetrefinement}
            else:
                target = data["target"].split("/")[-1]

            odrl_jsonld = {
                "action": data["action"].split("/")[-1],  # Extract the action type
                "assignee": data["actor"].split("/")[-1],
                "target": target,
                "constraint": [],
            }

            for constraint in data["targetrefinements"]:
                if constraint["operator"] is not None:
                    odrl_jsonld["target"]["refinement"].append(
                        {
                            "leftOperand": constraint["type"].split("/")[
                                -1
                            ],  # Extract the constraint type
                            "operator": constraint["operator"].split("/")[-1],
                            "rightOperand": constraint["value"],
                        }
                    )
            for constraint in data["constraints"]:
                if constraint["operator"] is not None:
                    odrl_jsonld["constraint"].append(
                        {
                            "leftOperand": constraint["type"].split("/")[
                                -1
                            ],  # Extract the constraint type
                            "operator": constraint["operator"].split("/")[-1],
                            "rightOperand": constraint["value"],
                        }
                    )
            policy[ruleType].append(odrl_jsonld)
    if len(policy["rule"]) == 0:
        del policy["rule"]
    return policy

def recursive_replace(data, target_str, replacement_str):
    if isinstance(data, list):
        for i in range(len(data)):
            data[i] = recursive_replace(data[i], target_str, replacement_str)
    elif isinstance(data, dict):
        for key in data:
            data[key] = recursive_replace(data[key], target_str, replacement_str)
    elif isinstance(data, str):
        return data.replace(target_str, replacement_str)
    return data
def convert_list_to_odrl_jsonld_no_user(data_list):
    # data_list = recursive_replace (data_list,"https://w3id.org/dpv/dpv-owl#","https://w3id.org/dpv#")
    # data_list = recursive_replace (data_list,"http://www.w3.org/ns/odrl/2/","")

    odrl_permissions = []
    odrl_prohibitions = []
    odrl_obligations = []
    odrl_duties = []
    odrl_rules = []


    policy = {
        "permission": odrl_permissions,
        "prohibition": odrl_prohibitions,
        "obligation": odrl_obligations,
        "duty": odrl_duties,
        "rule": odrl_rules,
        "uid": "http://example.org/policy-" + str(uuid.uuid4()),
        "@context": [
        "http://www.w3.org/ns/odrl.jsonld",
        {
            "dcat": "http://www.w3.org/ns/dcat#",
            "dpv": "https://w3id.org/dpv/dpv-owl#",
        }
        ],

        "@type": "Policy",
    }
    for data in data_list:
        if data["action"] is not None and data["actor"] is not None and data["target"] is not None:
            if "rule" in data:
                ruleType = str(data["rule"].split("/")[-1]).lower()

                if len(data["actorrefinements"])>0:
                    actor = {"@type":"PartyCollection", "source": data["actor"], "refinement": []}
                else:
                    actor = data["actor"]
                if len(data["actionrefinements"])>0:
                    action = {"source": data["action"], "refinement": []}
                else:
                    action = data["action"]


                if len(data["targetrefinements"])>0:
                    target = {"@type":"AssetCollection", "source": data["target"], "refinement": []}
                else:
                    target = data["target"]

                odrl_jsonld = {
                    "action": action,  # Extract the action type
                    "assignee": actor,
                    "target": target,
                    "constraint": [],
                }

                if len(data["purposerefinements"])>0:

                    purpose = data["purpose"]
                    purposerefinements = {"and":[]}
                    purposerefinements["and"].append({
                        "leftOperand": "purpose",
                        "operator": "http://www.w3.org/ns/odrl/2/eq",
                        "rightOperand": purpose,
                    })

                    for constraint in data["purposerefinements"]:

                        if constraint["operator"] is not None:
                            purposerefinements["and"].append(
                                {
                                    "leftOperand": constraint["type"].split("#")[
                                        -1
                                    ],  # Extract the constraint type
                                    "operator": constraint["operator"],
                                    "rightOperand": constraint["value"],
                                }
                            )

                    odrl_jsonld["constraint"].append(purposerefinements)
                else:
                    purpose = data["purpose"]
                    odrl_jsonld["constraint"].append(
                        {
                            "leftOperand": "purpose",
                            "operator": "http://www.w3.org/ns/odrl/2/eq",
                            "rightOperand": purpose,
                        }
                    )
            else:
                ruleType = "rule"
                odrl_jsonld = {
                    "action": data["action"],  # Extract the action type
                    "assignee": data["actor"],
                    "constraint": [],
                }
            if "query" in data:
                if data["query"] is not '':
                    odrl_jsonld["constraint"].append(
                        {
                            "leftOperand": "ex:query",
                            "operator": "http://www.w3.org/ns/odrl/2/eq",
                            "rightOperand": data["query"],
                        }
                    )
            for constraint in data["constraints"]:
                if constraint["operator"] is not None:
                    odrl_jsonld["constraint"].append(
                        {
                            "leftOperand": constraint["type"].split("#")[
                                -1
                            ],  # Extract the constraint type
                            "operator": constraint["operator"],
                            "rightOperand": constraint["value"],
                        }
                    )
            for constraint in data["actorrefinements"]:
                if constraint["operator"] is not None:
                    print(constraint)
                    print(odrl_jsonld)
                    print(odrl_jsonld["assignee"]["refinement"])
                    print(constraint["type"])
                    print(constraint["operator"])
                    print(constraint["value"])
                    odrl_jsonld["assignee"]["refinement"].append(
                        {
                            "leftOperand": constraint["type"].split("#")[
                                -1
                            ],  # Extract the constraint type
                            "operator": constraint["operator"],
                            "rightOperand": constraint["value"],
                        }
                    )
            for constraint in data["actionrefinements"]:
                if constraint["operator"] is not None:
                    odrl_jsonld["action"]["refinement"].append(
                        {
                            "leftOperand": constraint["type"].split("#")[
                                -1
                            ],  # Extract the constraint type
                            "operator": constraint["operator"],
                            "rightOperand": constraint["value"],
                        }
                    )
            for constraint in data["targetrefinements"]:
                if constraint["operator"] is not None:
                    odrl_jsonld["target"]["refinement"].append(
                        {
                            "leftOperand": constraint["type"].split("#")[
                                -1
                            ],  # Extract the constraint type
                            "operator": constraint["operator"],
                            "rightOperand": constraint["value"],
                        }
                    )
            policy[ruleType].append(odrl_jsonld)
    if len(policy["permission"]) == 0:
        del policy["permission"]
    if len(policy["prohibition"]) == 0:
        del policy["prohibition"]
    if len(policy["obligation"]) == 0:
        del policy["obligation"]
    if len(policy["duty"]) == 0:
        del policy["duty"]
    if len(policy["rule"]) == 0:
        del policy["rule"]
    return policy

def _fetch_valid_status(odrl_policy):
    edge_options = webdriver.EdgeOptions()
    edge_options.add_argument("--headless")

    driver = webdriver.Edge(options=edge_options)
    driver.get("https://odrlapi.appspot.com/")

    WebDriverWait(driver, 50).until(EC.presence_of_element_located((By.ID, "pgn")))
    print(odrl_policy)

    text_area = driver.find_element(By.ID, "pgn")
    text_area.send_keys(odrl_policy)

    time.sleep(3)

    validate_button = driver.find_element(By.XPATH, '//a[@id="boton2"]')
    validate_button.click()

    time.sleep(25)

    WebDriverWait(driver, 100).until(
        EC.invisibility_of_element_located(
            (By.XPATH, '//div[@id="salida"]/pre[text()="No output"]')
        )
    )

    result_element = driver.find_element(By.ID, "salida")
    result = result_element.text

    driver.implicitly_wait(0)
    driver.quit()

    return result


###### custom odrl conversion function ######

ODRL = Namespace("http://www.w3.org/ns/odrl/2/")
DPV = Namespace("https://w3id.org/dpv/dpv-owl#")
EX = Namespace("http://example.org/resource/")

def normalize_odrl_graph(g):
    properties_to_wrap = [ODRL.action, ODRL.assignee, ODRL.assigner, ODRL.target]

    triples_to_add = []
    triples_to_remove = []

    # Step 1: Wrap direct IRIs into blank nodes with odrl:source
    for s, p, o in g:
        if p in properties_to_wrap and isinstance(o, URIRef):
            # Create new blank node
            bn = BNode()
            triples_to_add.append((s, p, bn))
            triples_to_add.append((bn, ODRL.source, o))
            triples_to_remove.append((s, p, o))

    for triple in triples_to_remove:
        g.remove(triple)
    for triple in triples_to_add:
        g.add(triple)

    # Step 2: Replace all blank nodes with fresh IRIs
    bnode_to_iri = {}

    for s, p, o in list(g):
        new_s = bnode_to_iri.get(s, None)
        new_o = bnode_to_iri.get(o, None)

        # Subject replacement
        if isinstance(s, BNode):
            if s not in bnode_to_iri:
                bnode_to_iri[s] = EX[str(uuid.uuid4())]
            new_s = bnode_to_iri[s]

        # Object replacement
        if isinstance(o, BNode):
            if o not in bnode_to_iri:
                bnode_to_iri[o] = EX[str(uuid.uuid4())]
            new_o = bnode_to_iri[o]

        # Only modify if replacements happened
        if new_s or new_o:
            g.remove((s, p, o))
            g.add((new_s if new_s else s, p, new_o if new_o else o))

    return g

def custom_convert_odrl_policy(jsonld_str):
    print("Starting custom conversion of ODRL policy")
    g = Graph()
    g.parse(data=jsonld_str, format='json-ld')
    g = normalize_odrl_graph(g)
    # normalise_here

    results = []

    # Get all rules: Permissions, Prohibitions, Obligations
    rule_types = {
        str(ODRL.Permission): "Permission",
        str(ODRL.Prohibition): "Prohibition",
        str(ODRL.Obligation): "Obligation"
    }

    # Query all rules (permissions, prohibitions, obligations)
    rule_query = """
      SELECT ?rule ?ruleType WHERE {
        ?policy ?predicate ?rule .
        VALUES (?predicate ?ruleType) {
          (odrl:permission odrl:Permission)
          (odrl:prohibition odrl:Prohibition)
          (odrl:obligation odrl:Obligation)
        }
      }
    """
    ns_manager = NamespaceManager(g)
    ns_manager.bind('odrl', ODRL)
    g.namespace_manager = ns_manager

    for row in g.query(rule_query, initNs={'odrl': ODRL}):
        rule_uri = row['rule']
        # print("Processing rule URI:", rule_uri)
        rule_type = str(row['ruleType'])
        # print("Rule type:", rule_type)
        processed_rule = process_rule(g, rule_uri, rule_type)
        # print("Processed rule:", processed_rule)
        results.append(processed_rule)
        # print("Current results:", results)
    
    print(json.dumps(results, indent=2))

    return results


def process_rule(g, rule_uri, rule_type):
    # Helper to run SPARQL query and get first result
    def get_single_value(query, bindings={}):
        qres = g.query(query, initBindings=bindings, initNs={'odrl': ODRL, 'dpv': DPV, 'rdf': RDF})
        for row in qres:
            return str(row[0])
        return ""

    # Get actor (assignee)
    actor_query = """
    SELECT ?actor WHERE {
      <%s> odrl:assignee ?actorNode .
      ?actorNode odrl:source ?actor .
    }
    """ % rule_uri
    actor = get_single_value(actor_query)

    # Get action
    action_query = """
    SELECT ?action WHERE {
      <%s> odrl:action ?actionNode .
      ?actionNode odrl:source | rdf:value ?action .
    }
    """ % rule_uri
    action = get_single_value(action_query)

    # Get target
    target_query = """
    SELECT ?target WHERE {
      <%s> odrl:target ?targetNode .
      ?targetNode odrl:source ?target .
    }
    """ % rule_uri
    target = get_single_value(target_query)

    # Helper to group refinements or constraints by (leftOperand, operator)
    def group_constraints_or_refinements(query):
        result = defaultdict(lambda: {"type": None, "operator": None, "value": ""})
        qres = g.query(query, initNs={'odrl': ODRL, 'dpv': DPV, 'rdf': RDF})
    
        for row in qres:
            left = str(row.left)
            op = str(row.op)
            right = row.right.toPython() if hasattr(row.right, 'toPython') else str(getattr(row.right, 'toPython', lambda: row.right)())
            key = (left, op)
            result[key]["type"] = left if left != "http://www.w3.org/ns/odrl/2/Purpose" else "http://www.w3.org/ns/odrl/2/purpose"
            result[key]["operator"] = op
            result[key]["value"] += str(right)  # Concatenate instead of append
    
        return list(result.values())
    # Get constraints (grouped)
    constraints_query = """
    SELECT ?left ?op ?right WHERE {
      <%s> odrl:constraint ?c .
      ?c odrl:leftOperand ?left ;
         odrl:operator ?op ;
         odrl:rightOperand ?right .
    }
    """ % rule_uri
    constraints = group_constraints_or_refinements(constraints_query)

    # Get actor refinements (grouped)
    actor_ref_query = """
    SELECT ?left ?op ?right WHERE {
      <%s> odrl:assignee ?actorNode .
      ?actorNode odrl:refinement ?ref .
      ?ref odrl:leftOperand ?left ;
           odrl:operator ?op ;
           odrl:rightOperand ?right .
    }
    """ % rule_uri
    actor_refinements = group_constraints_or_refinements(actor_ref_query)

    # Get action refinements (grouped)
    action_ref_query = """
    SELECT ?left ?op ?right WHERE {
      <%s> odrl:action ?actionNode .
      ?actionNode odrl:refinement ?ref .
      ?ref odrl:leftOperand ?left ;
           odrl:operator ?op ;
           odrl:rightOperand ?right .
    }
    """ % rule_uri
    action_refinements = group_constraints_or_refinements(action_ref_query)

    # Get target refinements (grouped) — new
    target_ref_query = """
    SELECT ?left ?op ?right WHERE {
      <%s> odrl:target ?targetNode .
      ?targetNode odrl:refinement ?ref .
      ?ref odrl:leftOperand ?left ;
           odrl:operator ?op ;
           odrl:rightOperand ?right .
    }
    """ % rule_uri
    target_refinements = group_constraints_or_refinements(target_ref_query)

    return {
        "rule": str(rule_type),
        "actor": actor,
        "action": action,
        "target": target,
        "purpose": "",  # Placeholder
        "query": "",    # Placeholder
        "constraints": constraints,
        "actorrefinements": actor_refinements,
        "actionrefinements": action_refinements,
        "targetrefinements": target_refinements,
        "purposerefinements": []
    }