"""CLI entrypoint for the Hub sourcing pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .auth import (
    CredentialStore,
    InteractiveAuthFlow,
)
from .pipeline import SourcingPipeline
from .providers import PROVIDER_TYPES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hub environment sourcing pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("auth", "discover", "score", "select", "publish", "run"):
        subparser = subparsers.add_parser(command)
        _add_common_args(subparser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    auth_flow = InteractiveAuthFlow(store=CredentialStore())
    if args.command in {"discover", "run"}:
        auth_flow.bootstrap(args.providers)
    pipeline = SourcingPipeline(output_dir=Path(args.output_dir))
    catalog_path = Path(args.output_dir) / "candidates.jsonl"
    attempts = 0
    while True:
        try:
            if args.command == "auth":
                auth_flow.configure(args.providers)
                return 0

            if args.command == "discover":
                candidates = pipeline.discover(
                    providers=args.providers,
                    limit=args.limit,
                    allow_partial=args.allow_partial,
                )
                pipeline._write_jsonl(catalog_path, candidates)
                _print_summary("discovered", candidates, all_candidates=candidates)
                return 0

            if args.command == "score":
                candidates = pipeline.load_candidates(catalog_path)
                scored = pipeline.score(candidates)
                pipeline._write_jsonl(catalog_path, scored)
                _print_summary("scored", scored, all_candidates=scored)
                return 0

            if args.command == "select":
                candidates = pipeline.load_candidates(catalog_path)
                scored = pipeline.score(candidates)
                selected = pipeline.select(
                    scored,
                    minimum_score=args.minimum_score,
                    max_candidates=args.max_candidates,
                )
                _print_summary("selected", selected, all_candidates=scored)
                return 0

            if args.command == "publish":
                candidates = pipeline.load_candidates(catalog_path)
                scored = pipeline.score(candidates)
                selected = pipeline.select(
                    scored,
                    minimum_score=args.minimum_score,
                    max_candidates=args.max_candidates,
                )
                pipeline.publish(all_candidates=scored, selected=selected)
                _print_summary("published", selected, all_candidates=scored)
                return 0

            selected = pipeline.run(
                providers=args.providers,
                limit=args.limit,
                allow_partial=args.allow_partial,
                minimum_score=args.minimum_score,
                max_candidates=args.max_candidates,
            )
            all_candidates = pipeline.load_candidates(catalog_path)
            _print_summary("run", selected, all_candidates=all_candidates)
            return 0
        except Exception as exc:
            attempts += 1
            if attempts > 2 or not auth_flow.recoverable_auth_error(exc):
                raise


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parents[1] / "catalog"),
        help="Catalog output directory.",
    )
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=sorted(PROVIDER_TYPES.keys()),
        default=sorted(PROVIDER_TYPES.keys()),
        help="Provider adapters to run.",
    )
    parser.add_argument("--limit", type=int, default=5, help="Per-provider discovery limit.")
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Continue when a provider fails.",
    )
    parser.add_argument(
        "--minimum-score",
        type=float,
        default=60.0,
        help="Minimum score required for promotion.",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        help="Maximum number of promoted candidates.",
    )


def _print_summary(stage: str, candidates, *, all_candidates=None) -> None:
    selected = list(candidates)
    discovered = list(all_candidates) if all_candidates is not None else selected
    payload = {
        "stage": stage,
        "discovered_count": len(discovered),
        "selected_count": len(selected),
        "rejected_count": max(len(discovered) - len(selected), 0),
        "selected": [
            {
                "game_id": candidate.game_id,
                "title": candidate.title,
                "provider": candidate.provider,
                "score": candidate.score,
                "complexity": candidate.complexity,
                "homepage_url": candidate.homepage_url,
                "source_repo_url": candidate.source_repo_url,
                "patch_notes_url": candidate.patch_notes_url,
            }
            for candidate in selected
        ],
    }
    rejected = [candidate for candidate in discovered if candidate not in selected]
    if rejected:
        payload["rejected"] = [
            {
                "game_id": candidate.game_id,
                "title": candidate.title,
                "score": candidate.score,
                "complexity": candidate.complexity,
                "homepage_url": candidate.homepage_url,
                "rejection_reasons": candidate.rejection_reasons,
            }
            for candidate in rejected
        ]
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
