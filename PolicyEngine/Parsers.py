"""
Author: Semih Yumuşak
Date: March 25, 2024
Description: This is the constraint package which has logical and arithmetic constraint implementations.

Contributors:

"""
import json
from .Policy import Policy, Rule, Permission, Obligation, Duty, Prohibition

class PolicyObject:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class ODRLParser:

    def parse_file(self,file_name):
        if file_name is not None:
            file_name = file_name
        with open(file_name, 'r') as file:
            parsed_policy = json.load(file)

        # with open(file_name, 'r') as file:
        #     parsed_policy_object = json.load(file,object_hook = lambda d: Policy(**d))
        list_of_policies = []
        for p in parsed_policy:
            list_of_policies.append(self.parse(p))

        return list_of_policies


    def parse_list(self,parsed_policy):
        list_of_policies = []
        if isinstance(parsed_policy, str):
            parsed_policy = json.loads(parsed_policy)
        for p in parsed_policy:
            list_of_policies.append(self.parse(p))

        return list_of_policies

    def parse(self,parsed_policy):
        policy = Policy(parsed_policy["uid"], parsed_policy["@type"])
        for key, value in parsed_policy.items():
            if key == "prohibition":
                policy.prohibition = self.__parse_rule(key, value)
            if key == "permission":
                policy.permission = self.__parse_rule(key, value)
            if key == "duty":
                policy.duty = self.__parse_rule(key, value)
            if key == "obligation":
                policy.obligation = self.__parse_rule(key,value)
        return policy

    def __parse_rule(self,type,rule):
        if type == "prohibition":
            return [Prohibition(**r) for r in rule]
        if type == "permission":
            return [Permission(**r) for r in rule]
        if type == "duty":
            return [Duty(**r) for r in rule]
        if type == "obligation":
            return [Obligation(**r) for r in rule]

    def __parse_refinable(self,type,refinable):
        pass

    def __parse_constraint(self,type,constraint):
        pass
