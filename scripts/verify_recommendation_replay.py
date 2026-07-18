#!/usr/bin/env python3
"""Verify one persisted recommendation without network access."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from uuid import UUID

backend_src = Path(__file__).resolve().parent.parent / "backend" / "src"
if str(backend_src) not in sys.path:
    sys.path.insert(0, str(backend_src))

from marko.infrastructure.db.session import async_session_factory  # noqa: E402
from marko.services.recommendation_replay import (  # noqa: E402
    replay_recommendation,
)


async def _run(workspace_id: UUID, recommendation_id: UUID) -> int:
    async with async_session_factory() as session:
        replay = await replay_recommendation(
            session,
            workspace_id=workspace_id,
            recommendation_id=recommendation_id,
        )
    print(
        json.dumps(
            {
                "recommendation_id": str(replay.recommendation_id),
                "replay_contract_version": replay.replay_contract_version,
                "calculated_at": replay.calculated_at.isoformat(),
                "exact_match": replay.exact_match,
                "mismatches": replay.mismatches,
                "replayed": replay.replayed,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if replay.exact_match else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace_id", type=UUID)
    parser.add_argument("recommendation_id", type=UUID)
    args = parser.parse_args()
    return asyncio.run(_run(args.workspace_id, args.recommendation_id))


if __name__ == "__main__":
    raise SystemExit(main())
