"""Tratamiento explícito de listas heredadas: se detectan pero no se
convierten automáticamente, y la limpieza (si se invoca) se limita al
catálogo heredado y a la red administrada, sin afectar otras redes."""

from __future__ import annotations

from tests.conftest import NETWORK, OTHER_NETWORK
from tests.fake_backend import FakeMikroTikRestClient


def test_legacy_allow_detected_without_auto_conversion(client):
    client.seed_membership("ALLOW_MICROSOFT", NETWORK)

    legacy = client.get_legacy_allow_entries(NETWORK)
    assert legacy == {"ALLOW_MICROSOFT"}

    # detectar no debe crear ni modificar ALLOW_M365
    assert "ALLOW_M365" not in client.get_optional_allows(NETWORK)
    # ni eliminar la entrada heredada por sí sola
    assert client.get_legacy_allow_entries(NETWORK) == {"ALLOW_MICROSOFT"}


def test_legacy_cleanup_is_scoped_to_managed_network_only():
    client = FakeMikroTikRestClient.create()
    client.seed_membership("SRC_GENERAL", NETWORK)
    client.seed_membership("ALLOW_MICROSOFT", NETWORK)
    client.seed_membership("ALLOW_MICROSOFT", OTHER_NETWORK)  # otra red, no gestionada

    removed = client.remove_legacy_allow_entries(NETWORK)

    assert removed == 1
    assert client.get_legacy_allow_entries(NETWORK) == set()
    # la entrada de otra red no se toca
    assert any(e["list"] == "ALLOW_MICROSOFT" and e["address"] == OTHER_NETWORK for e in client.entries)


def test_legacy_cleanup_does_not_touch_other_allow_lists(client):
    client.seed_membership("ALLOW_MICROSOFT", NETWORK)
    client.seed_membership("ALLOW_AI", NETWORK)

    client.remove_legacy_allow_entries(NETWORK)

    assert client.get_optional_allows(NETWORK) == {"ALLOW_AI"}
