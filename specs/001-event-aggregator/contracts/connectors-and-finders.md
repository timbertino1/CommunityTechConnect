# Contract: Connectors, Finders, and the Classifier

Internal Python interfaces in `discovery/src/netc/`. They are contracts because each connector
and finder is an isolated, independently tested unit (Constitution V, VI).

## Connector

```python
class Connector(Protocol):
    kind: ClassVar[str]                     # "ical" | "rss" | "jsonld" | "eventbrite_org" | "html_rules"

    def fetch(self, source: Source, http: SafeHttp) -> RawPayload: ...
    def parse(self, source: Source, payload: RawPayload) -> list[RawListing]: ...
```

- `fetch` MUST use only the provided `SafeHttp` (SSRF protection, robots.txt, rate limits,
  size and time limits — research R12). Direct use of `httpx` elsewhere fails a lint rule.
- `parse` is pure (no I/O) and MUST tolerate malformed input by returning the listings it could
  parse plus recorded warnings; it MUST NOT raise for bad data.
- `RawListing` fields: `external_id, url, title, start, end, tz, all_day, location_text,
  online, organizer_text, description_text, cancelled`. All text is untrusted.
- A connector failure is caught by the runner, recorded in `state/source_status.json`, and
  never affects other sources (FR-008).

## Feed detector

```python
def detect(url: str, http: SafeHttp) -> Detection   # connector kind + feed_url, or "none"
```

Priority: iCal → JSON-LD/microdata `Event` → RSS/Atom (research R5).

## Finder

```python
class Finder(Protocol):
    name: ClassVar[str]                     # "web_search" | "link_graph" | "newsletter" | "news" | "platform" | "gap"

    def run(self, ctx: FinderContext) -> FinderResult: ...
```

`FinderResult` = `candidates: list[CandidateSource]`, `mentions: list[EventMention]`,
`stats: dict`. Finders never create sources or events directly; the evaluator does.

## Search provider

```python
class SearchProvider(Protocol):
    def search(self, query: str, *, count: int = 10) -> list[SearchResult]   # title, url, snippet
```

Selected by config; results cached 7 days; monthly query budget enforced.

## Classifier

```python
def classify(item: ClassifyInput) -> Classification
```

- Output: `relevant: bool`, `nebraska: bool`, `area`, `categories`, `confidence: float`,
  `decided_by: "rules" | "ai" | "none"`.
- Rules run first; AI is called only when rules are undecided and the monthly AI budget remains.
- AI call: Structured Outputs with a fixed JSON schema; source text passed as delimited data;
  no tools; output validated. Results cached by content hash.
- If AI is unavailable or over budget → `decided_by: "none"` → item goes to review.

## Extractor (newsletters and news)

```python
def extract_mentions(text: str, links: list[str]) -> list[EventMention]
```

Same AI safety rules as the classifier. Mentions are never published directly (FR-014).
