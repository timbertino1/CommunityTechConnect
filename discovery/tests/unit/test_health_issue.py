"""The Discovery health issue: its description and the alert comment (T124; FR-042, FR-044)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from netc.github.health import (
    ALERT_AFTER_FAILURES,
    HEALTH_TITLE,
    Health,
    LastAlert,
    alert_comment,
    build_health,
)
from netc.models import Event, EventMention, ReviewItem, Source, SourceStatus
from tests.data_samples import make_event, make_mention, make_source, make_status, utc
from tests.review_support import NOW, campus_source, held_event, queue_item

pytestmark = pytest.mark.unit

OWNER = "timbertino1"


def health(
    sources: list[Source] | None = None,
    statuses: dict[str, SourceStatus] | None = None,
    *,
    events: list[Event] | None = None,
    queue: list[ReviewItem] | None = None,
    mentions: list[EventMention] | None = None,
    previous: dict[str, SourceStatus] | None = None,
    now: datetime = NOW,
    ai_spent: float | None = None,
) -> Health:
    return build_health(
        sources if sources is not None else [make_source()],
        statuses if statuses is not None else {},
        events or [],
        queue or [],
        mentions or [],
        now=now,
        previous_status=previous,
        ai_spent_usd=ai_spent,
    )


def section(body: str, heading: str) -> str:
    return body.split(f"### {heading}\n", 1)[1].split("\n### ", 1)[0].strip()


def failing(n: int, error: str = "TimeoutError: timed out") -> SourceStatus:
    return make_status(last_attempt=NOW, consecutive_failures=n, last_error=error)


def ok(found: int = 2, when: datetime = NOW) -> SourceStatus:
    return make_status(last_attempt=when, last_success=when, events_found_last_run=found)


def keys(h: Health) -> set[str]:
    return {a.key for a in h.attention}


# --- The issue and its Sources table (FR-042)


def test_the_issue_is_called_discovery_health() -> None:
    assert HEALTH_TITLE == "Discovery health"


def test_the_sources_table_lists_every_source_with_its_health() -> None:
    sources = [
        make_source("src_omaha-python", name="Omaha Python"),
        make_source("src_paused", name="Paused group", status="paused", trust="probationary"),
        make_source("src_new", name="Brand new"),
    ]
    statuses = {"src_omaha-python": ok(found=3), "src_paused": failing(1)}
    table = section(health(sources, statuses).body, "Sources").splitlines()
    assert table[0] == (
        "| Source | Status | Trust | How found | Last successful check | Events found last run "
        "| Failures in a row |"
    )
    assert table[2:] == [
        "| Brand new | active | trusted | pre-configured | never | - | 0 |",
        "| Omaha Python | active | trusted | pre-configured | Mon, Oct 19, 2026, 6:00 AM CT "
        "| 3 | 0 |",
        "| Paused group | paused | probationary | pre-configured | never | - | 1 |",
    ]


@pytest.mark.parametrize(
    ("overrides", "label"),
    [
        ({"origin": "preconfigured"}, "pre-configured"),
        ({"origin": "admin"}, "added by the owner"),
        ({"origin": "discovered", "found_via": "web_search"}, "discovered (web search)"),
        ({"origin": "discovered", "found_via": "link_graph"}, "discovered (linked from a source)"),
        ({"origin": "suggested", "found_via": "suggestion"}, "suggested by a visitor"),
    ],
)
def test_how_each_source_was_found(overrides: dict[str, Any], label: str) -> None:
    body = health([make_source(**overrides)]).body
    assert f"| active | trusted | {label} |" in section(body, "Sources")


# --- Failing sources


def test_failing_sources_show_their_error_and_count() -> None:
    sources = [make_source("src_unl", name="UNL computing"), make_source()]
    statuses = {"src_unl": failing(3, "RobotsUnavailableError: robots.txt timed out")}
    text = section(health(sources, statuses).body, "Failing sources")
    assert text == (
        "- **UNL computing** (3 runs in a row, never succeeded): "
        "`RobotsUnavailableError: robots.txt timed out`"
    )


def test_last_success_is_shown_for_a_source_that_used_to_work() -> None:
    status = failing(1).model_copy(update={"last_success": utc(2026, 10, 15, 11)})
    text = section(health([make_source()], {"src_omaha-python": status}).body, "Failing sources")
    assert "(first failure, last worked Oct 15, 2026)" in text


def test_paused_sources_are_not_listed_as_failing() -> None:
    sources = [make_source(status="paused")]
    body = health(sources, {"src_omaha-python": failing(4)}).body
    assert section(body, "Failing sources") == "None."


def test_a_single_failure_is_shown_but_needs_no_action() -> None:
    h = health([make_source()], {"src_omaha-python": failing(1)})
    assert "first failure" in section(h.body, "Failing sources")
    assert h.attention == []


def test_repeated_failures_need_attention() -> None:
    h = health([make_source()], {"src_omaha-python": failing(ALERT_AFTER_FAILURES)})
    assert keys(h) == {"failing:src_omaha-python"}
    assert "**Needs attention:**" in h.body


def test_nothing_to_do_is_said_plainly() -> None:
    h = health([make_source()], {"src_omaha-python": ok()})
    assert h.attention == []
    assert "Nothing needs attention." in h.body
    assert section(h.body, "Failing sources") == "None."


# --- Waiting for review


def test_pending_review_items_need_attention() -> None:
    events = [held_event(3), held_event(4)]
    h = health([campus_source()], events=events, queue=[queue_item(e) for e in events])
    assert keys(h) == {"review"}
    assert section(h.body, "Waiting for review").startswith("2 items are waiting in the review PR")


def test_items_the_review_pr_would_not_list_are_not_counted() -> None:
    ended = held_event(4, start=utc(2026, 10, 1, 18))
    decided = held_event(5)
    queue = [queue_item(ended), queue_item(decided, decision="approved", decided_in_pr=3)]
    h = health([campus_source()], events=[ended, decided], queue=queue)
    assert h.attention == []
    assert section(h.body, "Waiting for review") == "Nothing is waiting."


# --- Quiet groups


def past_meetups(source_id: str, days_ago: list[int]) -> list[Event]:
    return [
        make_event(
            slug=f"meetup-{d}",
            start=NOW - timedelta(days=d),
            url=f"https://example.org/{source_id}/{d}/",
            source_id=source_id,
        )
        for d in days_ago
    ]


def test_a_group_that_stopped_posting_is_quiet() -> None:
    sources = [make_source("src_omaha-python", name="Omaha Python")]
    events = past_meetups("src_omaha-python", [40, 54, 68, 82])
    text = section(health(sources, events=events).body, "Quiet groups")
    assert text == "- **Omaha Python**: last event Sep 9, 2026; usually every 14 days."


def test_a_group_with_an_upcoming_event_is_not_quiet() -> None:
    events = past_meetups("src_omaha-python", [40, 54, 68, 82])
    events.append(make_event(slug="next", start=NOW + timedelta(days=5)))
    assert section(health(events=events).body, "Quiet groups") == "None."


def test_a_group_within_its_usual_gap_is_not_quiet() -> None:
    events = past_meetups("src_omaha-python", [10, 24, 38, 52])
    assert section(health(events=events).body, "Quiet groups") == "None."


def test_too_few_events_to_tell() -> None:
    events = past_meetups("src_omaha-python", [100, 114])
    assert section(health(events=events).body, "Quiet groups") == "None."


def test_cancelled_and_rejected_events_do_not_count_toward_cadence() -> None:
    events = past_meetups("src_omaha-python", [40, 54, 68, 82])
    events.append(
        make_event(slug="cancelled", start=NOW - timedelta(days=3), status="cancelled",
                   url="https://example.org/c/")
    )  # fmt: skip
    assert "Omaha Python" in section(health(events=events).body, "Quiet groups")


# --- Mentions, new sources, spend, schedule


def test_unresolved_mentions_are_counted_and_listed() -> None:
    open_one = make_mention("men_0000000000aa")
    resolved = make_mention("men_0000000000bb").model_copy(update={"resolution": "resolved"})
    text = section(health(mentions=[open_one, resolved]).body, "Unresolved mentions")
    assert text == "1 mention not yet matched to an event:\n\n- `Lincoln DevOps night` (newsletter)"


def test_new_sources_this_week_are_grouped_by_how_they_were_found() -> None:
    sources = [
        make_source("src_a", added_at="2026-10-17"),
        make_source("src_b", added_at="2026-10-18", origin="discovered", found_via="web_search"),
        make_source("src_c", added_at="2026-10-18", origin="discovered", found_via="web_search"),
        make_source("src_old", added_at="2026-09-01"),
    ]
    text = section(health(sources).body, "New sources this week")
    assert text == "- discovered (web search): 2\n- pre-configured: 1"


def test_ai_spend_says_not_used_until_the_first_call() -> None:
    text = section(health().body, "AI and search spend")
    assert text.startswith("AI second opinion: not used yet.")
    assert "Web search: not in use yet" in text


def test_ai_spend_shows_this_months_total() -> None:
    h = health(ai_spent=0.0412)
    assert "AI second opinion: $0.04 of $1.00 this month" in section(h.body, "AI and search spend")
    assert h.attention == []


def test_a_spent_ai_budget_needs_attention() -> None:
    h = health(ai_spent=1.0)
    assert keys(h) == {"ai-budget"}
    last = LastAlert(NOW - timedelta(days=2), "<!-- netc-health-alert: ai-budget -->")
    assert alert_comment(h, owner=OWNER, last=last, now=NOW) is None  # already told


def test_stale_data_on_main_needs_attention() -> None:
    previous = {"src_omaha-python": ok(when=NOW - timedelta(hours=40))}
    h = health(previous=previous)
    assert keys(h) == {"schedule"}
    assert "40 hours" in section(h.body, "Schedule")


def test_recent_data_on_main_is_fine() -> None:
    h = health(previous={"src_omaha-python": ok(when=NOW - timedelta(hours=12))})
    assert h.attention == []
    assert "12 hours earlier" in section(h.body, "Schedule")


def test_no_earlier_run_is_not_an_alarm() -> None:
    h = health(previous={})
    assert h.attention == []
    assert "No earlier run is recorded." in section(h.body, "Schedule")


# --- Untrusted text stays inert


def test_names_and_errors_cannot_mention_or_link() -> None:
    sources = [make_source(name="Evil @everyone #1 group")]
    statuses = {"src_omaha-python": failing(2, "boom @someone see https://evil.example/x")}
    body = health(sources, statuses).body
    assert "@everyone" not in body and "#1" not in body
    assert "`boom @someone see https://evil.example/x`" in body
    assert f"@{OWNER}" not in body


# --- The alert comment (FR-044)


def needing(*attention_keys: str) -> Health:
    sources = [make_source(f"src_{k}", name=f"Group {k}") for k in attention_keys]
    statuses = {f"src_{k}": failing(ALERT_AFTER_FAILURES) for k in attention_keys}
    return health(sources, statuses)


def test_no_comment_when_nothing_needs_attention() -> None:
    assert alert_comment(health(), owner=OWNER, last=None, now=NOW) is None


def test_the_comment_mentions_the_owner_and_lists_what_needs_doing() -> None:
    text = alert_comment(needing("a"), owner=OWNER, last=None, now=NOW)
    assert text is not None
    assert text.startswith(f"@{OWNER} the discovery bot needs your attention:")
    assert "- **Group a** has failed 2 runs in a row" in text
    assert "<!-- netc-health-alert: failing:src_a -->" in text


def test_at_most_one_comment_a_day() -> None:
    last = LastAlert(NOW - timedelta(hours=5), "<!-- netc-health-alert: failing:src_a -->")
    assert alert_comment(needing("a", "b"), owner=OWNER, last=last, now=NOW) is None


def test_the_same_problem_is_not_repeated_every_day() -> None:
    last = LastAlert(NOW - timedelta(days=2), "<!-- netc-health-alert: failing:src_a -->")
    assert alert_comment(needing("a"), owner=OWNER, last=last, now=NOW) is None


def test_a_new_problem_is_reported_the_next_day() -> None:
    last = LastAlert(NOW - timedelta(days=1), "<!-- netc-health-alert: failing:src_a -->")
    text = alert_comment(needing("a", "b"), owner=OWNER, last=last, now=NOW)
    assert text is not None and "failing:src_a failing:src_b" in text


def test_an_unresolved_problem_is_repeated_weekly() -> None:
    last = LastAlert(NOW - timedelta(days=7), "<!-- netc-health-alert: failing:src_a -->")
    assert alert_comment(needing("a"), owner=OWNER, last=last, now=NOW) is not None


def test_a_last_comment_without_a_marker_counts_as_no_keys() -> None:
    last = LastAlert(NOW - timedelta(days=2), "Something a person wrote")
    assert alert_comment(needing("a"), owner=OWNER, last=last, now=NOW) is not None


@pytest.mark.parametrize("owner", ["", "two words", "@owner", "a" * 40, "-leading"])
def test_the_owner_must_be_a_github_login(owner: str) -> None:
    with pytest.raises(ValueError, match="GitHub login"):
        alert_comment(needing("a"), owner=owner, last=None, now=NOW)


def test_the_body_fits_in_an_issue() -> None:
    sources = [make_source(f"src_group-{i}", name=f"Group {i} " + "x" * 150) for i in range(400)]
    statuses = {s.id: failing(5, "e" * 400) for s in sources}
    assert len(health(sources, statuses).body) <= 65_536
