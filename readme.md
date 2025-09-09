# Data Sharing Negotiation Code Repository

**Note that this service is under construction and not all features will work.**

This project is a web application with a REST API and a MongoDB database. It is containerized using Docker and managed with Docker Compose, enabling simple deployment and scaling. The project consists of two main services:

1. **Negotiation UI - Web App (Under Construction)**: A Django-based application, serving the main web interface.
2. **Negotiation API Service**: A Python-based service handling API requests.
3. **MongoDB Service**: A MongoDB instance for persistent data storage.

## Requirements

- Docker
- Docker Compose

## Installation Using Docker

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

## Using the Negotiation Plugin

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


## Getting Started with Local Development on the UI

The UI allows the data controller or processor to collect user consent and custom privacy constraints (or preferences) ethically.

First, ensure that all docker containers except `web` are running.

1. Install dependencies
```bash
pip install -r requirements.txt
```

2. Run the server
```bash
python manage.py runserver 
```
Note: the UI no longer uses a sqlite database and therefore no migrations are necessary.  Instead, users are managed in the mongoDB connected to the API. Users should be managed using the commands from the API. For documentation about the API see http://localhost:8002/docs when the api docker container is running locally or see https://dips.soton.ac.uk/negotiation-api/docs for documentation on the deployed version of the API. 


## Contributing
Pull requests are welcome. For any changes, please follow the instructions below. 
1. Fork the repository
2. Create a new branch
```bash
git checkout -b <branch-name>
```
3. Make changes and commit
```bash
git add .
git commit -m "commit message"
```
4. Setup [pre-commit hooks](https://pre-commit.com). 
```bash
pre-commit install
```
5. Run pre-commit hooks. This will run the linters and auto-format the code.
```bash
pre-commit run --all-files
```

4. Push changes to the branch
```bash
git push origin <branch-name>
```
5. Create a pull request
6. Wait for the pull request to be reviewed and merged
## License
Apache 2.0


