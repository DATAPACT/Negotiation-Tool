from Parsers import ODRLParser
from PolicyEnforcement import PolicyEnforcement
from ontology import *

odrl = ODRLParser()
policies = odrl.parse_file("./examples/policy.odrl")

# ----------------------------  SAMPLE CLASS USE ----------------------------------#

file_path = "./examples/request.odrl"

odrl = ODRLParser()
req = odrl.parse_file(file_path)


conjunction = "∧"
disjunction = "∨"
actionTypes = get_actions_from_odrl()
actorTypes = get_actors_from_dpv()
purposeTypes = get_purposes_from_dpv()

print("----------------------------ACTOR-----------------------")
for a in actorTypes:
    print(a)

print("----------------------------ACTION-----------------------")
for a in actionTypes:
    print(a)

print("----------------------------purpose-----------------------")
for a in purposeTypes:
    print(a)

def check(i,list):
    for a in list:
        if a["label"].lower() == i.lower() or a["uri"].lower() == i.lower():
            return True
def get(i, list):
    for a in list:
        if a["label"].lower() == i.lower() or a["uri"].lower() == i.lower():
            return a["label"].replace(" ","")

def extract_logic_expressions():

    policies = odrl.parse_file("./Examples/consent.odrl")
    logic_expression = ""
    logic_op = conjunction
    y = 0
    for p in policies:
        for proh in p.prohibition:
            if check(proh.target, actorTypes):
                function_name = get(proh.target, actorTypes)
                logic_expression += f"hasActor (x,y{y}) {logic_op} {function_name} (y{y}) {logic_op} "
                y += 1
            if check(proh.action, actionTypes):
                function_name = get(proh.action, actionTypes)
                logic_expression += f"hasAction (x,y{y}) {logic_op} {function_name} (y{y}) {logic_op} "
                y += 1
            for c in proh.constraint:
                if check(c.rightOperand, purposeTypes):
                    function_name = get(c.rightOperand, purposeTypes)
                    logic_expression += f"hasPurpose (x,y{y}) {logic_op} {function_name} (y{y}) {logic_op} "
                    y += 1
    logic_expression = logic_expression [:-2]

extract_logic_expressions()


pe = PolicyEnforcement(policies)
for r in req:
    print(pe.check_permission(r.permission))


from Constraint import ArithmeticConstraint
from Policy import Rule, Permission, Prohibition, Duty, Policy
from Refinables import Action, AssetCollection, PartyCollection


# Creating an Action instance
action1 = Action("read")
constraint1 = ArithmeticConstraint(leftOperand="count", operator="gteq", rightOperand=5) # Number of action is equal to or greater than 5.
action1.add_refinement(constraint1)

action2 = Action("compensate")
constraint2 = ArithmeticConstraint(leftOperand="amount", operator="eq", rightOperand="10.0EUR")
action2.add_refinement(constraint2)
# This action is to pay 10 EUR.

# Creating AssetCollection instances
assets1 = AssetCollection("Library")
constraint2 = ArithmeticConstraint("rdf:type", "eq", rightOperand="book")
assets1.add_refinement(constraint2)
# This asset collection is comprised by all elements that are books (i.e., of rdf:type book),

# Creating PartyCollection instances
party1 = PartyCollection("Staff")
constraint3 = ArithmeticConstraint("foaf:occupation", "eq", rightOperand="librarian")
party1.add_refinement(constraint3)
party2 = PartyCollection("User")

# Creating Rule instances
rule1 = Rule(action=action1, target=assets1, assigner=party1)

# Creating a Permission instance
permission1 = Permission(target=assets1, action=action1, assigner=party1, assignee=party1)

# Creating a Prohibition instance
prohibition1 = Prohibition(target=assets1, action=action1, assigner=party1, assignee=party1)

# Creating Duty instances
duty1 = Duty(target=assets1, action=action1, assigner=party1, assignee=party1)
remedy_action = Duty(action=action2)
duty_action = Duty(action=Action("notify"))

# Creating a Policy instance
policy1 = Policy(uid="policy1")
policy1.addRule(rule1)

# Adding a constraint to the Duty instance
constraint4 = ArithmeticConstraint("datetime", "lt", rightOperand="2023-06-01T12:00:00Z")
duty1.add_constraint(constraint4)

# Removing a constraint from the Duty instance
duty1.remove_constraint(constraint4)

# Activating a Rule
rule1.activate()

# Deactivating a Rule
rule1.deactivate()

# Checking if a Rule is active
is_active = rule1.is_active()

# Setting duty for Permission
permission1.set_duty(duty_action)

# Clearing duty for Permission
permission1.clear_duty()

# Checking if a Prohibition is violated
is_violated = prohibition1.is_violated()

# Setting remedy for Prohibition
prohibition1.set_remedy(remedy_action)

# Clearing remedy for Prohibition
prohibition1.clear_remedy()

# Adding an implied action to an Action
implied_action = Action("log")
action1.add_implied_action(implied_action)
