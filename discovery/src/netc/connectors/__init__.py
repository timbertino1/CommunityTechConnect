"""netc.connectors: read event sources into RawListings."""

from collections.abc import Callable
from datetime import datetime

from netc.connectors.base import Connector, ParseResult, RawPayload
from netc.connectors.ical import IcalConnector
from netc.connectors.jsonld import JsonLdConnector


def default_connectors(clock: Callable[[], datetime] | None = None) -> dict[str, Connector]:
    """The connectors available to the runner, keyed by Source.connector. ``clock`` sets the
    time the date window is measured from (tests and ``--now``)."""
    if clock is None:
        return {IcalConnector.kind: IcalConnector(), JsonLdConnector.kind: JsonLdConnector()}
    return {IcalConnector.kind: IcalConnector(clock), JsonLdConnector.kind: JsonLdConnector(clock)}


__all__ = [
    "Connector",
    "IcalConnector",
    "JsonLdConnector",
    "ParseResult",
    "RawPayload",
    "default_connectors",
]
