import json
import matplotlib.pyplot as plt
from pyld import jsonld
import requests

from rdflib import Graph

def custom_document_loader(url,options):
    # A simple document loader that loads the document from a URL
    response = requests.get(url)
    return {'contextUrl': None, 'document': response.text, 'contentType': 'application/ld+json'}

# Example usage
if __name__ == "__main__":
    jsonld_file = './examples/policy.odrl'  # Path to yo

    from pyld import jsonld
    g = Graph()
    g.parse(jsonld_file, format='json-ld')
    g.serialize(destination="tbl.ttl")
    g.serialize(destination="tbl.json",format="json-ld")

    query = """
 
    PREFIX odrl: <http://www.w3.org/ns/odrl/2/>
    SELECT ?s1 ?p2 ?p3
    WHERE {
        ?subject ?predicate odrl:Policy .
        ?s11 odrl:permission ?p31 . 
        ?s1 ?p2 ?p3 .        
    }
    LIMIT 100
    """

    # Execute the SPARQL query on the RDF graph
    results = g.query(query)

    # Print the query results
    for row in results:
        print(row)

