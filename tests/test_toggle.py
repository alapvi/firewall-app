"""toggle_allow_list(): activación y revocación de opciones, verificación
posterior, limpieza de conntrack solo tras un cambio efectivo, y fallo de
conntrack diferenciado del resultado del cambio de listas."""

from __future__ import annotations

import pytest

from mikrotik_api import MikroTikError
from tests.conftest import NETWORK
from tests.fake_backend import FakeMikroTikRestClient
from vlan_controller import VlanController


@pytest.fixture
def selective_client(client):
    client.set_mode_selective(NETWORK, allow_lists=(), comment="t")
    return client


@pytest.fixture
def controller(selective_client):
    c = VlanController(selective_client, NETWORK, comment="test")
    c.refresh_status()
    return c


def test_toggle_rejected_when_mode_is_not_selective():
    client = FakeMikroTikRestClient.create()
    client.seed_membership("SRC_GENERAL", NETWORK)
    controller = VlanController(client, NETWORK, comment="t")

    with pytest.raises(MikroTikError, match="MODE_SELECTIVE"):
        controller.toggle_allow("ALLOW_AI", True)


def test_toggle_enable_then_verify(controller, selective_client):
    result = controller.toggle_allow("ALLOW_AI", True)
    assert result.changed is True
    assert result.active is True
    assert "ALLOW_AI" in selective_client.get_optional_allows(NETWORK)
    # tras un alta efectiva también se intenta limpiar conntrack
    assert result.conntrack_cleared is not None or result.conntrack_error is not None


def test_toggle_disable_verifies_and_clears_conntrack(controller, selective_client):
    controller.toggle_allow("ALLOW_AI", True)
    selective_client.connections.append(
        {".id": "*c1", "src-address": "10.0.21.55:1234", "dst-address": "8.8.8.8:443"}
    )

    result = controller.toggle_allow("ALLOW_AI", False)

    assert result.changed is True
    assert result.active is False
    assert "ALLOW_AI" not in selective_client.get_optional_allows(NETWORK)
    assert result.conntrack_cleared == 1
    assert result.conntrack_error is None
    assert selective_client.connections == []


def test_toggle_no_change_skips_conntrack_cleanup(controller, selective_client):
    # ya está desactivada: pedir desactivarla de nuevo no debe tocar conntrack
    result = controller.toggle_allow("ALLOW_AI", False)
    assert result.changed is False
    assert result.conntrack_cleared is None
    assert result.conntrack_error is None


def test_conntrack_failure_is_differentiated_from_list_change_result(controller, selective_client):
    controller.toggle_allow("ALLOW_AI", True)
    selective_client.connections.append({".id": "*c1", "src-address": "10.0.21.10:1"})

    calls_before = len(selective_client.call_log)
    # La siguiente escritura (DELETE de ALLOW_AI) tiene éxito; se hace fallar la
    # limpieza de conntrack posterior sin afectar al resultado de la lista.
    def hook(n, method, path, kwargs):
        if path.startswith("/ip/firewall/connection/"):
            return MikroTikError("fallo simulado limpiando conntrack")
        return None

    selective_client.on_call = hook
    result = controller.toggle_allow("ALLOW_AI", False)
    selective_client.on_call = None

    assert result.changed is True
    assert result.active is False  # el cambio de lista sí se aplicó y se verificó
    assert result.conntrack_error is not None
    assert result.conntrack_cleared is None
    # la conexión preexistente sigue activa: no se afirma un corte que no ocurrió
    assert len(selective_client.connections) == 1


def test_checkboxes_sync_with_read_state_not_requested_state(controller, selective_client):
    # Se simula que otra fuente (WinBox) ya había añadido la entrada.
    selective_client.seed_membership("ALLOW_SEARCH", NETWORK)

    result = controller.toggle_allow("ALLOW_SEARCH", True)
    # no hay cambio real (ya existía), pero el estado verificado sigue siendo activo
    assert result.changed is False
    assert result.active is True
    assert controller.current_allows == {"ALLOW_SEARCH"}


def test_toggle_raises_when_verified_state_does_not_match_request(controller, selective_client):
    """Si tras revocar un permiso otra fuente (p. ej. WinBox) lo vuelve a añadir
    antes de la relectura, el resultado no debe darse por bueno en silencio."""
    controller.toggle_allow("ALLOW_AI", True)

    def hook(n, method, path, kwargs):
        if method == "DELETE" and path.startswith("/ip/firewall/address-list/"):
            selective_client.entries.append(
                {".id": "*999", "list": "ALLOW_AI", "address": NETWORK, "comment": "winbox", "disabled": "false"}
            )
        return None

    selective_client.on_call = hook
    with pytest.raises(MikroTikError, match="No se pudo confirmar"):
        controller.toggle_allow("ALLOW_AI", False)
    selective_client.on_call = None

    # se conserva el estado realmente leído: sigue activo, pese a haberse pedido revocarlo
    assert controller.current_allows == {"ALLOW_AI"}


def test_toggle_skips_conntrack_when_request_not_fulfilled(controller, selective_client):
    controller.toggle_allow("ALLOW_AI", True)
    selective_client.connections.append({".id": "*c1", "src-address": "10.0.21.10:1"})

    def hook(n, method, path, kwargs):
        if method == "DELETE" and path.startswith("/ip/firewall/address-list/"):
            selective_client.entries.append(
                {".id": "*999", "list": "ALLOW_AI", "address": NETWORK, "comment": "winbox", "disabled": "false"}
            )
        return None

    selective_client.on_call = hook
    with pytest.raises(MikroTikError):
        controller.toggle_allow("ALLOW_AI", False)
    selective_client.on_call = None

    # como la revocación no se confirmó, no se debe haber intentado limpiar conntrack
    assert len(selective_client.connections) == 1


def test_refresh_status_marks_unknown_on_any_mikrotik_error(controller, selective_client):
    """La recuperación de estado debe tratar como no verificado cualquier error
    REST (p. ej. HTTP 403), no solo la pérdida de conexión."""
    calls_before = len(selective_client.call_log)
    selective_client.fail_at(calls_before + 1, MikroTikError("HTTP 403 Forbidden"))

    with pytest.raises(MikroTikError):
        controller.refresh_status()

    assert controller.status_known is False
    assert controller.current_mode is None
