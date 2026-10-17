"""Shared test configuration.

All tests run offline. Any real network connection fails the test unless it is explicitly
marked ``allow_network`` (never used in CI). HTTP calls must be mocked with respx.
"""

import socket
from collections.abc import Iterator
from typing import Any

import pytest

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


class NetworkAccessError(RuntimeError):
    """Raised when a test tries to open a real network connection."""


def _blocked(self: socket.socket, address: Any) -> Any:
    if self.family == getattr(socket, "AF_UNIX", None):
        return _real_connect(self, address)
    raise NetworkAccessError(f"Network access is blocked in tests (attempted {address!r})")


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest) -> Iterator[None]:
    if request.node.get_closest_marker("allow_network"):
        yield
        return
    mp = pytest.MonkeyPatch()
    mp.setattr(socket.socket, "connect", _blocked)
    mp.setattr(socket.socket, "connect_ex", _blocked)
    try:
        yield
    finally:
        mp.undo()
