# Negotiation Manager

Powered by

[![UoSLOGO](./images/UniSouthampton.png)](https://dips.soton.ac.uk/#home)


## **General Description**

The Negotiation Manager allows the creation and negotiation of data sharing agreements through an interface and APIs. The negotiation protocol implement IDSA Contract Negotiation Protocol. Negotiation is possible over ODRL policies, dataset metadata, and natural language clauses. It integration with the Constract Service enables the generation of contracts following a successful negotiation.​


## **Commercial Information**

Table with the organisation, license nature (Open Source, Commercial ... ) and the license. Replace with the values of your module.

| Organisation (s) | License Nature | License |
| ---------------  | -------------- | ------- |
| University of Southampton  | Open Source | MIT Licence |



## **How To Install**


### Requirements

- Docker
- Docker Compose

### Software

Django, Python

### Summary of installation steps

1. Clone the repository:
   ```bash
   git clone --recurse-submodules <repository-url>
   cd <repository-directory>
2. Install the [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
3. Create .env file (see .env.test for the variables that need to be specified).  Note: `API_BASE_URL=http://api:8001/negotiation-api` and `DJANGO_BASE_URL=http://web:8000` when using docker.  If running the django app locally (e.g. for development), `API_BASE_URL=http://localhost:8002/negotiation-api` and `DJANGO_BASE_URL=http://localhost:8000`
4. Then run the following command.
```bash
docker compose up
```

## **How To Use**

1.  Navigate to http://localhost:8000/negotiation/ if running locally or https://dips.soton.ac.uk/negotiation/ for the deployed service.
2.  Register a user using either the UI or the API.  If simulating a negotiation between a consumer and provider, you will need to create one consumer account and one provider account.
3.  Login.
4.  The provider creates an offer using the API or another UPCAST service.
5.  The consumer makes a request through the UI or API. They can edit the ODRL and Resource Description from the corresponding tabs.
6.  The provider logs in and sees the request in their dashboard, they can give a counter-offer.
7.  The consumer accepts the offer.
8.  The provider agrees.
9.  Both parties sign to finalise the negotiation. 
10.  The finalised negotiation is shown in the finalised negotiations table and available for download.


## Expected KPIs

| What | How | Values |
| --- | --- | --- |
| 1) Engagement and satisfaction with negotiation support 2) Effectiveness of the policy comparison functionality |	1) Questionnaire for pilots who integrated/tested the negotiation tool 2) Experiments with pilots, given a number of policies (>=5), variations are automatically generated, and pairs of data provider/ data requester policies are shown to the pilots, who are asked to express whether there is a conflict between the provider and the requester policies. 	| 1) Questionnaire for pilots who integrated/tested the negotiation tool 2) High agreement (>80%) between the pilot's assessment of the two policies and the automatically detected conflict. |
