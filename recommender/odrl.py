import rdflib
import networkx as nx

def calculate_levels(action_graph):
        """Calculate the level of each action in the hierarchy."""
        levels = {}
        root_actions = [n for n in action_graph.nodes() if action_graph.in_degree(n) == 0]  # Identify root actions
        
        for root in root_actions:
            queue = [(root, 1)]  # Start with the root node at level 1
            while queue:
                current_node, current_level = queue.pop(0)
                levels[current_node] = current_level  # Assign level to current node
                
                for child in action_graph.successors(current_node):
                    if child not in levels:  # Only process unvisited nodes
                        queue.append((child, current_level + 1))  # Increment level for child nodes

        return levels

def get_action_detail(action : str): 
    # Load the RDF file
    rdf_file_path = "./recommender/ODRL22.rdf"
    g = rdflib.Graph()
    g.parse(rdf_file_path, format="xml")

    # Define namespaces
    ODRL_NS = rdflib.Namespace("http://www.w3.org/ns/odrl/2/")
    INCLUDED_IN = rdflib.URIRef("http://www.w3.org/ns/odrl/2/includedIn")

    # Create a directed graph for the action hierarchy
    action_graph = nx.DiGraph()

    # Extract actions and their hierarchy
    for s, p, o in g.triples((None, rdflib.RDF.type, ODRL_NS.Action)):
        action_name = str(s).replace("http://www.w3.org/ns/odrl/2/", "").lower()  # Convert to lowercase
        action_graph.add_node(action_name)

        # Find the parent action using the `includedIn` property
        for parent in g.objects(s, INCLUDED_IN):
            parent_name = str(parent).replace("http://www.w3.org/ns/odrl/2/", "").lower()  # Convert to lowercase
            action_graph.add_node(parent_name)
            action_graph.add_edge(parent_name, action_name)  # Edge from parent to child

    # Calculate levels for all actions in the graph
    action_levels = calculate_levels(action_graph)

    # Get user input for the action name
    # input_action = input("Enter the name of the action: ").strip().lower()  # Convert input to lowercase

    if action in action_graph.nodes():
        action_level = action_levels.get(action, "Unknown")
        
        # Find the parent node (node pointing to action)
        parents = list(action_graph.predecessors(action))
        parent_node = parents[0] if parents else "No parent (root node)"
        
        # Find sibling nodes (nodes that share the same parent)
        sibling_nodes = set()
        if parents:
            for sibling in action_graph.successors(parents[0]):
                if sibling != action:
                    sibling_nodes.add(sibling)

        siblings = ', '.join(sibling_nodes) if sibling_nodes else 'No siblings'
        return action_level, parent_node, siblings
        # Display results
        # print(f"The level of '{action}' in the hierarchy: {action_level}")
        # print(f"Parent node: {parent_node}")
        # print(f"Sibling nodes: {', '.join(sibling_nodes) if sibling_nodes else 'No siblings'}")

    else:
        return None
        # print(f"The action '{input_action}' does not exist in the graph.")