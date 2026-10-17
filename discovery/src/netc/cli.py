"""The `netc` command line."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from netc.pipeline.validate import validate_data

PLANNED_COMMANDS = {
    "discover-events": "Collect events from known sources and update data/.",
    "discover-sources": "Find and evaluate new event sources.",
    "apply-review": "Apply decisions from a merged review pull request.",
    "build-site": "Build the static site from data/.",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netc", description="NETechConnect discovery pipeline and site generator."
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for name, help_text in PLANNED_COMMANDS.items():
        commands.add_parser(name, help=help_text, description=help_text)
    validate = commands.add_parser(
        "validate-data",
        help="Check every file in data/ against its schema and the data rules.",
        description="Check every file in data/ against its schema and the data rules.",
    )
    validate.add_argument(
        "--data-dir", type=Path, default=Path("data"), help="data directory (default: ./data)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate-data":
        return _validate(args.data_dir)
    print(f"netc {args.command}: not implemented yet", file=sys.stderr)
    return 2


def _validate(data_dir: Path) -> int:
    report = validate_data(data_dir)
    if report.ok:
        print(f"OK: {report.files_checked} files in {data_dir} are valid.")
        return 0
    for line in report.errors:
        print(line, file=sys.stderr)
    count = len(report.errors)
    print(
        f"validate-data: {count} problem{'s' if count != 1 else ''} in {data_dir}", file=sys.stderr
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
