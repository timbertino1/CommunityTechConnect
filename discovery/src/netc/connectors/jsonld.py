"""JSON-LD / microdata connector (T057; research R5).

Reads schema.org ``Event`` data built into web pages: JSON-LD blocks (including ``@graph``,
arrays, item lists, and ``@id`` references) and microdata (``itemscope`` with an Event
``itemtype``). With ``follow_links``, it also reads same-site pages linked from the source page
whose path matches a glob (e.g. Meetup event pages, or ``/live/nenug-*`` on usnua.com).

Text is passed through with length caps only; cleaning happens in normalize. Organizers that are
people (schema.org ``Person``) are not kept. Broken blocks are skipped with a warning.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import json
import re
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, time
from typing import Any, ClassVar, Final
from urllib.parse import urlsplit, urlunsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from netc.connectors import cost as costs
from netc.connectors.base import WINDOW_AHEAD, WINDOW_BEHIND, ParseResult, RawPayload
from netc.fetch import FetchError, HttpClient
from netc.fetch.urls import join_url
from netc.models import Cost, FollowLinks, RawListing, Source

MAX_TITLE_CHARS: Final = 2_000
MAX_DESCRIPTION_CHARS: Final = 20_000
MAX_SHORT_CHARS: Final = 2_000
MAX_DEPTH: Final = 12
MAX_NODES: Final = 5_000
MAX_WARNINGS: Final = 50

_DATE_ONLY: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JsonLdConnector:
    kind: ClassVar[str] = "jsonld"

    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock

    def fetch(self, source: Source, http: HttpClient) -> RawPayload:
        fetched_at = self._clock()
        response = http.get(source.url, kind="page", delay_seconds=source.rate_limit_seconds)
        if response.status >= 400:
            raise FetchError(f"{source.url} returned HTTP {response.status}")
        main = RawPayload.from_response(response, fetched_at)
        if source.follow_links is None:
            return main

        linked: list[RawPayload] = []
        warnings: list[str] = []
        for url in _matching_links(response.url, response.text, source.follow_links):
            try:
                page = http.get(url, kind="page", delay_seconds=source.rate_limit_seconds)
            except FetchError as exc:
                warnings.append(f"linked page {url} could not be read: {type(exc).__name__}")
                continue
            if page.status >= 400:
                warnings.append(f"linked page {url} returned HTTP {page.status}")
                continue
            linked.append(RawPayload.from_response(page, fetched_at))
        return dataclasses.replace(main, linked=tuple(linked), warnings=tuple(warnings))

    def parse(self, source: Source, payload: RawPayload) -> ParseResult:
        warnings = list(payload.warnings)
        listings: list[RawListing] = []
        seen: set[tuple[str | None, str]] = set()
        past: set[tuple[str | None, str]] = set()
        latest_past: datetime | None = None
        earliest = payload.fetched_at - WINDOW_BEHIND
        latest = payload.fetched_at + WINDOW_AHEAD
        for document in (payload, *payload.linked):
            for listing in _page_listings(document, warnings):
                key = (listing.external_id or listing.url, listing.start.isoformat())
                if not _in_window(listing, earliest, latest):
                    start = _aware(listing.start)
                    if start < earliest and key not in past:
                        past.add(key)
                        latest_past = start if latest_past is None else max(latest_past, start)
                    continue
                if key not in seen:
                    seen.add(key)
                    listings.append(listing)
        return ParseResult(listings, warnings[:MAX_WARNINGS], len(past), latest_past)


# ---------------------------------------------------------------- following links


# Absolute URLs written in page text, e.g. in a script's embedded JSON (Meetup renders its event
# links with JavaScript, so they appear only there).
_TEXT_URL: Final = re.compile(r"https://[A-Za-z0-9.-]+/[^\s\"'<>\\]*")


def _matching_links(page_url: str, html: str, rule: FollowLinks) -> list[str]:
    """Same-site https links whose path matches the glob, in page order: ``<a href>`` links
    first, then absolute URLs written in the page text. Query and fragment are dropped."""
    base = urlsplit(page_url)
    found: list[str] = []
    try:
        hrefs = [a.attributes.get("href") or "" for a in LexborHTMLParser(html).css("a[href]")]
    except Exception:
        hrefs = []
    for href in [*hrefs, *_TEXT_URL.findall(html)]:
        parts = urlsplit(join_url(page_url, href))
        if parts.scheme != "https" or (parts.hostname or "") != (base.hostname or ""):
            continue
        if not fnmatch.fnmatchcase(parts.path, rule.path_glob):
            continue
        url = urlunsplit(("https", parts.netloc, parts.path, "", ""))
        if url not in found:
            found.append(url)
        if len(found) >= rule.max_pages:
            break
    return found


# ---------------------------------------------------------------- page parsing


def page_listings(document: RawPayload) -> list[RawListing]:
    """Every event on one page, in or out of the date window (used by feed detection)."""
    return list(_page_listings(document, []))


def _page_listings(document: RawPayload, warnings: list[str]) -> Iterator[RawListing]:
    if not document.text.strip():
        return
    try:
        tree = LexborHTMLParser(document.text)
    except Exception:
        warnings.append(f"{document.url}: page could not be parsed")
        return

    for script in tree.css("script"):
        if (script.attributes.get("type") or "").strip().lower() != "application/ld+json":
            continue
        raw = script.text()
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except Exception:
            warnings.append(f"{document.url}: skipped a JSON-LD block that is not valid JSON")
            continue
        nodes = _nodes(data)
        # Map ids to full objects only; a bare {"@id": ...} is a reference, not the object.
        index = {n["@id"]: n for n in nodes if isinstance(n.get("@id"), str) and len(n) > 1}
        for node in nodes:
            if _is_event(node.get("@type")):
                listing = _listing(node, index, document.url, warnings)
                if listing is not None:
                    yield listing

    for element in tree.css("[itemscope][itemtype]"):
        if _is_event(element.attributes.get("itemtype")):
            node = _microdata(element, document.url, depth=0)
            listing = _listing(node, {}, document.url, warnings)
            if listing is not None:
                yield listing


def _in_window(listing: RawListing, earliest: datetime, latest: datetime) -> bool:
    """Same window as the iCal connector. Naive times are compared as if UTC (a few hours'
    difference at the edges does not matter)."""
    finish = _aware(listing.end or listing.start)
    return finish >= earliest and _aware(listing.start) <= latest


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _nodes(data: Any) -> list[dict[str, Any]]:
    """Every object in a JSON-LD document, bounded in depth and count."""
    out: list[dict[str, Any]] = []
    stack: list[tuple[Any, int]] = [(data, 0)]
    while stack and len(out) < MAX_NODES:
        value, depth = stack.pop()
        if depth > MAX_DEPTH:
            continue
        if isinstance(value, dict):
            out.append(value)
            stack.extend(
                (v, depth + 1)
                for v in reversed(list(value.values()))
                if isinstance(v, (dict, list))
            )
        elif isinstance(value, list):
            stack.extend((v, depth + 1) for v in reversed(value) if isinstance(v, (dict, list)))
    return out


def _is_event(kind: Any) -> bool:
    kinds = kind if isinstance(kind, list) else [kind]
    for item in kinds:
        if isinstance(item, str):
            for word in item.split():
                if word.rstrip("/").rsplit("/", 1)[-1].endswith("Event"):
                    return True
    return False


def _listing(
    node: dict[str, Any], index: dict[str, dict[str, Any]], page_url: str, warnings: list[str]
) -> RawListing | None:
    name = node.get("name")
    if not isinstance(name, str) or not name.strip():
        warnings.append(f"{page_url}: skipped an event without a usable name")
        return None
    title = name.strip()[:MAX_TITLE_CHARS]

    start = _when(node.get("startDate"))
    if start is None:
        warnings.append(f"{page_url}: skipped {title[:80]!r}: missing or invalid startDate")
        return None
    start_dt, all_day = start
    end = _when(node.get("endDate"))

    raw_url = node.get("url")
    url = (
        join_url(page_url, raw_url.strip())
        if isinstance(raw_url, str) and raw_url.strip()
        else page_url
    )
    raw_id = node.get("@id")
    external_id = raw_id[:MAX_SHORT_CHARS] if isinstance(raw_id, str) else url

    status = _last_segment(node.get("eventStatus"))
    cancelled = status in {"EventCancelled", "EventPostponed"}
    if status == "EventPostponed":
        warnings.append(
            f"{page_url}: {title[:80]!r} is postponed with no new date; treated as cancelled"
        )
    locations = _as_list(_resolve(node.get("location"), index))
    places = [
        loc
        for loc in locations
        if isinstance(loc, dict) and _last_segment(loc.get("@type")) != "VirtualLocation"
    ]
    mode = _last_segment(node.get("eventAttendanceMode"))
    if mode == "OnlineEventAttendanceMode" or status == "EventMovedOnline":
        online = True
    elif mode in {"OfflineEventAttendanceMode", "MixedEventAttendanceMode"}:
        online = False
    else:
        online = bool(locations) and not places

    description = node.get("description")
    cost, price = _cost(node, index)
    return RawListing(
        external_id=external_id,
        url=url[:MAX_SHORT_CHARS],
        title=title,
        start=start_dt,
        end=end[0] if end is not None else None,
        tz=None,
        all_day=all_day,
        location_text=_place_text(places, index),
        online=online,
        organizer_text=_organizer(node.get("organizer"), index),
        description_text=description.strip()[:MAX_DESCRIPTION_CHARS] or None
        if isinstance(description, str)
        else None,
        cancelled=cancelled,
        cost=cost,
        price=price,
        country=_country(places, index),
    )


def _country(places: list[Any], index: dict[str, dict[str, Any]]) -> str | None:
    """``addressCountry`` of the first place that gives one: a code ("gb") or a Country's name."""
    for place in places:
        address = _resolve(place.get("address"), index)
        if not isinstance(address, dict):
            continue
        country = _resolve(address.get("addressCountry"), index)
        if isinstance(country, dict):
            country = country.get("name")
        if isinstance(country, str) and country.strip():
            return country.strip()[:100]
    return None


