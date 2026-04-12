"""Utility helpers for software-project normalization and publication."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import json
import re
from typing import Dict, Iterable, List, Optional


VERSION_RE = re.compile(r"(?:v(?:ersion)?\s*)?(\d+(?:\.\d+){0,4})", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s\"'<>]+")
WHITESPACE_RE = re.compile(r"\s+")
FIX_KEYWORDS = (
    "fix",
    "fixed",
    "fixes",
    "bug",
    "issue",
    "crash",
    "error",
    "broken",
    "resolve",
    "resolved",
    "hotfix",
    "regression",
    "vulnerability",
    "security",
    "sanitize",
    "prevent",
    "correct",
)
NON_BUG_PREFIXES = (
    "add ",
    "added ",
    "new ",
    "introduce ",
    "introduced ",
    "feature ",
    "docs ",
    "documentation ",
    "refactor ",
    "chore ",
    "build ",
    "ci ",
)
BUG_SECTION_HEADERS = (
    "bug fixes",
    "bugfixes",
    "fixes",
    "fixed issues",
    "resolved issues",
    "hotfixes",
)
FEATURE_SECTION_HEADERS = (
    "features",
    "new features",
    "enhancements",
    "improvements",
    "added",
    "changed",
)
FRONTEND_PATH_MARKERS = (
    "package.json",
    "vite.config",
    "webpack.config",
    "src/app.tsx",
    "src/app.jsx",
    "src/main.tsx",
    "src/main.jsx",
    "pages/",
    "components/",
    "public/",
    "templates/",
    "static/",
)
BACKEND_PATH_MARKERS = (
    "app.py",
    "server.py",
    "manage.py",
    "main.go",
    "pom.xml",
    "build.gradle",
    "Program.cs",
    "Controllers/",
    "routes/",
    "api/",
    "cmd/",
)
DATABASE_PATH_MARKERS = (
    "migration",
    "schema.sql",
    "prisma/",
    "alembic/",
    "sequelize/",
    "typeorm/",
    "sql/",
    "database/",
    "db/",
)


def slugify(value: str) -> str:
    """Normalize text into a stable slug."""
    lowered = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return lowered.strip("-") or "candidate"


def clean_text(value: str) -> str:
    """Normalize whitespace and HTML entities."""
    return WHITESPACE_RE.sub(" ", html.unescape(value or "").strip())


def sha256_text(value: str) -> str:
    """Hash one text payload."""
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def now_iso() -> str:
    """Return the current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_datetime(value: str) -> Optional[datetime]:
    """Parse an ISO-like datetime string when possible."""
    text = clean_text(value)
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def days_since(value: str) -> Optional[int]:
    """Return the number of days since one timestamp."""
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    return (datetime.now(timezone.utc) - parsed).days


def release_cadence_days(timestamps: List[str]) -> Optional[float]:
    """Compute the mean number of days between release timestamps."""
    parsed = [item for item in (parse_datetime(value) for value in timestamps) if item]
    if len(parsed) < 2:
        return None
    parsed.sort()
    deltas = [
        (current - previous).days
        for previous, current in zip(parsed[:-1], parsed[1:], strict=False)
        if (current - previous).days >= 0
    ]
    if not deltas:
        return None
    return round(sum(deltas) / len(deltas), 2)


def version_sort_key(version: str) -> tuple[int, ...]:
    """Build a sortable tuple from a version string."""
    match = VERSION_RE.search(version or "")
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def extract_version(value: str) -> str:
    """Extract a version string from arbitrary release text."""
    match = VERSION_RE.search(value or "")
    if match:
        return match.group(1)
    return clean_text(value)


def has_fix_language(value: str) -> bool:
    """Return whether one text contains bug-fix evidence."""
    text = clean_text(value).lower()
    return any(keyword in text for keyword in FIX_KEYWORDS)


def looks_non_bug_line(value: str) -> bool:
    """Return whether one line looks like a feature or maintenance note."""
    text = clean_text(value).lower()
    return any(text.startswith(prefix) for prefix in NON_BUG_PREFIXES)


def split_patch_lines(value: str) -> List[str]:
    """Split release text into normalized candidate lines."""
    lines: List[str] = []
    for raw_line in value.replace("\r", "\n").split("\n"):
        line = clean_text(_strip_markdown_prefix(raw_line))
        if not line:
            continue
        segments = _split_compound_line(line)
        if segments:
            lines.extend(segments)
        else:
            lines.append(line)
    if lines:
        return lines
    return [
        clean_text(sentence)
        for sentence in re.split(r"(?<=[.!?])\s+", clean_text(value))
        if clean_text(sentence)
    ]


