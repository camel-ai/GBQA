"""GitHub issue/PR closure verification for fix releases (release -> commits -> issues)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Set
from urllib.parse import quote

from .fetcher import FetchError
from .models import ReleaseRecord, SerializableModel


# Match #123 style references; avoid matching URL path segments like /issue/1/foo.
_ISSUE_HASH_RE = re.compile(r"(?<![\w/])#(\d+)(?!\w)")
_GH_ISSUE_OR_PULL_RE = re.compile(
    r"github\.com/[^/\s]+/[^/\s]+/(?:issues|pull)/(\d+)",
    re.IGNORECASE,
)


def extract_tracked_issue_numbers(texts: List[str]) -> List[int]:
    """Collect unique GitHub issue/PR numbers from release text and URLs."""
    found: Set[int] = set()
    for raw in texts:
        text = raw or ""
        for match in _ISSUE_HASH_RE.finditer(text):
            found.add(int(match.group(1)))
        for match in _GH_ISSUE_OR_PULL_RE.finditer(text):
            found.add(int(match.group(1)))
    return sorted(found)


@dataclass(slots=True)
class IssueVerificationResult(SerializableModel):
    """Outcome of cross-checking a fix release against GitHub issues/PRs."""

    referenced_numbers: List[int] = field(default_factory=list)
    issue_states: Dict[str, str] = field(default_factory=dict)
    compare_commits_scanned: int = 0
    compare_included: bool = False
    ok: bool = False
    failure_reason: str = ""

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "IssueVerificationResult":
        """Deserialize from JSON-compatible data."""
        return cls(
            referenced_numbers=list(payload.get("referenced_numbers", [])),
            issue_states=dict(payload.get("issue_states", {})),
            compare_commits_scanned=int(payload.get("compare_commits_scanned", 0)),
            compare_included=bool(payload.get("compare_included", False)),
            ok=bool(payload.get("ok", False)),
            failure_reason=str(payload.get("failure_reason", "")),
        )


def verify_issue_closure_chain(
    *,
    repo_full_name: str,
    baseline_release: ReleaseRecord,
    fix_release: ReleaseRecord,
    fetch_json: Callable[[str], Any],
) -> IssueVerificationResult:
    """
    Verify that every issue/PR referenced by the fix release is closed on GitHub.

    References are collected from:
    1) The fix release title and body (same signals as human-facing release notes).
    2) Commit messages between baseline and fix tags (release -> commits -> issues).

    This mirrors SWE-bench-style expectations: fixes are tracked on GitHub and the
    linked issues/PRs reach a closed state after the change lands.
    """
    baseline_tag = baseline_release.tag_name or baseline_release.release_id
    fix_tag = fix_release.tag_name or fix_release.release_id
    texts: List[str] = [fix_release.body or "", fix_release.title or ""]
    numbers = extract_tracked_issue_numbers(texts)

    compare_included = False
    commits_scanned = 0
    if baseline_tag and fix_tag:
        compare_url = (
            f"https://api.github.com/repos/{repo_full_name}/compare/"
            f"{quote(baseline_tag, safe='')}...{quote(fix_tag, safe='')}"
        )
        try:
            payload = fetch_json(compare_url)
            if isinstance(payload, dict):
                commits = payload.get("commits", [])
                if isinstance(commits, list):
                    compare_included = True
                    commits_scanned = len(commits)
                    for item in commits:
                        if not isinstance(item, dict):
                            continue
                        commit = item.get("commit")
                        if not isinstance(commit, dict):
                            continue
                        message = str(commit.get("message", "") or "")
                        numbers.extend(extract_tracked_issue_numbers([message]))
        except FetchError:
            compare_included = False

    unique_sorted = sorted(set(numbers))
    if not unique_sorted:
        return IssueVerificationResult(
            referenced_numbers=[],
            issue_states={},
            compare_commits_scanned=commits_scanned,
            compare_included=compare_included,
            ok=False,
            failure_reason="no_issue_references_for_verification",
        )

    states: Dict[str, str] = {}
    for number in unique_sorted:
        issue_url = f"https://api.github.com/repos/{repo_full_name}/issues/{number}"
        try:
            payload = fetch_json(issue_url)
            state = ""
            if isinstance(payload, dict):
                state = str(payload.get("state", "") or "")
            states[str(number)] = state
        except FetchError:
            return IssueVerificationResult(
                referenced_numbers=unique_sorted,
                issue_states=states,
                compare_commits_scanned=commits_scanned,
                compare_included=compare_included,
                ok=False,
                failure_reason="issue_metadata_fetch_failed",
            )

    open_numbers = [n for n in unique_sorted if states.get(str(n), "") != "closed"]
    if open_numbers:
        return IssueVerificationResult(
            referenced_numbers=unique_sorted,
            issue_states=states,
            compare_commits_scanned=commits_scanned,
            compare_included=compare_included,
            ok=False,
            failure_reason="open_tracked_issues",
        )

    return IssueVerificationResult(
        referenced_numbers=unique_sorted,
        issue_states=states,
        compare_commits_scanned=commits_scanned,
        compare_included=compare_included,
        ok=True,
        failure_reason="",
    )
