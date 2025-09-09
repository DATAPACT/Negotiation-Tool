import rdflib
import networkx as nx

def get_purpose_detail(purpose : str):
    purpose = purpose.lower()
    rdf_file_path = "./recommender/purposes.rdf"
    g = rdflib.Graph()
    g.parse(rdf_file_path, format="xml")

    # Define namespaces
    DPV_NS = rdflib.Namespace("https://w3id.org/dpv#")
    SKOS_BROADER = rdflib.URIRef("http://www.w3.org/2004/02/skos/core#broader")

    # Create a directed graph for the purpose hierarchy
    purpose_graph = nx.DiGraph()

    for s, p, o in g.triples((None, rdflib.RDF.type, DPV_NS.Purpose)):
        purpose_name = str(s).replace("https://w3id.org/dpv#", "").lower()  # Convert to lowercase
        purpose_graph.add_node(purpose_name)

        # Find the parent purpose using the `skos:broader` property
        for parent in g.objects(s, SKOS_BROADER):
            parent_name = str(parent).replace("https://w3id.org/dpv#", "").lower()  # Convert to lowercase
            purpose_graph.add_node(parent_name)
            purpose_graph.add_edge(parent_name, purpose_name)  # Edge from parent to child

    # Identify root purposes (nodes with no incoming edges)
    root_purposes = [n for n in purpose_graph.nodes() if purpose_graph.in_degree(n) == 0]
    all_levels = {}

    # Calculate levels for each root purpose
    for root in root_purposes:
        all_levels.update(calculate_levels(purpose_graph, root))

    if purpose in purpose_graph.nodes():
        purpose_level = all_levels.get(purpose, "Unknown")
        
        # Find the parent node (node pointing to input_purpose)
        parents = list(purpose_graph.predecessors(purpose))
        parent_node = parents[0] if parents else "No parent (root node)"
        
        # Find sibling nodes (nodes that share the same parent)
        sibling_nodes = set()
        if parents:
            for sibling in purpose_graph.successors(parents[0]):
                if sibling != purpose:
                    sibling_nodes.add(sibling)

        siblings = ', '.join(sibling_nodes) if sibling_nodes else 'No siblings'
        return purpose_level, parent_node, siblings
    else:
        return None, None, None

def calculate_levels(graph, root):
    """Calculate the level of each purpose in the hierarchy."""
    levels = {}
    queue = [(root, 1)]  # Start with the root node at level 1

    while queue:
        current_node, current_level = queue.pop(0)
        levels[current_node] = current_level  # Assign level to current node
        
        for child in graph.successors(current_node):
            if child not in levels:  # Only process unvisited nodes
                queue.append((child, current_level + 1))  # Increment level for child nodes

    return levels
