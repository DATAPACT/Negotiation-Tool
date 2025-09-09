from recommender.dpv import get_purpose_detail
from recommender.odrl import get_action_detail

level, parent, sibilings = get_purpose_detail("AcademicResearch")
print(level, parent, sibilings)
action_level, parent_node, siblings = get_action_detail ("aggregate")
print(action_level, parent_node, siblings)