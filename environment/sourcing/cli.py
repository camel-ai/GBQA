from __future__ import annotations

import argparse
from pathlib import Path
import sys

from dotenv import load_dotenv

from .fetcher import FetchError
from .pipeline import DEFAULT_STATE_DIR, SourcingPipeline
from .providers import PROVIDER_TYPES
from .providers.base import ProviderConfig
from .verification.daytona import DaytonaEnvironmentVerifier
from .verification.fake import FakeEnvironmentVerifier


DEFAULT_OUTPUT_DIR = Path("environment/catalog/runs/dev")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Prepare GBQA software environments.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="discover, filter, score, and rank candidates")
    run_parser.add_argument("--provider", default="github", choices=sorted(PROVIDER_TYPES))
    run_parser.add_argument("--query", default="archived:false fork:false stars:>=10 mirror:false")
    run_parser.add_argument("--limit", type=int, default=100)
    run_parser.add_argument("--top-k", type=int, default=50)
    run_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    run_parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    run_parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    run_parser.add_argument("--no-resume", dest="resume", action="store_false")

    verify_parser = subparsers.add_parser("verify", help="verify ranked candidates")
    verify_parser.add_argument("--input", type=Path, required=True)
    verify_parser.add_argument("--provider", default="daytona", choices=("daytona", "fake"))
    verify_parser.add_argument("--top-k", type=int, default=20)
    verify_parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    verify_parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    verify_parser.add_argument("--no-resume", dest="resume", action="store_false")

    args = parser.parse_args(argv)
    if args.command == "run":
        provider = PROVIDER_TYPES[args.provider](
            config=ProviderConfig(github_query=args.query),
        )
        pipeline = SourcingPipeline(
            output_dir=args.output_dir,
            provider=provider,
            state_dir=args.state_dir,
            resume=args.resume,
        )
        try:
            result = pipeline.run(query=args.query, limit=args.limit, top_k=args.top_k)
        except FetchError as exc:
            print(f"provider fetch failed: {exc}", file=sys.stderr)
            if "rate limit" in exc.body.lower():
                print(
                    "GitHub rate limit exceeded. Set GITHUB_TOKEN in the root .env "
                    "or export it before running sourcing.",
                    file=sys.stderr,
                )
            return 1
        print(
            f"ranked={len(result.ranked)} rejected={len(result.rejected)} "
            f"skipped={result.skipped_repositories} "
            f"resume={args.resume} "
            f"output={args.output_dir}"
        )
        return 0
    if args.command == "verify":
        output_dir = args.input.parent if args.input.is_file() else args.input
        verifier = DaytonaEnvironmentVerifier() if args.provider == "daytona" else FakeEnvironmentVerifier()
        pipeline = SourcingPipeline(
            output_dir=output_dir,
            verifier=verifier,
            state_dir=args.state_dir,
            resume=args.resume,
        )
        results = pipeline.verify(top_k=args.top_k)
        passed = sum(1 for result in results if result.status == "passed")
        print(f"verified={len(results)} passed={passed} output={output_dir / 'verified.jsonl'}")
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
