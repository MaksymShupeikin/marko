# Marko backend

FastAPI API, background workers, PostgreSQL persistence, prom.ua ingestion, and
product matching for the Marko price-monitoring application. Firebase
Authentication owns credentials and sessions. This service verifies Firebase ID
tokens through Google's public signing keys, provisions local users/workspaces,
and owns all business authorization and data.

Set `FIREBASE_PROJECT_ID` to the exact Firebase project ID. No Firebase Admin
service-account JSON, OAuth client secret, or API key is needed by FastAPI.

The backend is developed and tested through Docker; no host `.venv` is needed:

```bash
docker compose up -d --build db broker migrate api worker scheduler
docker compose --profile test run --rm --build backend-test
```
