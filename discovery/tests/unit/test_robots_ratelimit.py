"""robots.txt, per-host delay, and per-host request budgets in SafeHttp (research R12)."""

from __future__ import annotations

import httpx
import pytest

from netc.fetch import BudgetExceededError, RobotsDisallowedError, RobotsUnavailableError
from tests.fetch_support import FakeClock, make_http, mocked_web

pytestmark = pytest.mark.unit

HTML = {"content-type": "text/html"}


def _robots(web: object, host: str, body: str) -> None:
    web.get(f"https://{host}/robots.txt").respond(  # type: ignore[attr-defined]
        200, text=body, headers={"content-type": "text/plain"}
    )


# --- robots.txt


def test_disallowed_path_is_not_fetched() -> None:
    with mocked_web() as web, make_http() as http:
        _robots(web, "example.com", "User-agent: *\nDisallow: /private\n")
        private = web.get("https://example.com/private/events").respond(200, headers=HTML)
        web.get("https://example.com/public").respond(200, headers=HTML)
        with pytest.raises(RobotsDisallowedError):
            http.get("https://example.com/private/events")
        assert not private.called
        assert http.get("https://example.com/public").status == 200


def test_rules_for_our_user_agent_are_honored() -> None:
    with mocked_web() as web, make_http() as http:
        _robots(
            web,
            "example.com",
            "User-agent: NETechConnectBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n",
        )
        with pytest.raises(RobotsDisallowedError):
            http.get("https://example.com/events")


def test_missing_robots_txt_allows_everything() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        web.get("https://example.com/events").respond(200, headers=HTML)
        assert http.get("https://example.com/events").status == 200


@pytest.mark.parametrize("status", [500, 502, 503, 429])
def test_robots_server_error_means_skip_the_host(status: int) -> None:
    with mocked_web() as web, make_http() as http:
        web.get("https://example.com/robots.txt").respond(status)
        page = web.get("https://example.com/events").respond(200, headers=HTML)
        with pytest.raises(RobotsUnavailableError):
            http.get("https://example.com/events")
        assert not page.called


def test_robots_network_failure_means_skip_the_host() -> None:
    with mocked_web() as web, make_http() as http:
        web.get("https://example.com/robots.txt").mock(side_effect=httpx.ConnectError("down"))
        page = web.get("https://example.com/events").respond(200, headers=HTML)
        with pytest.raises(RobotsUnavailableError):
            http.get("https://example.com/events")
        assert not page.called


def test_robots_is_fetched_once_per_host_per_run() -> None:
    with mocked_web() as web, make_http() as http:
        _robots(web, "example.com", "User-agent: *\nAllow: /\n")
        web.get("https://example.com/a").respond(200, headers=HTML)
        web.get("https://example.com/b").respond(200, headers=HTML)
        http.get("https://example.com/a")
        http.get("https://example.com/b")
        assert web.routes[0].call_count == 1


def test_robots_failure_is_remembered_for_the_run() -> None:
    with mocked_web() as web, make_http() as http:
        robots = web.get("https://example.com/robots.txt").respond(503)
        for _ in range(2):
            with pytest.raises(RobotsUnavailableError):
                http.get("https://example.com/events")
        assert robots.call_count == 1


def test_redirect_target_on_another_host_checks_that_hosts_robots() -> None:
    with mocked_web("example.com") as web, make_http() as http:
        _robots(web, "other.example.org", "User-agent: *\nDisallow: /\n")
        web.get("https://example.com/").respond(
            302, headers={"location": "https://other.example.org/x"}
        )
        target = web.get("https://other.example.org/x").respond(200, headers=HTML)
        with pytest.raises(RobotsDisallowedError):
            http.get("https://example.com/")
        assert not target.called


# --- Per-host delay


def test_default_delay_between_requests_to_the_same_host_is_5s() -> None:
    clock = FakeClock()
    with mocked_web("example.com") as web, make_http(clock=clock) as http:
        web.get("https://example.com/a").respond(200, headers=HTML)
        web.get("https://example.com/b").respond(200, headers=HTML)
        http.get("https://example.com/a")
        http.get("https://example.com/b")
    # robots.txt, then /a after 5 s, then /b after another 5 s.
    assert clock.sleeps == [5.0, 5.0]


def test_source_rate_limit_override_is_honored() -> None:
    clock = FakeClock()
    with mocked_web("example.com") as web, make_http(clock=clock) as http:
        web.get("https://example.com/a").respond(200, headers=HTML)
        web.get("https://example.com/b").respond(200, headers=HTML)
        http.get("https://example.com/a", delay_seconds=12)
        http.get("https://example.com/b", delay_seconds=12)
    assert clock.sleeps == [12.0, 12.0]


def test_robots_crawl_delay_raises_the_delay() -> None:
    clock = FakeClock()
    with mocked_web() as web, make_http(clock=clock) as http:
        _robots(web, "example.com", "User-agent: *\nCrawl-delay: 20\n")
        web.get("https://example.com/a").respond(200, headers=HTML)
        http.get("https://example.com/a")
    assert clock.sleeps == [20.0]


def test_time_already_elapsed_counts_toward_the_delay() -> None:
    clock = FakeClock()
    with mocked_web("example.com") as web, make_http(clock=clock) as http:
        web.get("https://example.com/a").respond(200, headers=HTML)
        web.get("https://example.com/b").respond(200, headers=HTML)
        http.get("https://example.com/a")
        clock.advance(3.0)
        http.get("https://example.com/b")
    assert clock.sleeps == [5.0, 2.0]


def test_different_hosts_do_not_wait_for_each_other() -> None:
    clock = FakeClock()
    with mocked_web("a.example.com", "b.example.com") as web, make_http(clock=clock) as http:
        web.get("https://a.example.com/").respond(200, headers=HTML)
        web.get("https://b.example.com/").respond(200, headers=HTML)
        http.get("https://a.example.com/")
        http.get("https://b.example.com/")
    # Only the wait after each host's own robots.txt fetch.
    assert clock.sleeps == [5.0, 5.0]


# --- Per-host budget


def test_per_host_budget_is_enforced() -> None:
    with (
        mocked_web("example.com", "other.example.com") as web,
        make_http(budget_per_host=3) as http,
    ):
        web.get(url__regex=r"https://example\.com/p\d").respond(200, headers=HTML)
        web.get("https://other.example.com/").respond(200, headers=HTML)
        for i in range(3):  # robots.txt does not count against the budget
            http.get(f"https://example.com/p{i}")
        with pytest.raises(BudgetExceededError):
            http.get("https://example.com/p9")
        assert http.get("https://other.example.com/").status == 200


def test_redirect_hops_count_against_the_budget() -> None:
    with mocked_web("example.com") as web, make_http(budget_per_host=2) as http:
        web.get("https://example.com/a").respond(302, headers={"location": "/b"})
        web.get("https://example.com/b").respond(302, headers={"location": "/c"})
        web.get("https://example.com/c").respond(200, headers=HTML)
        with pytest.raises(BudgetExceededError):
            http.get("https://example.com/a")
