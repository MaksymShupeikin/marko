# Production Compose deployment

`compose.production.yaml` is a self-contained application edge for a single
host. PostgreSQL and Redis remain external managed dependencies; Caddy,
Prometheus, the API, workers, scheduler, and Flutter frontend run in Compose.

## Required host preparation

1. Point the `APP_DOMAIN` and `API_DOMAIN` DNS records at the host.
2. Permit inbound TCP `80` and TCP/UDP `443`. Do not publish the API,
   frontend, Redis, PostgreSQL, or Prometheus ports publicly.
3. Copy `.env.production.example` to an untracked file outside the repository,
   replace every placeholder, and set mode `0600`.
4. Keep `PUBLIC_API_BASE_URL`, `API_DOMAIN`, `ALLOWED_HOSTS`, `APP_DOMAIN`, and
   `CORS_ORIGINS` consistent. The production preflight rejects mismatches.

Run from the repository root:

```bash
cd backend
uv run check-production-config --env-file /secure/path/marko-production.env --mode static
cd ..
docker compose \
  --env-file /secure/path/marko-production.env \
  -f deploy/compose.production.yaml \
  config --quiet
docker compose \
  --env-file /secure/path/marko-production.env \
  -f deploy/compose.production.yaml \
  up -d --build
```

## Edge and proxy boundary

Caddy obtains and renews public certificates automatically and routes the two
public hosts:

- `APP_DOMAIN` to `frontend:80`;
- `API_DOMAIN` to `api:8000`.

The API and frontend use Compose `expose`, not host port publication. For this
topology `TRUSTED_PROXY_IPS=*` is intentional: the API is reachable only from
private Docker networks and all public traffic crosses Caddy. Do not reuse that
setting if an operator publishes the API container directly.

## Scheduler and monitoring

The scheduler healthcheck verifies all three conditions: the supervisor PID is
alive, its Celery Beat child is alive, and Redis still contains the same fresh
lease token. Lease loss stops the fenced Beat child before the supervisor tries
to reacquire ownership.

Prometheus scrapes the private
`/api/v1/operations/metrics/prometheus` endpoint. Caddy returns `404` for that
path, so it is not part of the public API. The Prometheus UI binds to loopback
only at `127.0.0.1:${PROMETHEUS_PORT:-9090}`; use an SSH tunnel for operator
access. `prometheus-alerts.yml` is loaded by the service, including scheduler
lease, queue, failure, evidence, and retry-amplification alerts. Route alert
notifications through the infrastructure's Alertmanager or managed monitoring
receiver before go-live.

Caddy certificates/configuration and Prometheus time-series data live in named
volumes. Back up and restore requirements for those volumes and the external
PostgreSQL service remain an operational go-live gate.
