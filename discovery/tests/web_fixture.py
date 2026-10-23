"""The data the browser filter tests build their site from (T111):
`uv run python -m tests.web_fixture DIR`.

Six public events, one per filter case: each area, single and multiple topics, a two-day
event, a match only in the summary, and one whose organizer comes from its source's name
("Heartland Rustaceans", a word found nowhere else).
The real categories.yaml and areas.yaml are copied in, so the fixture never drifts from them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from netc.models import Event
from netc.storage import DataStore
from tests.data_samples import make_source, utc
from tests.site_support import make_data, site_event


def at(city: str | None, area: str, **kw: Any) -> dict[str, Any]:
    online = area == "online"
    location = {"venue": None, "city": city, "state": None if online else "NE", "online": online}
    return {"location": location, "area": area, **kw}


def events() -> list[Event]:
    return [
        site_event("https://lincolnsec.example.org/nov", "Lincoln Security Meetup",
                   utc(2026, 11, 5, 0), "lincoln-security-meetup-2026-11-04",
                   categories=["security"], summary="Talks about threat modeling.",
                   **at("Lincoln", "lincoln")),
        site_event("https://omahaai.example.org/nov", "Omaha AI Night",
                   utc(2026, 11, 11, 0), "omaha-ai-night-2026-11-10",
                   categories=["ai-ml"], summary="Large language models in practice.",
                   **at("Omaha", "omaha")),
        site_event("https://omahacloud.example.org/nov", "Omaha Cloud Day",
                   utc(2026, 11, 18, 15), "omaha-cloud-day-2026-11-18",
                   categories=["cloud-devops"], summary="Kubernetes and serverless.",
                   **at("Omaha", "omaha")),
        site_event("https://rust.example.org/nov", "Remote Rust Hour",
                   utc(2026, 11, 13, 0), "remote-rust-hour-2026-11-12",
                   categories=["software-dev"], summary="Ownership, borrowing and pizza.",
                   organizer_id=None, **at(None, "online")),
        site_event("https://lincolnsummit.example.org/2026", "Lincoln AI & Security Summit",
                   utc(2026, 11, 20, 14), "lincoln-ai-security-summit-2026-11-20",
                   end=utc(2026, 11, 21, 23), categories=["ai-ml", "security"],
                   summary="Two days of talks.", **at("Lincoln", "lincoln")),
        site_event("https://kearneydata.example.org/dec", "Kearney Data Workshop",
                   utc(2026, 12, 2, 18), "kearney-data-workshop-2026-12-02",
                   categories=["data-analytics"], summary="Dashboards for small towns.",
                   **at("Kearney", "other_ne")),
    ]  # fmt: skip


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m tests.web_fixture DIR", file=sys.stderr)
        return 2
    root = make_data(Path(argv[1]), events())
    DataStore(root).write_source(make_source(name="Heartland Rustaceans"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
