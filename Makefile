.PHONY: help up down restart ps logs logs-api logs-worker test test-backend test-frontend analyze migrate backup deploy-frontend update clean

# Default: show available commands
help:
	@echo "Available commands:"
	@echo "  make up              - Start all containers in background with build"
	@echo "  make down            - Stop all containers"
	@echo "  make restart         - Restart all containers"
	@echo "  make ps              - View status of all running containers"
	@echo "  make logs            - Stream logs from all containers"
	@echo "  make logs-api        - Stream FastAPI logs"
	@echo "  make logs-worker     - Stream Celery worker logs"
	@echo "  make migrate         - Run Alembic database migrations"
	@echo "  make backup          - Create a timestamped PostgreSQL backup"
	@echo "  make test            - Run all backend and frontend tests"
	@echo "  make test-backend    - Run backend pytest suite"
	@echo "  make test-frontend   - Run frontend Flutter tests"
	@echo "  make analyze         - Run Flutter linter/analyzer"
	@echo "  make deploy-frontend - Build and deploy Flutter Web to Cloudflare Pages"
	@echo "  make update          - Pull latest code and rebuild containers"
	@echo "  make clean           - Remove unused Docker caches and stopped containers"

# Docker & Services
up:
	docker compose up -d --build

down:
	docker compose down

restart:
	docker compose restart

ps:
	docker compose ps

# Logs
logs:
	docker compose logs -f

logs-api:
	docker compose logs -f api

logs-worker:
	docker compose logs -f worker

# Database
migrate:
	docker compose run --rm migrate

# Whitelist: permanent free access for an account, e.g. `make grant-access EMAIL=x@y.com`
grant-access:
	docker compose exec -T db psql -U marko -d marko -c "UPDATE workspaces SET has_free_access = true WHERE id IN (SELECT wm.workspace_id FROM workspace_members wm JOIN users u ON u.id = wm.user_id WHERE u.email = '$(EMAIL)');"

revoke-access:
	docker compose exec -T db psql -U marko -d marko -c "UPDATE workspaces SET has_free_access = false WHERE id IN (SELECT wm.workspace_id FROM workspace_members wm JOIN users u ON u.id = wm.user_id WHERE u.email = '$(EMAIL)');"

backup:
	@mkdir -p backups
	docker compose exec -T db pg_dump -U marko marko | gzip > backups/marko_$$(date +%Y%m%d_%H%M%S).sql.gz
	@echo "Backup saved to backups/"

# Testing & Quality
test: test-backend test-frontend

test-backend:
	docker compose --profile test run --rm --build backend-test

test-frontend:
	cd frontend && flutter test

analyze:
	cd frontend && flutter analyze

# Deployment & Maintenance
deploy-frontend:
	cd frontend && flutter build web --release \
		--dart-define=API_BASE_URL=https://api.markoprice.com \
		--dart-define=FIREBASE_API_KEY=AIzaSyB3z6DdrNqhHnMw6fwsrni8vhJ1Z66cgtA \
		--dart-define=FIREBASE_AUTH_DOMAIN=marko-4941e.firebaseapp.com \
		--dart-define=FIREBASE_PROJECT_ID=marko-4941e \
		--dart-define=FIREBASE_MESSAGING_SENDER_ID=779526440182 \
		--dart-define=FIREBASE_WEB_APP_ID=1:779526440182:web:050d87e4d64dccb57cd8d7 \
		--dart-define=GOOGLE_CLIENT_ID=779526440182-nrkjp7e7pma5lhdandq69hcc5gt0aodu.apps.googleusercontent.com
	cp frontend/web/_redirects frontend/build/web/_redirects 2>/dev/null || true
	cd frontend && npx wrangler pages deploy build/web --project-name=marko

build-android:
	cd frontend && JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home" flutter build appbundle --release \
		--dart-define=API_BASE_URL=https://api.markoprice.com \
		--dart-define=FIREBASE_API_KEY=AIzaSyB3z6DdrNqhHnMw6fwsrni8vhJ1Z66cgtA \
		--dart-define=FIREBASE_AUTH_DOMAIN=marko-4941e.firebaseapp.com \
		--dart-define=FIREBASE_PROJECT_ID=marko-4941e \
		--dart-define=FIREBASE_MESSAGING_SENDER_ID=779526440182 \
		--dart-define=FIREBASE_WEB_APP_ID=1:779526440182:web:050d87e4d64dccb57cd8d7 \
		--dart-define=GOOGLE_CLIENT_ID=779526440182-nrkjp7e7pma5lhdandq69hcc5gt0aodu.apps.googleusercontent.com

update:
	git pull
	docker compose up -d --build

clean:
	docker system prune -f
