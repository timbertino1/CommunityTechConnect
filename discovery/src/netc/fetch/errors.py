"""Errors raised by netc.fetch. Every one is a FetchError, so callers can catch them as one."""


class FetchError(Exception):
    """A URL could not be fetched safely."""


class UnsafeURLError(FetchError):
    """The URL, its host, or an address it resolves to is not allowed (SSRF protection)."""


class RobotsDisallowedError(FetchError):
    """The site's robots.txt does not allow our bot to fetch this path."""


class RobotsUnavailableError(FetchError):
    """robots.txt could not be read (server error or network failure), so the host is skipped."""


class BudgetExceededError(FetchError):
    """The per-host request budget for this run is used up."""


class TooManyRedirectsError(FetchError):
    """The redirect chain was longer than allowed."""


class ResponseTooLargeError(FetchError):
    """The response body exceeded the size cap for its kind."""


class ContentTypeNotAllowedError(FetchError):
    """The response content type is not one the caller accepts."""


class FetchTimeoutError(FetchError):
    """Connecting or downloading took longer than allowed."""
