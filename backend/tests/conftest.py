"""Make tests independent from the developer's uncommitted root ``.env``."""

import os


os.environ["API_DOCS_ENABLED"] = "false"
os.environ["FIREBASE_PROJECT_ID"] = ""
os.environ["PROM_MARKETPLACE_SOURCE_ACCESS_VERDICT"] = "NOT_PERMITTED"
os.environ["PROM_MARKETPLACE_SOURCE_ACCESS_REFERENCE"] = ""
os.environ["E2E_AUTH_BYPASS"] = "false"
os.environ["E2E_AUTH_TOKEN"] = ""
os.environ["E2E_TASK_HOLD_SECONDS"] = "0"
os.environ["COST_PRIVACY_MODE"] = "UNDECIDED"
os.environ["COST_ENCRYPTION_ACTIVE_KEY_ID"] = ""
os.environ["COST_ENCRYPTION_KEYS_JSON"] = ""
