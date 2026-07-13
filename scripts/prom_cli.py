#!/usr/bin/env python3
"""Compatibility wrapper for the packaged Marko CLI."""
from __future__ import annotations

import pathlib
import sys

backend_src = pathlib.Path(__file__).resolve().parent.parent / "backend" / "src"
if str(backend_src) not in sys.path:
    sys.path.insert(0, str(backend_src))

from marko.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
