import re

from .Interfaces import TranslatorInterface
from .Parsers import ODRLParser
from .Policy import Rule
from .PolicyEnforcement import PolicyEnforcement
from .Refinables import PartyCollection, AssetCollection
from .ontology import *



class LogicTranslator():
    def __init__(self):
        self.odrl = ODRLParser()
        self.conjunction = "∧"
        self.disjunction = "∨"
        self.actionTypes = get_actions_from_odrl()
        self.actorTypes = get_actors_from_dpv()
        self.purposeTypes = get_purposes_from_dpv()

    def __check(self, i,list):
        if isinstance(i,str):
            pass
        elif type(i) is type([]):
            i = i[0].source
        else:
            i = i.source
        for a in list:
            if a["label"].lower() == i.lower() or a["uri"].lower() == i.lower():
                return True
    def __get(self, i, list):
        if isinstance(i,str):
            pass
        elif type(i) is type([]):
            i = i[0].source
        else:
            i = i.source

        for a in list:
            if a["label"].lower() == i.lower() or a["uri"].lower() == i.lower():
                return a["label"].replace(" ","")

    def __extract_constraints_logic(self, x1,x2, constraint):
        logic_expression = ""

        try:
            lo = constraint.leftOperand.split("/")[-1].split("#")[-1]
            ro = constraint.rightOperand.split("/")[-1].split("#")[-1]
            op = constraint.operator
            if lo == "purpose" or constraint.operator.split("/")[-1].split("#")[-1] == "isA":
                logic_expression += f"has{lo.capitalize()} ({x1},x{x2}) {self.conjunction} {ro}(x{x2}) {self.conjunction} "
            else:
                logic_expression += f"has{lo.capitalize()} ({x1},x{x2}) {self.conjunction} x{x2} {self.__get_formal_logic_operator(op)} {ro} {self.conjunction} "
        except BaseException as b:
            if constraint.logic_and is not None:
                for a in constraint.logic_and:
                    lo = a['leftOperand'].split("/")[-1].split("#")[-1]
                    ro = a['rightOperand'].split("/")[-1].split("#")[-1]
                    op = a['operator']
                    if lo == "purpose" or constraint.operator.split("/")[-1].split("#")[-1] == "isA":
                        logic_expression += f"has{lo.capitalize()} ({x1},x{x2}) {self.conjunction} {ro}(x{x2}) {self.conjunction} "
                    else:
                        logic_expression += f"has{lo.capitalize()} ({x1},x{x2}) {self.conjunction} x{x2} {self.__get_formal_logic_operator(op)} {ro} {self.conjunction} "
        return logic_expression
    def __get_formal_logic_operator(self, uri):
        operators = {
            "http://www.w3.org/ns/odrl/2/eq": "=",
            "http://www.w3.org/ns/odrl/2/gt": ">",
            "http://www.w3.org/ns/odrl/2/gteq": "≥",
            "http://www.w3.org/ns/odrl/2/hasPart": "has part",
            "http://www.w3.org/ns/odrl/2/isA": "is a",
            "http://www.w3.org/ns/odrl/2/isAllOf": "∧",
            "http://www.w3.org/ns/odrl/2/isAnyOf": "∨",
            "http://www.w3.org/ns/odrl/2/isNoneOf": "¬",
            "http://www.w3.org/ns/odrl/2/isPartOf": "is part of",
            "http://www.w3.org/ns/odrl/2/lt": "<",
            "http://www.w3.org/ns/odrl/2/lteq": "≤",
            "http://www.w3.org/ns/odrl/2/neq": "≠"
        }
        return operators.get(uri, "Unknown")
    def __extract_logic_expressions_from_file(self, file = "./Examples/consent.odrl"):
        policies = self.odrl.parse_file(file)
        return self.translate_policy(policies)
    def translate_policy(self, policies: []):

        logic_list = []

        x = 0
        for p in policies:
            #results = []
            i = 1
            for r in p.prohibition:
                i, x, lst = self.__parse_rule("Prohibition", r, i, x, logic_list)
                logic_list = lst
            for r in p.permission:
                i, x, lst = self.__parse_rule("Permission", r, i, x, logic_list)
                logic_list = lst
            for r in p.obligation:
                i, x, lst = self.__parse_rule("Obligation", r, i, x, logic_list)
                logic_list = lst
                #results.append({"uid":id,"rule":logic_expression})

        return logic_list

    def __parse_rule(self, type: str, rule: object, i: int, x: int, logic_list: []):
        try:
            logic_op = self.conjunction
            id = f"{type[:2]}{i}"
            logic_expression = f"{type}({id}) {logic_op} "
            query = ""
            i += 1

            for c in rule.constraint:
                try:
                    if c.leftOperand == "ex:query":
                        query = c.rightOperand
                except:
                    pass
            if query == "":
                if isinstance(rule.target, str):
                    query = rule.target
                else:
                    query = rule.target.source
            # query = proh.target
            query_parts = query.split(":-")
            if len(query_parts) > 1:
                id = query.split("(")[0]

                inputs = query_parts[0].split("(")[1].replace(")", "")

                pattern = r'Table\d+\([^)]+\)'
                tables = re.findall(pattern, query_parts[1])

                logic_expression += f"hasTarget({id}, {inputs})  {logic_op} "
                for table in tables:
                    logic_expression += f"{table.strip()}  {logic_op} "
            else:
                target = query.split("/")[-1].split("#")[-1]
                #                    logic_expression += f"hasTarget({id}, {target})  {logic_op} "
                logic_expression += f"hasTarget ({id},x{x}) {logic_op} {target} (x{x}) {logic_op} "
                if isinstance(rule.target, AssetCollection):
                    x_temp = x
                    for ref in rule.target.refinement:
                        logic_expression += self.__extract_constraints_logic(f'x{x_temp}', x+1, ref)
                        x += 1
                x += 1

            if self.__check(rule.assignee, self.actorTypes):
                function_name = self.__get(rule.assignee, self.actorTypes)
                logic_expression += f"hasActor ({id},x{x}) {logic_op} {function_name} (x{x}) {logic_op} "
                if isinstance(rule.assignee, PartyCollection):
                    for ref in rule.assignee.refinement:
                        x_temp = x
                        logic_expression += self.__extract_constraints_logic(f'x{x_temp}', x + 1, ref)
                        x += 1
                        # logic_expression += f"has{ref.other['leftOperand']} (x{x}, y{x}) {logic_op} y{x} {get_formal_logic_operator(ref.other['operator'])} {ref.other['rightOperand']} {logic_op} "
                x += 1
            if self.__check(rule.action, self.actionTypes):
                function_name = self.__get(rule.action, self.actionTypes)
                logic_expression += f"hasAction ({id},x{x}) {logic_op} {function_name} (x{x}) {logic_op} "
                if not isinstance(rule.action, str):
                    for ref in rule.action[0].refinement:
                        x_temp = x
                        logic_expression += self.__extract_constraints_logic(f'x{x_temp}', x + 1, ref)
                        x += 1
                x += 1
            for c in rule.constraint:
                logic_expression += self.__extract_constraints_logic(id, x, c)
                # if c.logic_and:
                #     pass
                # if check(c.rightOperand, purposeTypes):
                #     function_name = get(c.rightOperand, purposeTypes)
                #     logic_expression += f"hasPurpose ({id},x{x}) {logic_op} {function_name} (x{x}) {logic_op} "
                x += 1
            logic_expression = logic_expression[:-2]
            logic_list.append(logic_expression)
        except BaseException as b:
            print(b)
            pass
        return i, x, logic_list

