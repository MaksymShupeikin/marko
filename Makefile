.PHONY: up down logs test analyze migrate

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api worker frontend

test:
	docker compose --profile test run --rm --build backend-test
	cd frontend && flutter test

analyze:
	cd frontend && flutter analyze

migrate:
	docker compose run --rm migrate
