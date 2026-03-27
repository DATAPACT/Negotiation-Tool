"""
Author: Semih Yumuşak
Date: March 25, 2024
Description: This is the action class which implements refinable interface.

Contributors:

"""

from typing import List

from .Constraint import Constraint
from .Interfaces import RefinableInterface

class Refinable(RefinableInterface):
    def __init__(self,  **args):
        """
        Initializes an Action instance.

        :param value: The main action, can be a string or an object representing the action.
        :param refinements: Optional list of Constraint objects that refine the conditions of the action.
        :param included_in: The encompassing Action.
        :param implies: Optional list of action that are implied by this Action.
        """
        # refinements: List[Constraint] = None,
        self.source = args.get("source", None)
        self.uid = args.get("uid", None)
        self.value = args.get("value", None)
        refinement = args.get("refinement", None)
        if isinstance(refinement, dict):
            self.refinement = Constraint(**refinement)
        elif isinstance(refinement, list):
            self.refinement = [Constraint(**c) for c in refinement]
        self.other = args
        # self.refinements = refinements if refinements is not None else []

    def add_refinement(self, constraint: Constraint):
        """
        Adds a refinement to the PartyCollection.

        :param constraint: Constraint object to be added as a refinement.
        """
        self.refinements.append(constraint)

    def remove_refinement(self, constraint: Constraint):
        """
        Removes a refinement from the PartyCollection.

        :param constraint: Constraint object to be removed from refinements.
        """
        if constraint in self.refinements:
            self.refinements.remove(constraint)

class Action(Refinable):
    def __init__(self, **args):
        """
        Initializes an Action instance.

        :param value: The main action, can be a string or an object representing the action.
        :param refinements: Optional list of Constraint objects that refine the conditions of the action.
        :param included_in: The encompassing Action.
        :param implies: Optional list of action that are implied by this Action.
        """
        super().__init__(**args)



class AssetCollection(Refinable):
    def __init__(self,  **args):
        """
        Initializes an AssetCollection instance.

        :param source: The source reference of the AssetCollection.
        :param refinements: Optional list of Constraint objects that refine the conditions of the AssetCollection.
        """
        super().__init__(**args)



class PartyCollection(Refinable):
    def __init__(self, **args):
        """
        Initializes a PartyCollection instance.

        :param source: The source reference of the PartyCollection.
        :param refinements: Optional list of Constraint objects that refine the conditions of the PartyCollection.
        """
        super().__init__(**args)

