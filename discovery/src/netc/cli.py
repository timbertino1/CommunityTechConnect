"""The `netc` command line."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from netc.connectors import default_connectors
from netc.fetch import FixtureHttp, SafeHttp
from netc.pipeline.discover_events import discover_events
from netc.pipeline.validate import validate_data
from netc.storage import DataStore, StorageError

PLANNED_COMMANDS = {
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
    discover = commands.add_parser(
        "discover-events",
        help="Collect events from known sources and update data/.",
        description="Collect events from known sources and update data/.",
    )
    discover.add_argument("--data-dir", type=Path, default=Path("data"), help="data directory")
    discover.add_argument(
        "--offline", action="store_true", help="read pages from --fixtures instead of the web"
    )
    discover.add_argument("--fixtures", type=Path, help="directory with index.json (offline)")
    discover.add_argument("--dry-run", action="store_true", help="report without writing data/")
    discover.add_argument("--force", action="store_true", help="read sources even if not due")
    discover.add_argument(
        "--now", type=_utc_datetime, help="run as if it were this UTC time (ISO 8601)"
    )
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
    if args.command == "discover-events":
        return _discover(args)
    print(f"netc {args.command}: not implemented yet", file=sys.stderr)
    return 2


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("--now needs a time zone, e.g. 2026-10-18T12:00:00Z")
    return parsed.astimezone(UTC)


def _discover(args: argparse.Namespace) -> int:
    now: datetime = args.now or datetime.now(UTC)
    store = DataStore(args.data_dir)
    connectors = default_connectors(lambda: now)
    try:
        if args.offline:
            if args.fixtures is None:
                print("netc discover-events: --offline needs --fixtures DIR", file=sys.stderr)
                return 2
            report = discover_events(
                store, FixtureHttp(args.fixtures), connectors, now=now,
                dry_run=args.dry_run, force=args.force,
            )  # fmt: skip
        else:
            domain = os.environ.get("NETC_SITE_DOMAIN", "netechconnect.example")
            with SafeHttp(site_domain=domain) as http:
                report = discover_events(
                    store, http, connectors, now=now, dry_run=args.dry_run, force=args.force
                )
    except (StorageError, RuntimeError) as exc:
        print(f"netc discover-events: {exc}", file=sys.stderr)
        return 1
    listings = ", ".join(f"{k} {v}" for k, v in sorted(report.listings.items())) or "none"
    print(
        f"Sources: {report.sources}. Listings: {listings}. "
        f"Events stored: {report.events_total}. New review items: {report.new_reviews}."
        + ("" if report.written else " (dry run: nothing written)")
    )
    return 0


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
