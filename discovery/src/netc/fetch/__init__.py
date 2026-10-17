"""netc.fetch: safe, polite HTTP for untrusted URLs. The only package allowed to import httpx."""

from netc.fetch.errors import (
    BudgetExceededError,
    ContentTypeNotAllowedError,
    FetchError,
    FetchTimeoutError,
    ResponseTooLargeError,
    RobotsDisallowedError,
    RobotsUnavailableError,
    TooManyRedirectsError,
    UnsafeURLError,
)
from netc.fetch.safe_fetch import (
    DEFAULT_CONTENT_TYPES,
    MAX_BYTES,
    FetchKind,
    FetchResponse,
    Resolver,
    SafeHttp,
)
from netc.fetch.urls import IPAddress, is_public_ip, vet_hostname, vet_url

__all__ = [
    "DEFAULT_CONTENT_TYPES",
    "MAX_BYTES",
    "BudgetExceededError",
    "ContentTypeNotAllowedError",
    "FetchError",
    "FetchKind",
    "FetchResponse",
    "FetchTimeoutError",
    "IPAddress",
    "Resolver",
    "ResponseTooLargeError",
    "RobotsDisallowedError",
    "RobotsUnavailableError",
    "SafeHttp",
    "TooManyRedirectsError",
    "UnsafeURLError",
    "is_public_ip",
    "vet_hostname",
    "vet_url",
]
