"""Fallos de lectura, alta y eliminación en puntos relevantes de las
transiciones: ante un fallo no se debe ampliar el conjunto de permisos ni
perder la última restricción conocida."""

from __future__ import annotations

import pytest

from mikrotik_api import MikroTikConnectionError, MikroTikError, SPECIAL_MODES
from tests.conftest import NETWORK
from tests.fake_backend import FakeMikroTikRestClient, connection_error


def _active_special_modes(client, network=NETWORK):
    return {e["list"] for e in client.entries if e.get("address") == network and e.get("list") in SPECIAL_MODES}


def test_conflict_detected_before_starting_is_reported_and_aborts():
    """Un conflicto de modos presente ANTES de empezar (p. ej. tras una edición
    manual en WinBox) se distingue de un estado transitorio propio: se aborta
    sin tocar nada."""
    client = FakeMikroTikRestClient.create()
    client.seed_membership("MODE_EXAM", NETWORK)
    client.seed_membership("MODE_RESTRICTED", NETWORK)

    with pytest.raises(MikroTikError, match="Conflicto de modos"):
        client.set_mode_selective(NETWORK, allow_lists=("ALLOW_AI",), comment="t")

    # ninguna entrada nueva se ha añadido ni retirado
    assert _active_special_modes(client) == {"MODE_EXAM", "MODE_RESTRICTED"}


def test_failure_adding_target_mode_keeps_previous_restriction(client):
    client.set_mode_restricted(NETWORK, comment="t")

    # Falla la escritura que añadiría MODE_SELECTIVE (primer PUT tras la lectura inicial)
    calls_before = len(client.call_log)
    client.fail_at(calls_before + 2, MikroTikError("fallo simulado al añadir MODE_SELECTIVE"))

    with pytest.raises(MikroTikError):
        client.set_mode_selective(NETWORK, allow_lists=("ALLOW_AI",), comment="t")

    # la restricción anterior sigue activa; no se ha ampliado el acceso
    assert client.get_vlan_mode(NETWORK) == "MODE_RESTRICTED"


def test_failure_removing_stale_mode_leaves_both_restrictions_active(client):
    client.set_mode_exam(NETWORK, comment="t")

    # Se deja que la escritura del destino tenga éxito, pero falla justo el
    # DELETE que retiraría la restricción antigua (MODE_EXAM) al final.
    def hook(n, method, path, kwargs):
        if method == "DELETE" and path.startswith("/ip/firewall/address-list/"):
            return MikroTikError("fallo simulado al retirar la restricción antigua")
        return None

    client.on_call = hook

    with pytest.raises(MikroTikError):
        client.set_mode_restricted(NETWORK, comment="t")

    client.on_call = None
    # ambas restricciones siguen presentes: es más restrictivo, nunca menos
    assert _active_special_modes(client) == {"MODE_EXAM", "MODE_RESTRICTED"}


def test_connection_loss_during_verification_is_not_silently_treated_as_success(client):
    client.set_mode_exam(NETWORK, comment="t")

    calls_before = len(client.call_log)
    # Se corta la conexión en la última lectura de verificación
    client.fail_at(calls_before + 5, connection_error())

    with pytest.raises(MikroTikConnectionError):
        client.set_mode_restricted(NETWORK, comment="t")


def test_read_failure_before_any_write_leaves_state_untouched():
    client = FakeMikroTikRestClient.create()
    client.seed_membership("MODE_EXAM", NETWORK)
    client.fail_at(1, connection_error())

    with pytest.raises(MikroTikConnectionError):
        client.set_mode_restricted(NETWORK, comment="t")

    client.on_call = None
    assert client.get_vlan_mode(NETWORK) == "MODE_EXAM"
