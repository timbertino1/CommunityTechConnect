"""Admin overrides (T126; FR-019, FR-045; data-model.md "Override").

``data/overrides.yaml`` holds corrections the owner makes by pull request: hide or unhide an
event, or fix its categories or area. They are applied at the end of every run that writes
events (so the next run's fresh details don't undo them) and again when the site is built
(so a merged override shows up at the next deploy without waiting for a run).

Only overrides hide events, so an event with no override is shown: removing a "hidden" entry
brings the event back. An override can't change ``original_url``, ``review_state`` or a
source's trust (the model has no such fields), so it can never publish an event that is
waiting for review. Overrides for unknown events are skipped here; ``validate-data`` reports
them.
"""

from __future__ import annotations

from collections.abc import Iterable

from netc.models import Event, Override


def apply_overrides(events: Iterable[Event], overrides: Iterable[Override]) -> list[Event]:
    """Every event with its override applied, in the same order."""
    by_event = {o.event_id: o for o in overrides}
    return [_apply(event, by_event.get(event.id)) for event in events]


def _apply(event: Event, override: Override | None) -> Event:
    update: dict[str, object] = {}
    visibility = override.visibility if override and override.visibility else "shown"
    if event.visibility != visibility:
        update["visibility"] = visibility
    if override is not None:
        settled: set[str] = set()
        if override.categories is not None:
            update["categories"] = list(override.categories)
            settled.add("categories")
        if override.area is not None:
            update["area"] = override.area
            settled.add("area")
        if settled & set(event.inferred):
            update["inferred"] = [f for f in event.inferred if f not in settled]
    return event.model_copy(update=update) if update else event
