"""Fixtures compartidas. Todas las pruebas usan el backend REST simulado en
fake_backend.py: no hay ninguna conexión al router real en ningún test."""

from __future__ import annotations

import pytest

from tests.fake_backend import FakeMikroTikRestClient

NETWORK = "10.0.21.0/24"
OTHER_NETWORK = "10.0.22.0/24"


@pytest.fixture
def client() -> FakeMikroTikRestClient:
    """Cliente simulado con la red gestionada ya en MODE_NORMAL (miembro de
    SRC_GENERAL), como estaría una VLAN recién desplegada."""
    c = FakeMikroTikRestClient.create()
    c.seed_membership("SRC_GENERAL", NETWORK)
    return c
