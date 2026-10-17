"""netc.connectors: read event sources into RawListings."""

from netc.connectors.base import Connector, ParseResult, RawPayload
from netc.connectors.ical import IcalConnector
from netc.connectors.jsonld import JsonLdConnector


def default_connectors() -> dict[str, Connector]:
    """The connectors available to the runner, keyed by Source.connector."""
    return {IcalConnector.kind: IcalConnector(), JsonLdConnector.kind: JsonLdConnector()}


__all__ = [
    "Connector",
    "IcalConnector",
    "JsonLdConnector",
    "ParseResult",
    "RawPayload",
    "default_connectors",
]