def classify_release_note_line(value: str) -> str:
    """Classify one release-note line as a heading or content."""
    text = clean_text(_strip_markdown_prefix(value)).lower().rstrip(":")
    if not text:
        return "empty"
    if text in BUG_SECTION_HEADERS:
        return "bug_section"
    if text in FEATURE_SECTION_HEADERS:
        return "feature_section"
    return "content"


def find_urls(value: str) -> List[str]:
    """Extract URLs from one text field."""
    return [clean_text(item) for item in URL_RE.findall(value or "")]


def pretty_json(payload: object) -> str:
    """Render JSON with stable formatting."""
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"


def infer_architecture(
    file_paths: Iterable[str],
    languages: Dict[str, int],
    topics: Iterable[str],
) -> Dict[str, object]:
    """Infer repository architecture from file paths, languages, and topics."""
    normalized_paths = [path.replace("\\", "/").lower() for path in file_paths]
    normalized_topics = {str(topic).strip().lower() for topic in topics}
    language_names = {name.lower() for name in languages}

    has_frontend = _has_marker(normalized_paths, FRONTEND_PATH_MARKERS) or bool(
        normalized_topics & {"frontend", "web", "browser", "react", "vue", "ui"}
    )
    if {"javascript", "typescript", "html", "css"} & language_names:
        has_frontend = has_frontend or any(
            path.endswith((".tsx", ".jsx", ".vue", ".svelte", ".html", ".css"))
            for path in normalized_paths
        )

    has_backend = _has_marker(normalized_paths, BACKEND_PATH_MARKERS) or bool(
        normalized_topics & {"backend", "api", "server", "microservice", "fastapi"}
    )
    if {"python", "go", "java", "c#", "rust"} & language_names:
        has_backend = has_backend or any(
            path.endswith((".py", ".go", ".java", ".cs", ".rs", ".rb", ".php", ".ts"))
            for path in normalized_paths
        )

    has_database = _has_marker(normalized_paths, DATABASE_PATH_MARKERS) or bool(
        normalized_topics & {"database", "sql", "postgres", "mysql", "sqlite", "prisma"}
    )

    if has_frontend and has_backend:
        interaction_mode = "mixed"
    elif has_frontend:
        interaction_mode = "computer_use"
    elif has_backend or has_database:
        interaction_mode = "api_cli"
    else:
        interaction_mode = "unknown"

    evidence = {
        "frontend": _first_marker(normalized_paths, FRONTEND_PATH_MARKERS),
        "backend": _first_marker(normalized_paths, BACKEND_PATH_MARKERS),
        "database": _first_marker(normalized_paths, DATABASE_PATH_MARKERS),
    }
    return {
        "has_frontend": has_frontend,
        "has_backend": has_backend,
        "has_database": has_database,
        "interaction_mode": interaction_mode,
        "evidence": {key: value for key, value in evidence.items() if value},
    }


def build_dedupe_key(repo_full_name: str, release_id: str) -> str:
    """Build a stable dedupe key for one repo and release pair."""
    return f"{repo_full_name.lower()}::{release_id}"


def _has_marker(paths: List[str], markers: Iterable[str]) -> bool:
    return any(marker.lower() in path for path in paths for marker in markers)


def _first_marker(paths: List[str], markers: Iterable[str]) -> str:
    for path in paths:
        for marker in markers:
            if marker.lower() in path:
                return path
    return ""


def _strip_markdown_prefix(value: str) -> str:
    stripped = value.strip()
    stripped = re.sub(r"^#{1,6}\s*", "", stripped)
    stripped = re.sub(r"^(?:[-*+•]|\d+[.)])\s*", "", stripped)
    return stripped.strip()


def _split_compound_line(value: str) -> List[str]:
    text = clean_text(value)
    if not text:
        return []
    parts = re.split(
        r"(?<=[.;!?])\s+(?=(?:fix|fixed|fixes|resolved|resolve|bug|issue|hotfix|security|prevent|correct)\b)",
        text,
        flags=re.IGNORECASE,
    )
    return [clean_text(part) for part in parts if clean_text(part)]
