from sympy import symbols
from sympy.logic.boolalg import Or, And, Not
from sympy.logic.inference import satisfiable
# Define the propositional symbols
A, B, C = symbols('A B C')

# Define the two propositional logic expressions
expr1 = Or(A, Not(B))
expr2 = And(B, C)

# Check if their conjunction with the negation of the first expression is satisfiable
conflict_check = satisfiable(And(expr1, Not(expr2)))

if conflict_check:
    print("The expressions are not in conflict. There is a model where both can be true.")
else:
    print("The expressions are in conflict. There is no model where both can be true.")

# Optionally, check if the conjunction of the two expressions is satisfiable directly
consistency_check = satisfiable(And(expr1, expr2))

if consistency_check:
    print("The expressions are logically consistent.")
else:
    print("The expressions are logically inconsistent.")
