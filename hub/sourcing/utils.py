"""Utility helpers for provider normalization and publication."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import json
import re
from typing import Iterable, List, Optional


VERSION_RE = re.compile(r"(?:v(?:ersion)?\s*)?(\d+(?:\.\d+){0,3})", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s\"'<>]+")
WHITESPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
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
    "prevent",
    "correct",
)
NON_BUG_PREFIXES = (
    "add ",
    "added ",
    "new ",
    "introduce ",
    "introduced ",
    "content ",
    "dlc ",
    "feature ",
    "refactor ",
    "docs ",
    "documentation ",
)


def slugify(value: str) -> str:
    lowered = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return lowered.strip("-") or "candidate"


def clean_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", html.unescape(value or "").strip())


def strip_html(value: str) -> str:
    return clean_text(TAG_RE.sub(" ", value or ""))


def sha256_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def epoch_to_iso(value: int | str | None) -> str:
    if value in (None, ""):
        return ""
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return clean_text(str(value))
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(
        microsecond=0
    ).isoformat()


def parse_datetime(value: str) -> Optional[datetime]:
    text = clean_text(value)
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def version_sort_key(version: str) -> tuple[int, ...]:
    match = VERSION_RE.search(version or "")
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def extract_version(value: str) -> str:
    match = VERSION_RE.search(value or "")
    if match:
        return match.group(1)
    return clean_text(value)


def find_urls(value: str) -> List[str]:
    return [clean_text(item) for item in URL_RE.findall(value or "")]


def choose_first_url(value: str, domains: Iterable[str]) -> str:
    domain_set = {domain.lower() for domain in domains}
    for url in find_urls(value):
        lowered = url.lower()
        if any(domain in lowered for domain in domain_set):
            return url
    return ""


def has_fix_language(value: str) -> bool:
    text = clean_text(value).lower()
    return any(keyword in text for keyword in FIX_KEYWORDS)


def looks_non_bug_line(value: str) -> bool:
    text = clean_text(value).lower()
    return any(text.startswith(prefix) for prefix in NON_BUG_PREFIXES)


def split_patch_lines(value: str) -> List[str]:
    text = value.replace("\r", "\n")
    lines: List[str] = []
    for raw_line in text.split("\n"):
        line = clean_text(raw_line.lstrip("-*•0123456789. ").strip())
        if line:
            lines.append(line)
    if not lines:
        for sentence in re.split(r"(?<=[.!?])\s+", clean_text(value)):
            cleaned = clean_text(sentence)
            if cleaned:
                lines.append(cleaned)
    return lines


def extract_meta_content(html_text: str, key: str) -> str:
    pattern = re.compile(
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    )
    match = pattern.search(html_text or "")
    return clean_text(match.group(1)) if match else ""


def find_link_urls(html_text: str) -> List[str]:
    pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
    return [clean_text(item) for item in pattern.findall(html_text or "")]


def pretty_json(payload: object) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