def _cost(node: dict[str, Any], index: dict[str, dict[str, Any]]) -> tuple[Cost | None, str | None]:
    """``isAccessibleForFree``, then the amounts in ``offers`` (``price``, or an
    AggregateOffer's ``lowPrice``/``highPrice``)."""
    flag = node.get("isAccessibleForFree")
    if isinstance(flag, str):
        flag = {"true": True, "false": False}.get(flag.strip().lower())
    if flag is True:
        return "free", None
    amounts = []
    dollars = True
    for offer in _as_list(_resolve(node.get("offers"), index)):
        if not isinstance(offer, dict):
            continue
        found = [
            a
            for key in ("price", "lowPrice", "highPrice")
            if (a := costs.amount(offer.get(key))) is not None
        ]
        currency = offer.get("priceCurrency")
        if found and isinstance(currency, str) and currency.strip().upper() != "USD":
            dollars = False
        amounts.extend(found)
    stated = costs.from_amounts(amounts, dollars=dollars)
    if stated is not None:
        return stated
    return ("paid", None) if flag is False else (None, None)


def _when(value: Any) -> tuple[datetime, bool] | None:
    """(start, all_day) from an ISO 8601 date or date-time string."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if _DATE_ONLY.match(text):
            return datetime.combine(date.fromisoformat(text), time()), True
        return datetime.fromisoformat(text.replace("Z", "+00:00")), False
    except ValueError:
        return None


def _last_segment(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return value.rstrip("/").rsplit("/", 1)[-1] if isinstance(value, str) else ""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _resolve(value: Any, index: dict[str, dict[str, Any]]) -> Any:
    """Replace ``{"@id": ...}`` references with the referenced object where known."""
    if isinstance(value, list):
        return [_resolve(v, index) for v in value[:20]]
    if isinstance(value, dict) and set(value) == {"@id"} and isinstance(value["@id"], str):
        return index.get(value["@id"], value)
    return value


def _place_text(places: list[Any], index: dict[str, dict[str, Any]]) -> str | None:
    for place in places:
        address = _resolve(place.get("address"), index)
        parts = [_str(place.get("name"))]
        if isinstance(address, dict):
            region = " ".join(
                p
                for p in (_str(address.get("addressRegion")), _str(address.get("postalCode")))
                if p
            )
            parts += [
                _str(address.get("streetAddress")),
                _str(address.get("addressLocality")),
                region,
            ]
        else:
            parts.append(_str(address))
        # Skip parts already written earlier (Meetup repeats "Omaha, NE" inside streetAddress).
        # Compare whole comma-separated pieces, so "NE" is not mistaken for part of "Nelnet".
        kept: list[str] = []
        seen: set[str] = set()
        for part in parts:
            pieces = [p.strip().casefold() for p in part.split(",") if p.strip()]
            if pieces and not all(p in seen for p in pieces):
                kept.append(part)
                seen.update(pieces)
        text = ", ".join(kept)
        if text:
            return text[:MAX_SHORT_CHARS]
    return None


def _organizer(value: Any, index: dict[str, dict[str, Any]]) -> str | None:
    for item in _as_list(_resolve(value, index)):
        if isinstance(item, str):
            return item.strip()[:MAX_SHORT_CHARS] or None
        if isinstance(item, dict) and _last_segment(item.get("@type")) != "Person":
            name = _str(item.get("name"))
            if name:
                return name[:MAX_SHORT_CHARS]
    return None


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


# ---------------------------------------------------------------- microdata


def _microdata(element: LexborNode, page_url: str, depth: int) -> dict[str, Any]:
    """The properties of one microdata item, as a JSON-LD-like dict."""
    itemtype = element.attributes.get("itemtype") or ""
    props: dict[str, Any] = {"@type": itemtype.rstrip("/").rsplit("/", 1)[-1]}
    if depth > 4:
        return props
    own_id = element.mem_id
    for prop in element.css("[itemprop]"):
        owner = prop.parent
        while owner is not None and "itemscope" not in owner.attributes:
            owner = owner.parent
        if owner is None or owner.mem_id != own_id:
            continue
        if "itemscope" in prop.attributes:
            value: Any = _microdata(prop, page_url, depth + 1)
        else:
            value = _microdata_value(prop, page_url)
        for name in (prop.attributes.get("itemprop") or "").split():
            props.setdefault(name, value)
    return props


def _microdata_value(element: LexborNode, page_url: str) -> str:
    tag = (element.tag or "").lower()
    attrs = element.attributes
    if tag == "meta":
        return (attrs.get("content") or "").strip()
    if tag in {"a", "link", "area"}:
        return join_url(page_url, (attrs.get("href") or "").strip())
    if tag in {"img", "audio", "video", "source", "iframe", "embed"}:
        return join_url(page_url, (attrs.get("src") or "").strip())
    if tag == "time" and attrs.get("datetime"):
        return (attrs.get("datetime") or "").strip()
    if tag in {"data", "meter"}:
        return (attrs.get("value") or "").strip()
    return " ".join((element.text(separator=" ") or "").split())
