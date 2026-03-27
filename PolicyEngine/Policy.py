"""
Author: Semih Yumuşak
Date: March 25, 2024
Description: This is file containing Policy and rule classes.

Contributors:

"""
from typing import Union, Optional

from .Refinables import Action
from .Refinables import AssetCollection
from .Refinables import PartyCollection
from .Constraint import Constraint

class Rule:
    def __init__(self, action: Action = None, target: AssetCollection = None, assigner: Union[PartyCollection, None] = None, assignee: Union[PartyCollection, None] = None, constraint: list[Union[Constraint, 'LogicalConstraint']] = None, uid: str = None):
        """
        Initializes a Rule instance.

        :param action: The action associated with the Rule.
        :param target: Optional; the target AssetCollection associated with the Rule.
        :param assigner: Optional; the assigner PartyCollection associated with the Rule.
        :param assignee: Optional; the assignee PartyCollection associated with the Rule.
        :param constraints: Optional list of Constraint or LogicalConstraint objects associated with the Rule.
        :param uid: Optional; the unique identifier of the Rule.
        """
        try:
            if isinstance(action, dict):
                self.action = [Action(**action)]
            elif isinstance(action, list):
                self.action = [Action(**c) for c in action]
            else:
                self.action = action
        except:
            self.action = action

        try:
            if isinstance(target, dict):
                self.target = AssetCollection(**target)
            else:
                self.target = target
        except:
            self.target = target

        self.assigner = assigner

        if isinstance(assignee, dict):
            self.assignee = PartyCollection(**assignee)
        else:
            self.assignee = assignee

        if constraint is None:
            self.constraint = []
        elif isinstance(constraint, list):
            self.constraint = [Constraint(**c) for c in constraint]
        elif isinstance(constraint, dict):
            self.constraint = [Constraint(**constraint)]

        self.type = type
        self.uid = uid
        self.state = "Inactive"  # Default state is Inactive

    def add_constraint(self, constraint: Union[Constraint, 'LogicalConstraint']):
        """
        Adds a constraint to the Rule.

        :param constraint: Constraint or LogicalConstraint object to be added.
        """
        self.constraint.append(constraint)

    def remove_constraint(self, constraint: Union[Constraint, 'LogicalConstraint']):
        """
        Removes a constraint from the Rule.

        :param constraint: Constraint or LogicalConstraint object to be removed.
        """
        if constraint in self.constraint:
            self.constraint.remove(constraint)

    def clear_constraint(self):
        """
        Clears all constraints associated with the Rule.
        """
        self.constraint = []

    def activate(self):
        """
        Activates the Rule.
        """
        self.state = "Active"

    def deactivate(self):
        """
        Deactivates the Rule.
        """
        self.state = "Inactive"

    def is_active(self) -> bool:
        """
        Checks if the Rule is active.

        :return: True if the Rule is active, False otherwise.
        """
        return self.state == "Active"

    def type(self):
        return self.__class__

class Duty(Rule):
    def __init__(self, target = None, action=None, assigner=None, assignee=None, constraint=None, consequence=None, **args):
        """
        Initializes a Duty instance, extending the Rule class with additional properties
        for action, constraints, and a potential consequence.

        :param target: The object or entity the duty applies to.
        :param action: The primary action associated with the duty.
        :param assigner: The entity that imposes the duty.
        :param assignee: The entity obligated to fulfill the duty.
        :param consequence: Optional; another Duty (or Rule) instance representing the consequence of not fulfilling the duty.
        :param action: Optional; a list of additional Action objects associated with the duty.
        :param constraints: Optional; a list of Constraint objects specifying conditions under which the duty applies.
        """
        self.set_consequence(consequence)
        super().__init__(target=target, action=action, assigner=assigner, assignee=assignee, constraint=constraint, **args)

    def add_action(self, action):
        """
        Adds an additional action to the duty.

        :param action: Action object to be added.
        """
        self.action.append(action)
    def remove_action(self, action):
        """
        Remove action from the duty.

        :param action: Action object to be removed.
        """
        if action in self.action:
            self.action.remove(action)

    def add_constraint(self, constraint):
        """
        Adds a constraint to the duty.

        :param constraint: Constraint object to be added.
        """
        self.constraint.append(constraint)

    def set_consequence(self, consequence):
        """
        Sets the consequence of the duty.

        :param consequence: Duty object representing the consequence.
        """
        if consequence is None:
            self.consequence = []
        elif isinstance(consequence, list):
            self.consequence = [Duty(**c) for c in consequence]
        elif isinstance(consequence, dict):
            self.consequence = [Duty(**consequence)]
        else:
            self.consequence = consequence

    def is_fulfilled(self):
        """
        Checks if the duty is fulfilled.

        :return: True if the duty is fulfilled, False otherwise.
        """
        # Implement your logic to check if the duty is fulfilled here
        # For example, if all constraints are satisfied, consider it as fulfilled
        return all(constraint.is_satisfied() for constraint in self.constraint)

    def clear_action(self):
        """
        Clears all additional action associated with the duty.
        """
        self.action = []

    def clear_constraint(self):
        """
        Clears all constraints associated with the duty.
        """
        self.constraint = []

    def clear_consequence(self):
        """
        Clears the consequence associated with the duty.
        """
        self.consequence = None


