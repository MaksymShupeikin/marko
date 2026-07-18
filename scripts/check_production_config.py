#!/usr/bin/env python3
"""Validate production settings without printing credentials."""

from __future__ import annotations

import json
from pathlib import Path
import sys

backend_src = Path(__file__).resolve().parent.parent / "backend" / "src"
if str(backend_src) not in sys.path:
    sys.path.insert(0, str(backend_src))

from marko.core.config import Settings  # noqa: E402
from marko.services.source_access import source_access_status  # noqa: E402


def main() -> int:
    settings = Settings()
    if not settings.is_production:
        raise SystemExit("ENVIRONMENT must be production")
    source = source_access_status(settings)
    print(
        json.dumps(
            {
                "environment": settings.environment,
                "debug": settings.debug,
                "api_docs_enabled": settings.effective_api_docs_enabled,
                "allowed_hosts": settings.allowed_host_list,
                "cors_origins": settings.cors_origin_list,
                "firebase_project_configured": bool(
                    settings.firebase_project_id.strip()
                ),
                "source_access": source.as_dict(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
