"""Newsletter links and privacy (T098; research R8).

Everything kept from a newsletter ends up public, so only clean links to public event or group
pages survive: no query strings or fragments, and no unsubscribe, preference, "view in browser"
or tracking/redirect links that could be used to manage the inbox's subscriptions. Nothing from
an email but its hash (the KV key) is ever written to data/.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from netc.connectors import default_connectors
from netc.fetch import FixtureHttp
from netc.finders.newsletter import NewsletterFinder, clean_link, read_newsletter
from netc.pipeline.discover_sources import discover_sources
from netc.storage import DataStore
from tests.ai_support import EMAILS, NOW, ScriptedClient, ai

pytestmark = pytest.mark.security

REPO_DATA = Path(__file__).resolve().parents[3] / "data"
TRACKING = (EMAILS / "newsletter_tracking.eml").read_bytes()
KEPT = [
    "https://omahadata.example.org/events/streaming-night",
    "https://heartlandrust.example.org/events/rust-night-nov",
]


def test_only_clean_public_event_links_are_kept() -> None:
    assert read_newsletter(TRACKING).links == KEPT


def test_the_plain_text_part_follows_the_same_rules() -> None:
    head = TRACKING.split(b"Content-Type: text/html")[0].rstrip()
    plain_only = head.removesuffix(b"--b1_prairie") + b"--b1_prairie--\n"
    assert read_newsletter(plain_only).links == KEPT[:1]


@pytest.mark.parametrize(
    ("url", "label"),
    [
        ("https://news.example.com/u/7f3a9c?list=prairie", ""),  # in List-Unsubscribe
        ("https://news.example.com/unsubscribe/4821", ""),
        ("https://news.example.com/preferences?sub=1", ""),
        ("https://news.example.com/manage-subscription", ""),
        ("https://news.example.com/email/opt-out", ""),
        ("https://news.example.com/archive/2026-10-26", "View in browser"),
        ("https://news.example.com/archive/2026-10-26", "View this email online"),
        ("https://news.example.com/web-version/77", ""),
        ("https://click.news.example.com/ls/click?upn=abc", "Cyber Night"),
        ("https://links.example.com/a/b", ""),
        ("https://prairie.us21.list-manage.com/track/click?u=1", "Register"),
        ("https://u123.ct.sendgrid.net/ls/click?upn=x", ""),
        ("https://mandrillapp.com/track/click/1/x", ""),
        ("https://news.example.com/redirect?to=https%3A%2F%2Fa.example.org", ""),
        ("https://mailchi.mp/abc/prairie-weekly", ""),
        ("https://example.substack.com/redirect/2/abc", ""),
        ("http://plain.example.org/events", ""),
        ("https://10.0.0.1/events", ""),
        ("mailto:unsub@news.example.com", ""),
    ],
)
def test_management_tracking_and_unsafe_links_are_dropped(url: str, label: str) -> None:
    unsubscribe = frozenset({"https://news.example.com/u/7f3a9c"})
    assert clean_link(url, label=label, unsubscribe=unsubscribe) is None


def test_query_strings_and_fragments_are_removed() -> None:
    url = "https://omahadata.example.org/events/streaming-night?utm_source=x&id=7#rsvp"
    assert clean_link(url) == "https://omahadata.example.org/events/streaming-night"


def test_the_text_keeps_the_events_and_loses_the_rest() -> None:
    text = read_newsletter(TRACKING).text
    assert "Streaming Night" in text and "Rust Night" in text
    assert KEPT[0] in text  # kept links stay next to their event, for the AI
    for gone in ("reader-4821", "utm_", "alert(", "color: #333", "click.news", "list-manage"):
        assert gone not in text


def test_only_the_hash_of_an_email_is_ever_written(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    for name in ("categories.yaml", "areas.yaml"):
        shutil.copy(REPO_DATA / name, root / name)
    key = hashlib.sha256(TRACKING).hexdigest()
    box = MemoryInbox({key: TRACKING})
    client = ScriptedClient(
        {
            "mentions": [
                {
                    "title": "Streaming Night",
                    "date_hint": "Nov 10",
                    "place_hint": None,
                    "organizer_hint": "Omaha Data Engineers",
                    "links": [
                        KEPT[0] + "?utm_source=newsletter",
                        "https://news.example.com/u/7f3a9c",
                    ],
                }
            ]
        }
    )
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "index.json").write_text("{}", encoding="utf-8")
    report = discover_sources(
        DataStore(root),
        FixtureHttp(tmp_path / "pages"),
        default_connectors(lambda: NOW),
        now=NOW,
        ai=ai(root, client),
        finders=[NewsletterFinder(box)],
        inbox=box,
    )
    assert report.finders["newsletter"]["processed"] == 1
    [mention] = DataStore(root).read_mentions()
    assert mention.channel == "newsletter" and mention.links == [KEPT[0]]

    written = "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in root.rglob("*") if p.is_file()
    )
    for secret in (
        "reader-4821",
        "weekly@news.example.com",
        "Prairie Tech Weekly",
        "402-555-0142",
        "Thanks for reading",
        "news.example.com/u/",
        "utm_",
    ):
        assert secret not in written, secret


class MemoryInbox:
    def __init__(self, items: dict[str, bytes]) -> None:
        self.items = dict(items)
        self.deleted: list[str] = []

    def keys(self) -> list[str]:
        return list(self.items)

    def read(self, key: str) -> bytes | None:
        return self.items.get(key)

    def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.items.pop(key, None)
