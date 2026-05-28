from __future__ import annotations

import argparse
from pathlib import Path

from .generator import generate_task_packages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate GBQA task packages.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--input", type=Path, required=True)
    generate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "generate":
        generated = generate_task_packages(input_path=args.input, output_dir=args.output)
        for path in generated:
            print(path)
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
