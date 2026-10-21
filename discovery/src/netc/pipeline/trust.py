"""Source trust (T092; FR-016-FR-018).

Sources set up before launch or by the owner start trusted; discovered and visitor-suggested
ones start probationary, and their events wait for review. Review outcomes move a probationary
source: 3 approved events and none rejected make it trusted; once at least 3 have been reviewed
and most were rejected, it is paused. A trusted source is only ever demoted by the owner
(FR-019), so review counts never change it.
"""

from __future__ import annotations

from typing import Final, Literal

from netc.models import Source

PROMOTE_AFTER_APPROVALS: Final = 3
MIN_REVIEWED_TO_PAUSE: Final = 3
"""A source isn't paused for its first rejection or two (T092)."""

Origin = Literal["preconfigured", "admin", "discovered", "suggested"]
Trust = Literal["trusted", "probationary"]


def initial_trust(origin: Origin) -> Trust:
    return "trusted" if origin in ("preconfigured", "admin") else "probationary"


def apply_trust_rules(source: Source) -> Source:
    if source.trust != "probationary":
        return source
    reviewed = source.approved_count + source.rejected_count
    if reviewed >= MIN_REVIEWED_TO_PAUSE and source.rejected_count > source.approved_count:
        if source.status == "active":
            return source.model_copy(update={"status": "paused"})
        return source
    if source.approved_count >= PROMOTE_AFTER_APPROVALS and source.rejected_count == 0:
        return source.model_copy(update={"trust": "trusted"})
    return source
