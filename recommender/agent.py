import random
from typing import List, Optional
from pydantic import BaseModel

from recommender.dpv import get_purpose_detail
from recommender.odrl import get_action_detail


class Dataset(BaseModel):
    name : str
    items : List[str]

class Preference(BaseModel):
    dataset : Dataset
    upper_dataset_items : List[str]
    lower_dataset_items : List[str]
    upper_duration : int
    lower_duration : int
    upper_price : float
    lower_price : float
    upper_action : str
    lower_action : str
    upper_purpose : str
    lower_purpose : str
    upper_party : str
    lower_party : str

class Proposal(BaseModel):
    dataset : Dataset
    duration : int
    price : float
    action : str
    purpose : str
    party : str

class RecommenderAgentRecord(BaseModel):
    #agent_type: PartyType
    preference: Preference
    previous_offer: Proposal
    previous_request: Optional[Proposal]

def new_request(record : RecommenderAgentRecord) -> Proposal:
    result = None
    offer_purpose_level, offer_purpose_parent, offer_purpose_sibilings = get_purpose_detail(record.previous_offer.purpose)
    # print(record.previous_offer.purpose, offer_purpose_level, offer_purpose_parent, offer_purpose_sibilings)
    offer_action_level, offer_actione_parent, offer_action_siblings = get_action_detail (record.previous_offer.action)
    # print(offer_action_level, offer_actione_parent, offer_action_siblings)

    if record.previous_request is None:
        result = Proposal(
                dataset = Dataset(name=record.previous_offer.dataset.name,
                                    items=record.preference.upper_dataset_items),
                price = min (record.previous_offer.price , record.preference.lower_price),
                duration = record.preference.upper_duration,
                purpose = record.preference.upper_purpose,
                action = record.preference.upper_action,
                party = record.preference.upper_party)
    else:   
        request_purpose_level, request_purpose_parent, request_purpose_sibilings = get_purpose_detail(record.previous_request.purpose)
        # print(record.previous_request.purpose, request_purpose_level, request_purpose_parent, request_purpose_sibilings)
        request_action_level, request_action_parent, request_action_siblings = get_action_detail (record.previous_request.action)
        # print (request_action_level, request_action_parent, request_action_siblings)
        result = Proposal(   
                dataset = Dataset (name=record.previous_offer.dataset.name, 
                                    items = record.previous_offer.dataset.items 
                                        if len(record.previous_offer.dataset.items)>= len(record.preference.upper_dataset_items) 
                                            else record.preference.upper_dataset_items if random.random()< 0.4 
                                                else record.previous_request.dataset.items),
                price = record.previous_offer.price 
                        if (record.previous_offer.price <= record.previous_request.price) 
                            else record.previous_request.price + record.previous_offer.price / 10 
                                if (record.previous_request.price + record.previous_offer.price / 10 <= record.preference.upper_price)
                                    else record.preference.upper_price,
                duration = max (record.previous_offer.duration , ( record.preference.upper_duration + record.preference.lower_duration)/2),
                purpose = record.previous_offer.purpose 
                        if (record.previous_offer.purpose == request_purpose_parent or record.previous_offer.purpose == record.previous_request.purpose)
                            else record.previous_request.purpose 
                                if random.random()< 0.8
                                    else record.previous_offer.purpose, 
                action = record.previous_offer.action 
                        if (record.previous_offer.action == request_action_parent or record.previous_offer.action == record.previous_request.action)
                            else record.previous_request.action 
                                if random.random()< 0.8
                                    else record.previous_offer.action,
                party = record.previous_request.party)
    
    return result

def new_offer(record : RecommenderAgentRecord) -> Proposal:
    result = None
    offer_purpose_level, offer_purpose_parent, offer_purpose_sibilings = get_purpose_detail(record.previous_offer.purpose)
    # print(record.previous_offer.purpose, offer_purpose_level, offer_purpose_parent, offer_purpose_sibilings)
    offer_action_level, offer_actione_parent, offer_action_siblings = get_action_detail (record.previous_offer.action)
    # print(offer_action_level, offer_actione_parent, offer_action_siblings)
  
    request_purpose_level, request_purpose_parent, request_purpose_sibilings = get_purpose_detail(record.previous_request.purpose)
    # print(record.previous_request.purpose, request_purpose_level, request_purpose_parent, request_purpose_sibilings)
    request_action_level, request_action_parent, request_action_siblings = get_action_detail (record.previous_request.action)
    # print (request_action_level, request_action_parent, request_action_siblings)
    result = Proposal(   
        dataset = Dataset (name=record.previous_offer.dataset.name, 
                            items = record.previous_request.dataset.items 
                                if (len(record.previous_request.dataset.items) <= len(record.preference.upper_dataset_items) 
                                        and record.previous_request.price > (record.preference.lower_price + record.preference.upper_price)/2) 
                                    else record.previous_request.dataset.items if random.random()<= 0.5 
                                        else record.previous_offer.dataset.items),
                price = record.previous_request.price 
                    if (record.previous_request.price >= record.previous_offer.price) 
                        else record.previous_offer.price - record.previous_request.price/10 
                            if ((record.previous_offer.price - record.previous_request.price/10) > record.preference.lower_price)
                                else record.previous_offer.price,
                duration = min (record.previous_request.duration , ( record.preference.upper_duration + record.preference.lower_duration)/2),
                purpose = record.previous_request.purpose 
                        if (record.previous_request.purpose == record.previous_offer.purpose or record.previous_offer.purpose == request_purpose_parent)
                            else record.previous_offer.purpose 
                                if random.random()< 0.8
                                    else record.previous_request.purpose, 
                action = record.previous_request.action 
                        if (record.previous_offer.action == request_action_parent or record.previous_offer.action == record.previous_request.action)
                            else record.previous_offer.action 
                                if random.random()< 0.8
                                    else record.previous_request.action,
                party = record.previous_request.party 
                    if (record.previous_request.party or (record.previous_request.price > record.preference.lower_price))
                        else record.previous_offer.party 
    )     
             
    return result 
