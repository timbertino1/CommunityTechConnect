"""Rules-first relevance classification (T050; FR-003, FR-028, research R10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from netc.models import AreaConfig, Category
from netc.pipeline.classify import ClassifyInput, classify
from netc.storage import DataStore

pytestmark = pytest.mark.unit

STORE = DataStore(Path(__file__).resolve().parents[3] / "data")
CATEGORIES: list[Category] = STORE.read_categories()
AREAS: AreaConfig = STORE.read_areas()  # type: ignore[assignment]
CATEGORY_IDS = {c.id for c in CATEGORIES}


def item(
    title: str,
    summary: str = "",
    organizer: str | None = None,
    area: str | None = "omaha",
    online: bool = False,
    source_area: str | None = None,
) -> ClassifyInput:
    return ClassifyInput(
        title=title,
        summary=summary,
        organizer=organizer,
        area=area,  # type: ignore[arg-type]
        online=online,
        source_area=source_area,  # type: ignore[arg-type]
    )


def run(i: ClassifyInput):  # type: ignore[no-untyped-def]
    return classify(i, CATEGORIES, AREAS)


# --- Clear tech events are accepted


@pytest.mark.parametrize(
    ("title", "summary", "expected"),
    [
        ("Prairie Python Meetup", "Talks about packaging.", "software-dev"),
        ("OWASP Omaha: threat modeling night", "", "security"),
        ("Kubernetes and Terraform in practice", "", "cloud-devops"),
        ("Intro to RAG workshop", "Build a large language model app.", "ai-ml"),
        ("Power BI dashboards", "", "data-analytics"),
        (
            "(NE)NUG Omaha Fall Event 2026",
            "Lightning talks and a panel on emerging networking ideas.",
            "networking-infra",
        ),
        ("Drupal Nebraska quarterly meeting", "", "web-mobile"),
        (
            "Omaha tech career fair",
            "Meet engineers and learn about internships.",
            "career-networking",
        ),
        ("Raspberry Pi build night", "", "hardware-iot-makers"),
    ],
)
def test_clear_tech_events_are_relevant_with_categories(
    title: str, summary: str, expected: str
) -> None:
    result = run(item(title, summary))
    assert result.relevant is True
    assert result.decided_by == "rules"
    assert expected in result.categories
    assert set(result.categories) <= CATEGORY_IDS
    assert 1 <= len(result.categories) <= 3
    assert 0 < result.confidence <= 1


def test_keywords_match_whole_words_and_plurals_only() -> None:
    assert run(item("Hackathon weekend")).relevant is True
    assert run(item("Hackathons for students")).relevant is True
    # "ai" must not match inside other words; "rust" must not match "trust".
    assert run(item("Fair trust and maintenance")).decided_by == "none"


def test_keywords_with_symbols_match() -> None:
    assert "software-dev" in run(item("Building APIs in C# and .NET")).categories
    assert "cloud-devops" in run(item("CI/CD pipelines that don't hurt")).categories


def test_title_matches_outweigh_description_matches() -> None:
    result = run(
        item("Python for data science", "Bring a laptop; we will also discuss cloud costs.")
    )
    assert result.categories[0] in {"software-dev", "data-analytics"}


# --- Non-tech and sales pitches are rejected


@pytest.mark.parametrize(
    ("title", "summary"),
    [
        ("Real estate investing night", "Learn about cloud-based property tools."),
        ("Product webinar demo: our AI platform", ""),
        ("Book a demo of our security suite", ""),
        ("Mortgage rates and you", ""),
        ("Fall Semester Break (Student Holiday - UNL offices open)", ""),
        ("Priority Registration for Spring Semester 2027", ""),
        ("Last day to drop a class", ""),
        ("Commencement ceremony", ""),
        ("Happy Hour at Barred Owl", "Meet other makers and innovators."),
        ("Nebraska REALTORS Association Leadership Training", ""),
        ("Massage Monday", ""),
        ("Last day of Regular Session classes", ""),
        ("Fall 2026 Semester Final Exams", ""),
        # Student-only events (live UNL School of Computing feed, 2026-10-19)
        ("Industry in Residence: Nelnet", "Stop by to learn about career opportunities!"),
        ("COE Graduate Programs: Virtual Information Session", "Learn about an advanced degree."),
        ("Graduate Information Day", "Learn about graduate programs in computer science."),
        ("Spring Nvolvement Fair", "Explore Recognized Student Organizations."),
        ("Food for Thought", "The School of Computing Student Advisory Board is hosting."),
        ("Run with the School of Computing", "A monthly 5k run around campus."),
        ("School of Computing Showcase", "Students will tour research labs in robotics and AI."),
        ("Python workshop (students only)", ""),
    ],
)
def test_non_tech_and_sales_events_are_rejected(title: str, summary: str) -> None:
    result = run(item(title, summary))
    assert result.relevant is False
    assert result.decided_by == "rules"
    assert result.categories == []


# --- Nebraska connection (FR-003)


def test_events_placed_in_nebraska_are_nebraska() -> None:
    for area in ("omaha", "lincoln", "other_ne"):
        assert run(item("Python meetup", area=area)).nebraska is True


def test_online_event_from_a_nebraska_group_counts() -> None:
    result = run(item("Python meetup", area="online", online=True, source_area="omaha"))
    assert result.nebraska is True
    assert result.relevant is True


def test_online_event_with_no_nebraska_link_is_undecided() -> None:
    result = run(item("Python meetup", area="online", online=True, source_area=None))
    assert result.nebraska is None
    assert result.decided_by == "none"


def test_unknown_place_is_resolved_from_the_text() -> None:
    result = run(item("Lincoln Python meetup", area=None))
    assert result.nebraska is True
    assert result.area == "lincoln"


def test_unknown_place_with_no_clue_is_undecided() -> None:
    result = run(item("Python meetup", area=None))
    assert result.nebraska is None
    assert result.decided_by == "none"


def test_tech_event_explicitly_elsewhere_is_rejected() -> None:
    result = run(item("Python meetup in Denver, Colorado", area=None))
    assert result.relevant is False
    assert result.nebraska is False
    assert result.decided_by == "rules"


# --- Undecided


def test_no_tech_signal_is_undecided() -> None:
    result = run(item("Monthly gathering", "Join us for conversation."))
    assert result.relevant is None
    assert result.decided_by == "none"
    assert result.categories == []
    assert result.confidence == 0.0


def test_general_tech_terms_give_general_tech() -> None:
    assert run(item("Tech talk: what's new this year")).categories == ["general-tech"]


def test_organizer_name_counts_as_a_signal() -> None:
    result = run(item("Monthly meeting", organizer="Omaha Azure User Group"))
    assert result.relevant is True
    assert "cloud-devops" in result.categories