class Obligation(Duty):
    def __init__(self, target = None, action=None, assigner=None, assignee=None, constraint=None, consequence=None, **args):
        """
        Initializes a Obligation instance, extending the Rule class with additional properties
        for action, constraints, and a potential consequence.

        :param target: The object or entity the duty applies to.
        :param action: The primary action associated with the duty.
        :param assigner: The entity that imposes the duty.
        :param assignee: The entity obligated to fulfill the duty.
        :param consequence: Optional; another Duty (or Rule) instance representing the consequence of not fulfilling the duty.
        :param action: Optional; a list of additional Action objects associated with the duty.
        :param constraints: Optional; a list of Constraint objects specifying conditions under which the duty applies.
        """
        super().__init__(target=target, action=action, assigner=assigner, assignee=assignee, consequence=consequence, constraint=constraint, **args)


    def is_fulfilled(self):
        """
        Checks if the duty is fulfilled.

        :return: True if the duty is fulfilled, False otherwise.
        """
        # Implement your logic to check if the duty is fulfilled here
        # For example, if all constraints are satisfied, consider it as fulfilled
        return all(constraint.is_satisfied() for constraint in self.constraint)

    def clear_action(self):
        """
        Clears all additional action associated with the duty.
        """
        self.action = []

    def clear_constraint(self):
        """
        Clears all constraints associated with the duty.
        """
        self.constraint = []

    def clear_consequence(self):
        """
        Clears the consequence associated with the duty.
        """
        self.consequence = None


class Permission(Rule):
    def __init__(self, target, duty : Duty = None, action=None, assigner=None, assignee=None, constraint: Constraint = None, **args):
        """
        Initializes a Permission instance, extending the Rule class with an additional 'duty' property.

        :param target: The object or entity the permission applies to.
        :param action: The action permitted by the permission.
        :param assigner: The entity that grants the permission.
        :param assignee: The entity to whom the permission is granted.
        :param duty: Optional; an Action instance representing the duty associated with the permission.
        """

        self.set_duty(duty)
        super().__init__(target=target, action=action, assigner=assigner, assignee=assignee, constraint=constraint, **args)


    def set_duty(self, duty):
        """
        Sets or updates the duty associated with the permission.

        :param duty: Action instance representing the duty.
        """
        if duty is None:
            self.duty = []
        elif isinstance(duty, list):
            self.duty = [Duty(**c) for c in duty]
        elif isinstance(duty, dict):
            self.duty = [Duty(**duty)]
        else:
            self.duty = duty

    def clear_duty(self):
        """
        Removes the duty associated with the permission.
        """
        self.duty = None

    def is_used(self):
        pass


class Prohibition(Rule):
    def __init__(self, target = None, action=None, assigner=None, assignee=None, constraint=None, remedy:Duty=None, **args):
        """
        Initializes a Prohibition instance, extending the Rule class with an additional 'remedy' property.

        :param target: The object or entity the prohibition applies to.
        :param action: The action permitted by the prohibition.
        :param assigner: The entity that grants the prohibition.
        :param assignee: The entity to whom the prohibition is granted.
        :param remedy: Optional; an Action instance representing the remedy associated with the prohibition.
        """

        self.set_remedy(remedy)
        super().__init__(target=target, action=action, assigner=assigner, assignee=assignee, constraint=constraint, **args)



    def is_violated(self):
        """
        Checks if the prohibition has been violated.

        :return: True if the prohibition has been violated, False otherwise.
        """
        # # TODO: Implement your logic to check if the prohibition is violated here
        # For example, if the remedy is not None, consider it as violated
        return self.remedy is not None

    def set_remedy(self, remedy):
        """
        Sets or updates the remedy associated with the prohibition.

        :param remedy: Action instance representing the remedy.
        """

        if remedy is None:
            self.remedy = []
        elif isinstance(remedy, list):
            self.remedy = [Duty(**c) for c in remedy]
        elif isinstance(remedy, dict):
            self.remedy = [Duty(**remedy)]
        else:
            self.remedy = remedy

    def clear_remedy(self):
        """
        Removes the remedy associated with the prohibition.
        """
        self.remedy = None


class Policy:
    def __init__(self, uid, type, profiles=None, inherit_from=None, conflict=None, permission: Optional[Permission] = None ,
                 prohibition: Optional[Prohibition] = None, obligation: Optional[Obligation] = None, duty: Optional[Duty] = None):
        self.uid = uid
        self.type = type
        self.profiles = profiles if profiles else []
        self.permission = permission if permission else []
        self.prohibition = prohibition if prohibition else []
        self.obligation = obligation if obligation else []
        self.duty = duty if duty else []
        self.inherit_from = inherit_from if inherit_from else []
        self.conflict = conflict
