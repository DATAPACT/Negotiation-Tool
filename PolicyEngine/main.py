"""
Author: Semih Yumuşak
Date: March 25, 2024
Description: This is a reference implementation of the engine. Logical pipeline is implemented here.

Contributors:

"""

from flask import Flask, request, jsonify
from Constraint import Constraint
from Parsers import ODRLParser
from PolicyEnforcement import PolicyEnforcement
from ontology import *
from Translators import extract_logic_expressions as logic_expr
app = Flask(__name__)

# Assuming 'policy.odrl' is the file path
file_path = "./examples/policy.odrl"

odrl = ODRLParser()
policies = odrl.parse_file(file_path)

@app.route('/', methods=['GET'])
def index():
    # Read the content of the HTML file
    with open('logic.html', 'r') as file:
        html_content = file.read()
    return html_content
@app.route('/evaluate_odrl', methods=['POST'])
def evaluate_odrl():
    data = request.json
    incoming_request = odrl.parse(data)

    for p in policies:
        pe = PolicyEnforcement(p)
        return pe.enforce_policy(incoming_request)

    pe = PolicyEnforcement(policies)
    for r in incoming_request:
        for perm in r.permission:
            print(pe.check_permission(perm))

conjunction = "∧"
disjunction = "∨"
@app.route('/extract_logic_expressions', methods=['POST'])
def extract_logic_expressions():

    incoming_request = odrl.parse_list(request.json)
    print (incoming_request)
    result = logic_expr(incoming_request)
    return result


@app.route('/evaluate', methods=['POST'])
def evaluate():
    data = request.json
    target = data['target']
    action = data['action']
    context = data['context']
    permission_found = False
    allowed = True
    reason = ""
    for policy in policies:
        for permission in policy.permission:
            if permission.target == target and permission.action == action:
                permission_found = True
                if len(permission.constraint)>0:
                    constraints = permission.constraint if isinstance(permission.constraint, list) else [permission.constraint]
                    if not Constraint.evaluate(constraints, context):
                        allowed = False
                        reason = "Constraint not satisfied for permission"
                if allowed:
                    for duty in permission.duty:
                        if not duty.is_fulfilled(duty, context):
                            allowed = False
                            reason = "Duty not met"
                            break

        if allowed:
            for prohibition in policy.prohibition:
                if prohibition.target == target and prohibition.action == action:
                    if len(prohibition.constraint)>0:
                        constraints = prohibition.constraint if isinstance(prohibition.constraint, list) else [prohibition.constraint]
                        # TODO: check constraints
                        if Constraint.evaluate(constraints, context, "or"):  # Assuming OR logic for prohibition constraints
                            allowed = False
                            reason = "Prohibition applies"
                            break

    if not permission_found:
        allowed = False
        reason = "No applicable permission found"

    return jsonify({"allowed": allowed, "reason": reason})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port="8080")
