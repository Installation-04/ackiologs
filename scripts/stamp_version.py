#!/usr/bin/env python3
"""Writes app/_version.py so a build carries the version being released. Used by
the release workflow before building the Linux binary, Windows exe/MSI, and the
Docker image, so all four report the same `GET /api/version`. Not used for
day-to-day development — app/_version.py stays "0.0.0-dev" on your checkout."""

import re
import sys
from pathlib import Path

if len(sys.argv) != 2:
    print("usage: stamp_version.py <version>", file=sys.stderr)
    raise SystemExit(1)

version = sys.argv[1]
if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
    print(f"refusing to stamp suspicious version string: {version!r}", file=sys.stderr)
    raise SystemExit(1)

path = Path(__file__).resolve().parent.parent / "app" / "_version.py"
path.write_text(f'__version__ = "{version}"\n')
print(f"Stamped {path} -> {version}")
