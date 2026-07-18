.PHONY: up down logs test analyze migrate validate-response-footer validate-machine-summary

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api worker pricing-worker frontend

test:
	docker compose --profile test run --rm --build backend-test
	cd frontend && flutter test

analyze:
	cd frontend && flutter analyze

migrate:
	docker compose run --rm migrate

validate-response-footer:
	cd backend && uv run validate-response-footer --manifest ../docs/examples/end_of_response_prompt_15_013.yaml

validate-machine-summary:
	cd backend && uv run validate-machine-summary --manifest ../docs/examples/machine_readable_summary_prompt_15_013.yaml
