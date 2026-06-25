"""Register shared GBQA Rewardkit criteria for nested verifier layout."""

from __future__ import annotations

from pathlib import Path
import sys

for candidate in ("/tests/_gbqa_runtime", "/sandbox", "/solution"):
    if (Path(candidate) / "gbqa").is_dir() and candidate not in sys.path:
        sys.path.insert(0, candidate)

import gbqa.rewards.criteria  # noqa: F401
