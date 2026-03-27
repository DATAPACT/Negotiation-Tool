













import json
from rdflib import Graph, Namespace, RDF, URIRef
from rdflib.namespace import RDFS

# JSON-LD data for permission and prohibition
permission_jsonld = {
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

prohibition_jsonld = {
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

# Create an RDF graph and parse the JSON-LD data
g = Graph()
g.parse(data=json.dumps(permission_jsonld), format='json-ld')
g.parse(data=json.dumps(prohibition_jsonld), format='json-ld')


print(g.serialize(format='turtle'))


sparql_query_debug = """
PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
PREFIX dpv: <https://w3id.org/dpv/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?policy ?permission ?conflictingPolicy ?prohibition
WHERE {
  ?policy a odrl:Policy ;
          odrl:permission ?permission .
  ?conflictingPolicy a odrl:Policy ;
                     odrl:prohibition ?prohibition .
}
"""

sparql_query_debug = """
PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
SELECT ?policy ?permission ?conflictingPolicy ?prohibition ?action ?prohibitionAction
WHERE {
  ?policy a odrl:Policy ;
          odrl:permission ?permission .
  ?permission odrl:action ?action .
  ?conflictingPolicy a odrl:Policy ;
                     odrl:prohibition ?prohibition .
  ?prohibition odrl:action ?prohibitionAction .
  FILTER (?policy != ?conflictingPolicy)
}
"""

sparql_query_debu1g = """
PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
PREFIX dpv: <https://w3id.org/dpv/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?policy ?conflictingPolicy
WHERE {
  ?policy a odrl:Policy ;
          odrl:permission ?permission .
  ?permission odrl:action ?action ;
              odrl:assignee ?assignee ;
              odrl:target ?target ;
              odrl:constraint ?constraint .

  ?conflictingPolicy a odrl:Policy ;
                     odrl:prohibition ?prohibition .
  ?prohibition odrl:action ?prohibitionAction ;
               odrl:assignee ?assignee ;
               odrl:target ?target ;
               odrl:constraint ?constraint .

  FILTER (?policy = ?conflictingPolicy)
}
"""

sparql_query_debug = """
PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
PREFIX dpv: <https://w3id.org/dpv/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?action ?prohibitionAction ?assignee ?assignee2 
WHERE {
  ?policy a odrl:Policy ;
          odrl:permission ?permission .
  ?conflictingPolicy a odrl:Policy ;
          odrl:prohibition ?prohibition .

  ?permission odrl:action ?action ;
              odrl:assignee ?assignee ;
              odrl:target ?target ;
              odrl:constraint ?constraint .

  ?prohibition odrl:action ?prohibitionAction ;
               odrl:assignee ?assignee ;
               odrl:target ?target2 ;
               odrl:constraint ?constraint2 .

  FILTER (?action = ?prohibitionAction
          )
}
"""

# Run the SPARQL query
results_debug = g.query(sparql_query_debug)

# Print the debug results
for row in results_debug:
    print (row)
    print(f"Policy: {row.policy}, Permission: {row.permission}, Conflicting Policy: {row.conflictingPolicy}, Prohibition: {row.prohibition}")


# Define the SPARQL query to find conflicting permissions and prohibitions considering superclass relationships
sparql_query = """
PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
PREFIX dpv: <https://w3id.org/dpv/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?policy ?conflictingPolicy
WHERE {
  ?policy a odrl:Policy ;
          odrl:permission ?permission .
  ?permission odrl:action ?action ;
              odrl:assignee ?assignee ;
              odrl:target ?target ;
              odrl:constraint ?constraint .

  ?conflictingPolicy a odrl:Policy ;
                     odrl:prohibition ?prohibition .
  ?prohibition odrl:action ?prohibitionAction ;
               odrl:assignee ?assignee ;
               odrl:target ?target ;
               odrl:constraint ?constraint .
  
  FILTER (?policy != ?conflictingPolicy)
}
"""
# ?prohibitionAction rdfs:subPropertyOf* ?action .
# Run the SPARQL query
results = g.query(sparql_query)

# Print the results
for row in results:
    print(f"Policy: {row.policy}, Conflicting Policy: {row.conflictingPolicy}")
