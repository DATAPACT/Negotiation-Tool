import os

from rdflib import Graph, Namespace

# Resolve ontology files relative to this module, not the current working dir,
# so that running under different CWD (e.g., /app) doesn’t break file lookups.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ONTOLOGY_DIR = os.path.join(_HERE, "ontology")

dpv_file_path = os.path.join(_ONTOLOGY_DIR, "dpv.rdf")
odrl_file_path = os.path.join(_ONTOLOGY_DIR, "ODRL22.rdf")
odrl_dpv_file_path = os.path.join(_ONTOLOGY_DIR, "ODRL_DPV.rdf")
mdat_ontology_file_path = os.path.join(_ONTOLOGY_DIR, "mdatOntology.owl")
nhrf_ontology_file_path = os.path.join(_ONTOLOGY_DIR, "nhrf.owl")


def get_rules_from_odrl():
    ttl_file_path = odrl_dpv_file_path
    # Parse TTL data
    g = Graph()
    g.parse(ttl_file_path, format="xml")

    # Define namespace
    # odrl = Namespace(
    #     "http://www.w3.org/ns/odrl/2/#"
    # )  # Replace with the actual namespace
    # rdfs = Namespace("http://www.w3.org/2000/01/rdf-schema#")

    # Query for subclasses of :Rule
    subclasses_query = """
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
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
    ttl_file_path = odrl_dpv_file_path
    g = Graph()
    g.parse(ttl_file_path, format="xml")
    g.parse(mdat_ontology_file_path, format="xml")
    g.parse(nhrf_ontology_file_path, format="xml")

    # dpv = Namespace("https://w3id.org/dpv#")
    # skos = Namespace("http://www.w3.org/2004/02/skos/core#")

    # Query for subclasses of :Rule
    subclasses_query = """
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?subClass ?label
        WHERE {
          ?subClass rdfs:subClassOf+ <https://w3id.org/dpv/owl#LegalEntity> .
          ?subClass rdfs:label ?label .
        }
    """

    # Execute the query
    subclasses_result = g.query(subclasses_query)

    # Convert results to a list of dictionaries
    result_list = [
        {"uri": str(row.subClass), "label": str(row.label)} for row in subclasses_result
    ]

    return result_list


def get_purposes_from_dpv():
    ttl_file_path = odrl_dpv_file_path
    # Parse TTL data
    g = Graph()
    g.parse(ttl_file_path, format="xml")
    g.parse(mdat_ontology_file_path, format="xml")
    g.parse(nhrf_ontology_file_path, format="xml")

    # Define namespace
    # dpv = Namespace("https://w3id.org/dpv#")  # Replace with the actual namespace
    # skos = Namespace("http://www.w3.org/2004/02/skos/core#")

    # Query for subclasses of :Rule
    subclasses_query = """
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?subClass ?label
        WHERE {
          ?subClass rdfs:subClassOf <https://w3id.org/dpv/owl#Purpose> .
          ?subClass rdfs:label ?label .
        }
    """

    # Execute the query
    subclasses_result = g.query(subclasses_query)

    # Convert results to a list of dictionaries
    result_list = [
        {"uri": str(row.subClass), "label": str(row.label)} for row in subclasses_result
    ]

    return result_list


def get_constraints_types_from_odrl():
    ttl_file_path = odrl_dpv_file_path
    # Parse TTL data
    g = Graph()
    g.parse(ttl_file_path, format="xml")
    g.parse(mdat_ontology_file_path, format="xml")
    g.parse(nhrf_ontology_file_path, format="xml")

    # Query for subclasses of :Rule
    query = """
        PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
        PREFIX owl:  <http://www.w3.org/2002/07/owl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
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

def get_actions_from_odrl():
    ttl_file_path = odrl_dpv_file_path
    g = Graph()
    g.parse(ttl_file_path, format="xml")
    g.parse(mdat_ontology_file_path, format="xml")
    g.parse(nhrf_ontology_file_path, format="xml")

    odrl_query = """
    PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?action ?label
    WHERE {
        ?action rdfs:subClassOf* odrl:Action .
        ?action rdfs:label ?label .
    }
    """

    dpv_query = """
    PREFIX dpv:  <https://w3id.org/dpv/owl#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?action ?label
    WHERE {
        ?action rdfs:subClassOf+ dpv:Processing .
        ?action rdfs:label ?label .
    }
    """

    actions = []
    for row in g.query(odrl_query):
        actions.append({"uri": str(row.action), "label": str(row.label)})
    for row in g.query(dpv_query):
        actions.append({"uri": str(row.action), "label": str(row.label)})

    # Remove duplicates while preserving order
    seen = set()
    unique_actions = []
    for action in actions:
        if action["uri"] in seen:
            continue
        seen.add(action["uri"])
        unique_actions.append(action)

    return unique_actions


def get_operators_from_odrl():
    ttl_file_path = odrl_dpv_file_path
    # Parse TTL content
    g = Graph()
    g.parse(ttl_file_path, format="xml")
    g.parse(mdat_ontology_file_path, format="xml")
    g.parse(nhrf_ontology_file_path, format="xml")

    # Define namespaces
    # odrl = Namespace("http://www.w3.org/ns/odrl/2/#")

    # Query actions
    actions_query = """
    PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?action ?label
    WHERE {
        ?action a odrl:Operator .
        ?action rdfs:label ?label .
    }
    """

    actions = [
        {"uri": str(row.action), "label": str(row.label)}
        for row in g.query(actions_query)
    ]

    return actions

def get_assets_from_odrl():
    ttl_file_path = odrl_dpv_file_path
    # Parse TTL content
    g = Graph()
    g.parse(ttl_file_path, format="xml")
    g.parse(mdat_ontology_file_path, format="xml")
    g.parse(nhrf_ontology_file_path, format="xml")

    # Define namespaces
    # odrl = Namespace("http://www.w3.org/ns/odrl/2/#")

    # Query actions
    actions_query = """
        PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?action ?label
        WHERE {
            ?action rdfs:subClassOf+ odrl:Asset .
            ?action rdfs:label ?label.
        }
        """

    actions = [
        {"uri": str(row.action), "label": str(row.label)}
        for row in g.query(actions_query)
    ]

    return actions
