from typing import List, Union
from datetime import datetime

from .Parsers import ODRLParser
from .Refinables import Action
from .Policy import Policy, Permission, Prohibition, Obligation, Duty


class PolicyEnforcement:
    def __init__(self, policies: List[Policy]):
        self.policies = policies


    # def check_permission(self, permission_list:List[Permission]) -> bool:
    #     """
    #     Checks if the given action is permitted according to any of the policies.
    #
    #     :param action: The action to be checked.
    #     :param target: The target of the action.
    #     :param assigner: The entity attempting the action.
    #     :param assignee: Optional; the entity to whom the action is assigned.
    #     :return: True if the action is permitted, False otherwise.
    #     """
    #     results = []
    #     for perm in permission_list:
    #         for policy in self.policies:
    #             for permission in policy.permission:
    #                 if permission.target == perm.target and permission.assigner == perm.assigner:
    #                     if perm.assignee is None or permission.assignee == perm.assignee:
    #                         if permission.action == perm.action:
    #                             return (policy.uid, True)
    #     return (policy.uid, False)
    def check_permission(self, action: str, target: str, assigner: str, assignee: str = None) -> bool:
        """
        Checks if the given action is permitted according to any of the policies.

        :param action: The action to be checked.
        :param target: The target of the action.
        :param assigner: The entity attempting the action.
        :param assignee: Optional; the entity to whom the action is assigned.
        :return: True if the action is permitted, False otherwise.
        """
        for policy in self.policies:
            for permission in policy.permission:
                if permission.target == target and permission.assigner == assigner:
                    if assignee is None or permission.assignee == assignee:
                        try:
                            if any(act.title == action for act in permission.action):
                                return True
                        except:
                            if permission.action == action:
                                return True
        return False

    def check_prohibition(self, action: str, target: str, assigner: str, assignee: str = None) -> bool:
        """
        Checks if the given action is prohibited according to any of the policies.

        :param action: The action to be checked.
        :param target: The target of the action.
        :param assigner: The entity attempting the action.
        :param assignee: Optional; the entity to whom the action is assigned.
        :return: True if the action is prohibited, False otherwise.
        """

        for policy in self.policies:
            for prohibition in policy.prohibition:
                if prohibition.target == target and prohibition.assigner == assigner:
                    if assignee is None or prohibition.assignee == assignee:
                        try:
                            if any(act.title == action for act in prohibition.action):
                                return True
                        except:
                            if prohibition.action == action:
                                return True
        return False

    def enforce_policy(self, action: str, target: str, assigner: str, assignee: str = None) -> Union[str, None]:
        """
        Enforces the policies by checking if the given action is permitted, prohibited, or neither.

        :param action: The action to be checked.
        :param target: The target of the action.
        :param assigner: The entity attempting the action.
        :param assignee: Optional; the entity to whom the action is assigned.
        :return: "Permitted" if the action is permitted, "Prohibited" if the action is prohibited, None otherwise.
        """
        if self.check_permission(action=action, target=target, assigner=assigner, assignee=assignee):
            return "Permitted"
        elif self.check_prohibition(action, target, assigner, assignee):
            return "Prohibited"
        else:
            return None

    # def enforce_policy(self, policy:Policy):
    #     """
    #     Enforces the policies by checking if the given action is permitted, prohibited, or neither.
    #
    #     :param action: The action to be checked.
    #     :param target: The target of the action.
    #     :param assigner: The entity attempting the action.
    #     :param assignee: Optional; the entity to whom the action is assigned.
    #     :return: "Permitted" if the action is permitted, "Prohibited" if the action is prohibited, None otherwise.
    #     """
    #     if self.check_permission(policy.permission.action, policy.permission.target, policy.permission.assigner, policy.permission.assignee):
    #         return "Permitted"
    #     elif self.check_prohibition(policy.permission.action, policy.permission.target, policy.permission.assigner, policy.permission.assignee):
    #         return "Prohibited"
    #     else:
    #         return None


# Example usage:
if __name__ == "__main__":
    file_path = "./examples/policy.odrl"

    odrl = ODRLParser()
    policies = odrl.parse_file(file_path)

    # # Example policies
    # policy1 = Policy(uid="1", type="Example", permission=[Permission(target="resource", action=[Action(name="read")],
    #                                                                  assigner="user", assignee="admin")])
    # policy2 = Policy(uid="2", type="Example", prohibition=[Prohibition(target="resource", action=[Action(name="delete")],
    #                                                                     assigner="user", assignee="admin")])
    # policies = [policy1, policy2]

    # Creating an instance of PolicyEnforcement
    policy_enforcement = PolicyEnforcement(policies)

    # Checking permissions
    print(policy_enforcement.enforce_policy(action="read", target="http://example.com/asset:123", assigner="http://example.com/user", assignee="http://example.com/admin"))  # Output: Permitted
    print(policy_enforcement.enforce_policy("write", "http://example.com/asset:123", "http://example.com/user", "http://example.com/admin"))  # Output: None

    # Checking prohibitions
    print(policy_enforcement.enforce_policy("delete", "http://example.com/book/1999", "http://example.com/user", "http://example.com/admin"))  # Output: Prohibited
    print(policy_enforcement.enforce_policy("update", "http://example.com/book/1999", "http://example.com/user", "http://example.com/admin"))  # Output: None
