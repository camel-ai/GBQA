"""Run Harbor with GBQA's root `.env` loaded first."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence

from gbqa.env import load_root_dotenv


def build_harbor_command(argv: Sequence[str]) -> list[str]:
    """Build the Harbor CLI command preserving caller arguments."""

    return ["harbor", *argv]


def main(argv: Sequence[str] | None = None) -> int:
    """Load root `.env`, then delegate to Harbor."""

    load_root_dotenv()
    command = build_harbor_command(sys.argv[1:] if argv is None else argv)
    return subprocess.call(command, env=os.environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())
