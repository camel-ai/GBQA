"""Tests for GitHub issue/PR closure verification."""

from __future__ import annotations

import unittest

from hub.sourcing.fetcher import StaticFetcher
from hub.sourcing.issue_verification import (
    extract_tracked_issue_numbers,
    verify_issue_closure_chain,
)
from hub.sourcing.models import ReleaseRecord


class IssueVerificationTests(unittest.TestCase):
    """Cover issue number extraction and closure checks."""

    def test_extract_issue_numbers_from_hash_and_urls(self) -> None:
        text = (
            "Fixed crash (#12). See https://github.com/org/repo/pull/34 "
            "and https://github.com/org/repo/issues/56"
        )
        numbers = extract_tracked_issue_numbers([text])
        self.assertEqual(numbers, [12, 34, 56])

    def test_verify_requires_closed_issues(self) -> None:
        baseline = ReleaseRecord(
            release_id="v1.0.0",
            tag_name="v1.0.0",
            title="v1.0.0",
            published_at="2026-01-01T00:00:00Z",
            notes_url="https://example.com/r/v1.0.0",
            body="",
            artifact_urls=[],
            has_bug_fix_evidence=False,
        )
        fix = ReleaseRecord(
            release_id="v1.1.0",
            tag_name="v1.1.0",
            title="v1.1.0",
            published_at="2026-02-01T00:00:00Z",
            notes_url="https://example.com/r/v1.1.0",
            body="Fixed bug (#99)",
            artifact_urls=[],
            has_bug_fix_evidence=True,
        )
        mapping = {
            "https://api.github.com/repos/acme/demo/compare/v1.0.0...v1.1.0": {
                "commits": [],
            },
            "https://api.github.com/repos/acme/demo/issues/99": {"state": "open"},
        }
        fetcher = StaticFetcher(mapping)

        def fetch_json(url: str):
            response = fetcher.fetch(url)
            return response.json()

        result = verify_issue_closure_chain(
            repo_full_name="acme/demo",
            baseline_release=baseline,
            fix_release=fix,
            fetch_json=fetch_json,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.failure_reason, "open_tracked_issues")

    def test_verify_passes_when_all_referenced_closed(self) -> None:
        baseline = ReleaseRecord(
            release_id="v1.0.0",
            tag_name="v1.0.0",
            title="v1.0.0",
            published_at="2026-01-01T00:00:00Z",
            notes_url="https://example.com/r/v1.0.0",
            body="",
            artifact_urls=[],
            has_bug_fix_evidence=False,
        )
        fix = ReleaseRecord(
            release_id="v1.1.0",
            tag_name="v1.1.0",
            title="v1.1.0",
            published_at="2026-02-01T00:00:00Z",
            notes_url="https://example.com/r/v1.1.0",
            body="Fixed bug (#99)",
            artifact_urls=[],
            has_bug_fix_evidence=True,
        )
        mapping = {
            "https://api.github.com/repos/acme/demo/compare/v1.0.0...v1.1.0": {
                "commits": [],
            },
            "https://api.github.com/repos/acme/demo/issues/99": {"state": "closed"},
        }
        fetcher = StaticFetcher(mapping)

        def fetch_json(url: str):
            response = fetcher.fetch(url)
            return response.json()

        result = verify_issue_closure_chain(
            repo_full_name="acme/demo",
            baseline_release=baseline,
            fix_release=fix,
            fetch_json=fetch_json,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.referenced_numbers, [99])
