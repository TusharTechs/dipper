"""Tests never touch the network or the repository's data directory."""
import socket

import pytest


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    def refuse(*args, **kwargs):
        raise OSError("network access is disabled in tests")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setenv("DIPPER_CACHE", str(tmp_path / "weather-cache"))