class RegoTranslator():
    def __init__(self):
        self.odrl = ODRLParser()
        self.conjunction = "∧"
        self.disjunction = "∨"
        self.actionTypes = get_actions_from_odrl()
        self.actorTypes = get_actors_from_dpv()
        self.purposeTypes = get_purposes_from_dpv()

    def __check(self, i, lst):
        if isinstance(i, str):
            pass
        elif isinstance(i, list):
            i = i[0].source
        else:
            i = i.source
        for a in lst:
            if a["label"].lower() == i.lower() or a["uri"].lower() == i.lower():
                return True

    def __get(self, i, lst):
        if isinstance(i, str):
            pass
        elif isinstance(i, list):
            i = i[0].source
        else:
            i = i.source
        for a in lst:
            if a["label"].lower() == i.lower() or a["uri"].lower() == i.lower():
                return a["label"].replace(" ", "")

    def __extract_constraints_rego(self, x1, x2, constraint):
        rego_expression = ""
        try:
            lo = constraint.leftOperand.split("/")[-1].split("#")[-1]
            ro = constraint.rightOperand.split("/")[-1].split("#")[-1]
            op = self.__get_formal_rego_operator(constraint.operator)
            if lo == "purpose" or constraint.operator.split("/")[-1].split("#")[-1] == "isA":
                rego_expression += f"has_{lo}({x1}, x{x2}) {ro}(x{x2}) "
            else:
                rego_expression += f"has_{lo}({x1}, x{x2}) {op} {ro} "
        except:
            if constraint.logic_and is not None:
                for a in constraint.logic_and:
                    lo = a['leftOperand'].split("/")[-1].split("#")[-1]
                    ro = a['rightOperand'].split("/")[-1].split("#")[-1]
                    op = self.__get_formal_rego_operator(a['operator'])
                    if lo == "purpose" or a['operator'].split("/")[-1].split("#")[-1] == "isA":
                        rego_expression += f"has_{lo}({x1}, x{x2}) {ro}(x{x2}) "
                    else:
                        rego_expression += f"has_{lo}({x1}, x{x2}) {op} {ro} "
        return rego_expression

    def __get_formal_rego_operator(self, uri):
        operators = {
            "http://www.w3.org/ns/odrl/2/eq": "==",
            "http://www.w3.org/ns/odrl/2/gt": ">",
            "http://www.w3.org/ns/odrl/2/gteq": ">=",
            "http://www.w3.org/ns/odrl/2/lt": "<",
            "http://www.w3.org/ns/odrl/2/lteq": "<=",
            "http://www.w3.org/ns/odrl/2/neq": "!="
        }
        return operators.get(uri, "Unknown")

    def __extract_rego_expressions_from_file(self, file="./Examples/consent.odrl"):
        policies = self.odrl.parse_file(file)
        return self.translate_policy(policies)

    def translate_policy(self, policies):
        rego_list = []
        x = 0
        for p in policies:
            i = 1
            for r in p.prohibition:
                i, x, lst = self.__parse_rule("Prohibition", r, i, x, rego_list)
                rego_list = lst
            for r in p.permission:
                i, x, lst = self.__parse_rule("Permission", r, i, x, rego_list)
                rego_list = lst
            for r in p.obligation:
                i, x, lst = self.__parse_rule("Obligation", r, i, x, rego_list)
                rego_list = lst
        return rego_list

    def __parse_rule(self, type, rule, i, x, rego_list):
        try:
            logic_op = "&&"
            id = f"{type[:2]}{i}"
            rego_expression = f"{type}({id}) {{ {logic_op} "
            query = ""
            i += 1

            for c in rule.constraint:
                try:
                    if c.leftOperand == "ex:query":
                        query = c.rightOperand
                except:
                    pass
            if query == "":
                if isinstance(rule.target, str):
                    query = rule.target
                else:
                    query = rule.target.source
            query_parts = query.split(":-")
            if len(query_parts) > 1:
                id = query.split("(")[0]
                inputs = query_parts[0].split("(")[1].replace(")", "")
                pattern = r'Table\d+\([^)]+\)'
                tables = re.findall(pattern, query_parts[1])
                rego_expression += f"has_target({id}, {inputs}) {logic_op} "
                for table in tables:
                    rego_expression += f"{table.strip()} {logic_op} "
            else:
                target = query.split("/")[-1].split("#")[-1]
                rego_expression += f"has_target({id}, x{x}) {logic_op} {target}(x{x}) {logic_op} "
                if isinstance(rule.target, AssetCollection):
                    x_temp = x
                    for ref in rule.target.refinement:
                        rego_expression += self.__extract_constraints_rego(f'x{x_temp}', x + 1, ref)
                        x += 1
                x += 1

            if self.__check(rule.assignee, self.actorTypes):
                function_name = self.__get(rule.assignee, self.actorTypes)
                rego_expression += f"has_actor({id}, x{x}) {logic_op} {function_name}(x{x}) {logic_op} "
                if isinstance(rule.assignee, PartyCollection):
                    for ref in rule.assignee.refinement:
                        x_temp = x
                        rego_expression += self.__extract_constraints_rego(f'x{x_temp}', x + 1, ref)
                        x += 1
                x += 1

            if self.__check(rule.action, self.actionTypes):
                function_name = self.__get(rule.action, self.actionTypes)
                rego_expression += f"has_action({id}, x{x}) {logic_op} {function_name}(x{x}) {logic_op} "
                if not isinstance(rule.action, str):
                    for ref in rule.action[0].refinement:
                        x_temp = x
                        rego_expression += self.__extract_constraints_rego(f'x{x_temp}', x + 1, ref)
                        x += 1
                x += 1

            for c in rule.constraint:
                rego_expression += self.__extract_constraints_rego(id, x, c)
                x += 1
            rego_expression = rego_expression[:-4] + "}"
            rego_list.append(rego_expression)
        except BaseException as b:
            print(b)
            pass
        return i, x, rego_list
