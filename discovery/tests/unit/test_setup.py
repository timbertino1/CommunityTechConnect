"""Smoke tests for the project skeleton and the offline test guard."""

import socket

import pytest

import netc
from tests.conftest import NetworkAccessError


@pytest.mark.unit
def test_package_has_version() -> None:
    assert netc.__version__ == "0.1.0"


@pytest.mark.unit
def test_real_network_connections_are_blocked() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s,
        pytest.raises(NetworkAccessError),
    ):
        s.connect(("192.0.2.1", 443))  # TEST-NET-1, never routable
