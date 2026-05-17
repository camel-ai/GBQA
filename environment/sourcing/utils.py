from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


FIX_KEYWORDS = (
    "fix",
    "fixed",
    "bug",
    "crash",
    "error",
    "regression",
    "security",
    "vulnerability",
    "resolve",
    "resolved",
    "hotfix",
)


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "environment"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def has_fix_language(value: str) -> bool:
    text = clean_text(value).lower()
    return any(keyword in text for keyword in FIX_KEYWORDS)


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def first_matching_path(paths: Iterable[str], markers: Iterable[str]) -> str:
    normalized_markers = tuple(marker.lower() for marker in markers)
    for path in paths:
        lowered = normalize_path(path).lower()
        if any(marker in lowered for marker in normalized_markers):
            return normalize_path(path)
    return ""

