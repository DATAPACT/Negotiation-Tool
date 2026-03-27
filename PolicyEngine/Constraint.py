"""
Author: Semih Yumuşak
Date: March 25, 2024
Description: This is the constraint package which has logical and arithmetic constraint implementations.

Contributors:

"""

class Constraint:
    def __init__(self, leftOperand=None, operator=None, rightOperand=None, **args):
        if leftOperand is None:
            LogicalConstraint.__init__(self,**args)
        else:
            ArithmeticConstraint.__init__(self,leftOperand=leftOperand,operator=operator, rightOperand=rightOperand)

    def evaluate(self):
        pass

class Refinement(Constraint):
    def __init__(self, leftOperand=None, operator=None, rightOperand=None, **args):
        super().__init__(self, leftOperand=None, operator=None, rightOperand=None, **args)
    def evaluate(self):
        pass

class ArithmeticConstraint(Constraint):
    def __init__(self, leftOperand, operator, rightOperand):
        self.operator = operator
        self.leftOperand = leftOperand  # The specific operand that needs an exact match to proceed
        self.rightOperand = rightOperand

    def check_constraint(self, leftOperandValue, value):
        # First, check if the leftOperand matches exactly
        if self.leftOperand is not None and self.leftOperand != leftOperandValue:
            return False  # The leftOperand does not match; constraint check does not proceed

        # Proceed with the constraint checks
        if self.operator == 'eq':
            return value == self.rightOperand
        elif self.operator == 'gt':
            return value > self.rightOperand
        elif self.operator == 'gteq':
            return value >= self.rightOperand
        elif self.operator == 'lt':
            return value < self.rightOperand
        elif self.operator == 'lteq':
            return value <= self.rightOperand
        elif self.operator == 'neq':
            return value != self.rightOperand
        elif self.operator == "isA":  # This will require OWL reasoning for completeness.
            return value.type == self.rightOperand
        elif self.operator == "hasPart":
            return all(item in self.rightOperand for item in value)
        elif self.operator == "isPartOf":
            return all(item in value for item in self.rightOperand)
        elif self.operator == "isAllOf":
            return all(item == self.rightOperand for item in value)
        elif self.operator == "isAnyOf":
            return any(item == self.rightOperand for item in value)
        elif self.operator == "isNoneOf":
            return all(item != self.rightOperand for item in value)
        else:
            return False

class LogicalConstraint(Constraint):
    def __init__(self, **args):
        self.logic_and = args.get("and", None)
        self.logic_or = args.get("or", None)
        self.logic_xone = args.get("xone", None)
        self.logic_andSequence = args.get("andSequence", None)

        #super().__init__(**args)

    def check_constraint(self, value):
        if self.operator == 'or':
            return any(constraint.check_constraint(None, value) for constraint in self.constraints)
        elif self.operator == '':
            return sum(constraint.check_constraint(None, value) for constraint in self.constraints) == 1
        elif self.operator == 'and':
            return all(constraint.check_constraint(None, value) for constraint in self.constraints)
        elif self.operator == 'andSequence':
            results = [constraint.check_constraint(None, value) for constraint in self.constraints]
            return all(results) and results == sorted(results, reverse=True)
        else:
            return False