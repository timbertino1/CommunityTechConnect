"""The `netc` command line."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from netc.connectors import default_connectors
from netc.fetch import FixtureHttp, SafeHttp
from netc.github.health import LastAlert, alert_comment, build_health
from netc.github.markdown import code_span, plain_name
from netc.github.review_pr import build_review_pr, has_ticks, read_decisions
from netc.models import SourceStatus
from netc.pipeline.discover_events import discover_events
from netc.pipeline.review import ApplyResult, apply_decisions, check_review_merge
from netc.pipeline.run_report import render_markdown
from netc.pipeline.validate import validate_data
from netc.site.build import BuildError, build_site
from netc.storage import DataStore, StorageError

PLANNED_COMMANDS = {
    "discover-sources": "Find and evaluate new event sources.",
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
        "--report", type=Path, help="also write a Markdown run report to this file"
    )
    discover.add_argument(
        "--now", type=_utc_datetime, help="run as if it were this UTC time (ISO 8601)"
    )
    site = commands.add_parser(
        "build-site",
        help="Build the static site from data/.",
        description="Build the static site from data/.",
    )
    site.add_argument("--data", type=Path, default=Path("data"), help="data directory")
    site.add_argument("--out", type=Path, default=Path("dist"), help="output directory")
    site.add_argument("--web", type=Path, default=Path("web"), help="web assets directory")
    site.add_argument("--now", type=_utc_datetime, help="build as if it were this UTC time")
    review = commands.add_parser(
        "review-pr",
        help="Write the review PR's title, description and data/review/open.json.",
        description=(
            "Write the review PR for every pending item: OUT/title.txt, OUT/body.md and "
            "data/review/open.json. OUT/status says ready, none (nothing pending) or kept "
            "(the open PR already has ticked boxes, so it is left alone)."
        ),
    )
    review.add_argument("--data-dir", type=Path, default=Path("data"), help="data directory")
    review.add_argument("--out", type=Path, required=True, help="directory for the PR files")
    review.add_argument("--current-body", type=Path, help="description of the open review PR")
    review.add_argument("--now", type=_utc_datetime, help="run as if it were this UTC time")
    apply = commands.add_parser(
        "apply-review",
        help="Apply decisions from a merged review pull request.",
        description=(
            "Apply the ticks in a merged review PR, after checking the GitHub API responses "
            "show it is the bot's review PR merged by an admin as exactly --commit."
        ),
    )
    apply.add_argument("--data-dir", type=Path, default=Path("data"), help="data directory")
    apply.add_argument("--commit", required=True, help="the pushed commit (github.sha)")
    apply.add_argument("--pr", type=Path, required=True, help="GET /pulls/{number} response")
    apply.add_argument(
        "--permission", type=Path, required=True, help="collaborator permission response"
    )
    apply.add_argument(
        "--edits", type=Path, required=True, help="GraphQL response with lastEditedAt"
    )
    apply.add_argument("--bot-login", required=True, help="the App's login, e.g. name[bot]")
    apply.add_argument("--report", type=Path, help="write a Markdown summary to this file")
    apply.add_argument("--now", type=_utc_datetime, help="run as if it were this UTC time")
    health = commands.add_parser(
        "health-issue",
        help="Write the Discovery health issue's description and any alert comment.",
        description=(
            "Write OUT/body.md (the Discovery health issue's description) and, when something "
            "needs the owner and they haven't been told recently, OUT/comment.md."
        ),
    )
    health.add_argument("--data-dir", type=Path, default=Path("data"), help="data directory")
    health.add_argument("--out", type=Path, required=True, help="directory for the issue files")
    health.add_argument("--owner", required=True, help="GitHub login to mention in alerts")
    health.add_argument(
        "--previous-status", type=Path, help="main's state/source_status.json from before the run"
    )
    health.add_argument(
        "--last-alert", type=Path, help='the last alert comment as {"created_at", "body"} JSON'
    )
    health.add_argument("--now", type=_utc_datetime, help="run as if it were this UTC time")
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
    if args.command == "build-site":
        return _build_site(args)
    if args.command == "review-pr":
        return _review_pr(args)
    if args.command == "apply-review":
        return _apply_review(args)
    if args.command == "health-issue":
        return _health_issue(args)
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
    if args.report is not None:
        args.report.write_bytes(render_markdown(report).encode("utf-8"))
    return 0


def _build_site(args: argparse.Namespace) -> int:
    now: datetime = args.now or datetime.now(UTC)
    domain = os.environ.get("NETC_SITE_DOMAIN", "netechconnect.example")
    try:
        report = build_site(args.data, args.out, args.web, now=now, site_domain=domain)
    except (StorageError, BuildError) as exc:
        print(f"netc build-site: {exc}", file=sys.stderr)
        return 1
    print(
        f"Built {report.pages} pages into {args.out}; "
        f"{report.events_listed} upcoming events listed."
    )
    return 0


def _review_pr(args: argparse.Namespace) -> int:
    now: datetime = args.now or datetime.now(UTC)
    args.out.mkdir(parents=True, exist_ok=True)
    status = args.out / "status"
    if args.current_body is not None and has_ticks(args.current_body.read_text(encoding="utf-8")):
        status.write_bytes(b"kept\n")
        print("The open review PR already has ticked boxes; leaving it as it is.")
        return 0
    store = DataStore(args.data_dir)
    try:
        areas = store.read_areas()
        pr = build_review_pr(
            store.read_review_queue(),
            store.read_events(),
            store.read_sources(),
            categories={c.id: c.label for c in store.read_categories()},
            areas={a.id: a.label for a in areas.areas} if areas else {},
            now=now,
        )
    except StorageError as exc:
        print(f"netc review-pr: {exc}", file=sys.stderr)
        return 1
    if pr is None:
        status.write_bytes(b"none\n")
        print("Nothing is waiting for review.")
        return 0
    store.write_review_open(pr.review_ids)
    (args.out / "title.txt").write_bytes(pr.title.encode("utf-8") + b"\n")
    (args.out / "body.md").write_bytes(pr.body.encode("utf-8"))
    status.write_bytes(b"ready\n")
    more = f"; {pr.waiting} more wait for the next PR" if pr.waiting else ""
    print(f"{pr.title}{more}.")
    return 0


def _apply_review(args: argparse.Namespace) -> int:
    now: datetime = args.now or datetime.now(UTC)
    try:
        pr = json.loads(args.pr.read_text(encoding="utf-8"))
        permission = json.loads(args.permission.read_text(encoding="utf-8"))
        edits = json.loads(args.edits.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"netc apply-review: unreadable input: {exc}", file=sys.stderr)
        return 1
    if not all(isinstance(x, dict) for x in (pr, permission, edits)):
        print("netc apply-review: the GitHub responses must be JSON objects", file=sys.stderr)
        return 1
    check = check_review_merge(pr, permission, edits, commit=args.commit, bot_login=args.bot_login)
    if not check.ok or check.number is None:
        print(f"netc apply-review: not applied: {check.reason}", file=sys.stderr)
        return 1
    body = pr.get("body")
    store = DataStore(args.data_dir)
    try:
        result = apply_decisions(
            store,
            pr_number=check.number,
            decisions=read_decisions(body if isinstance(body, str) else ""),
            open_ids=store.read_review_open(),
            now=now,
        )
    except StorageError as exc:
        print(f"netc apply-review: {exc}", file=sys.stderr)
        return 1
    summary = _apply_summary(result)
    print(summary.splitlines()[2])
    if args.report is not None:
        args.report.write_bytes(summary.encode("utf-8"))
    return 0


def _apply_summary(result: ApplyResult) -> str:
    lines = [
        f"## Decisions from review PR #{result.pr_number}",
        "",
        f"{len(result.approved)} approved, {len(result.rejected)} rejected, "
        f"{result.still_pending} left waiting for the next review PR.",
    ]
    decided = (("Approved (published)", result.approved),
               ("Rejected (kept off the site)", result.rejected))  # fmt: skip
    for heading, items in decided:
        if items:
            lines += ["", f"### {heading}", ""]
            lines += [f"- {code_span(result.titles.get(i.id, i.ref))} `{i.id}`" for i in items]
    changed = (("Promoted to trusted", result.promoted),
               ("Paused (more rejected than approved)", result.paused))  # fmt: skip
    for heading, sources in changed:
        if sources:
            lines += ["", f"### {heading}", ""]
            lines += [
                f"- {plain_name(s.name)} ({s.approved_count} approved, {s.rejected_count} rejected)"
                for s in sources
            ]
    if result.ignored:
        lines += [
            "",
            f"Ignored {len(result.ignored)} ticked item(s) that were not in this PR's "
            "snapshot or were already decided.",
        ]
    return "\n".join(lines) + "\n"


def _health_issue(args: argparse.Namespace) -> int:
    now: datetime = args.now or datetime.now(UTC)
    store = DataStore(args.data_dir)
    try:
        health = build_health(
            store.read_sources(),
            store.read_source_status(),
            store.read_events(),
            store.read_review_queue(),
            store.read_mentions(),
            now=now,
            previous_status=_previous_status(args.previous_status),
        )
        comment = alert_comment(
            health, owner=args.owner, last=_last_alert(args.last_alert), now=now
        )
    except (StorageError, ValueError) as exc:
        print(f"netc health-issue: {exc}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "body.md").write_bytes(health.body.encode("utf-8"))
    alert = args.out / "comment.md"
    alert.unlink(missing_ok=True)
    if comment is not None:
        alert.write_bytes(comment.encode("utf-8"))
    count = len(health.attention)
    needs = "1 thing needs" if count == 1 else f"{count} things need"
    alert_note = "; posting an alert." if comment else "; no alert this time." if count else "."
    print(f"{needs} attention{alert_note}")
    return 0


def _previous_status(path: Path | None) -> dict[str, SourceStatus] | None:
    """Main's run status from before this run; unreadable means unknown, not an error."""
    if path is None or not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): SourceStatus.model_validate(v) for k, v in raw.items()}
    except (OSError, ValueError, AttributeError) as exc:
        print(f"netc health-issue: ignoring --previous-status: {exc}", file=sys.stderr)
        return None


def _last_alert(path: Path | None) -> LastAlert | None:
    """The bot's last alert comment, as the script found it; none (or unreadable) means none."""
    if path is None or not path.is_file() or not path.read_text(encoding="utf-8").strip():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("body"), str):
        raise ValueError("--last-alert must be a JSON object with created_at and body")
    try:
        posted = _utc_datetime(str(raw.get("created_at")))
    except argparse.ArgumentTypeError as exc:
        raise ValueError(f"--last-alert created_at: {exc}") from exc
    return LastAlert(posted, raw["body"])


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
