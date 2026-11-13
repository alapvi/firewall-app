import pytest

from mikrotik_api import MikroTikConnectionError, MikroTikError
from tests.conftest import NETWORK
from vlan_controller import VlanController


@pytest.mark.parametrize("start", ["MODE_NORMAL", "MODE_EXAM", "MODE_RESTRICTED", "MODE_SELECTIVE"])
@pytest.mark.parametrize("target", ["MODE_EXAM", "MODE_RESTRICTED"])
def test_restrictive_transition_cleans_old_flows_and_verifies_final_mode(client, start, target):
    c = VlanController(client, NETWORK, "test")
    c.set_mode(start)
    client.connections = [{".id": "*old", "src-address": "10.0.21.50:443"}]
    result = c.set_mode(target)
    assert result.mode == target
    assert result.conntrack_cleared == 1
    assert result.conntrack_error is None
    assert not client.connections
    assert client.get_vlan_mode(NETWORK) == target
    # Se eliminan conexiones incluso al volver a pulsar el mismo modo.


def test_cleanup_failure_keeps_restriction_and_retry_does_not_change_lists(client):
    c = VlanController(client, NETWORK, "test")
    client.connections = [{".id": "*old", "src-address": "10.0.21.50:443"}]
    client.on_call = lambda n, m, p, kw: MikroTikError("failed") if m == "DELETE" and "/connection/" in p else None
    result = c.set_mode("MODE_EXAM")
    assert result.mode == "MODE_EXAM"
    assert result.conntrack_error
    assert c.status_known
    assert client.get_vlan_mode(NETWORK) == "MODE_EXAM"
    client.on_call = None
    before = len(client.call_log)
    retry = c.retry_conntrack()
    assert retry.conntrack_error is None
    assert retry.conntrack_cleared == 1
    assert not any(m != "GET" and "/address-list" in p for _, m, p in client.call_log[before:])


def test_failure_before_mode_write_invalidates_controller(client):
    c = VlanController(client, NETWORK, "test")
    c.refresh_status()
    client.fail_at(len(client.call_log) + 1, MikroTikConnectionError("offline"))
    with pytest.raises(MikroTikConnectionError):
        c.set_mode("MODE_EXAM")
    assert c.current_mode is None
    assert not c.status_known


def test_mode_changed_elsewhere_during_cleanup_is_not_claimed_as_target(client):
    c = VlanController(client, NETWORK, "test")
    def concurrent(n, m, p, kw):
        if p == "/ip/firewall/connection" and m == "GET":
            client.entries = [e for e in client.entries if e["list"] != "MODE_EXAM"]
    client.on_call = concurrent
    with pytest.raises(MikroTikError, match="cambiaron"):
        c.set_mode("MODE_EXAM")
    assert not c.status_known


def test_cannot_verify_mode_after_cleanup_when_connection_is_lost(client):
    c = VlanController(client, NETWORK, "test")
    seen_cleanup = False
    def lost(n, m, p, kw):
        nonlocal seen_cleanup
        if p == "/ip/firewall/connection":
            seen_cleanup = True
        if seen_cleanup and p == "/ip/firewall/address-list":
            return MikroTikConnectionError("offline")
    client.on_call = lost
    with pytest.raises(MikroTikConnectionError):
        c.set_mode("MODE_RESTRICTED")
    assert not c.status_known
    assert any(e["list"] == "MODE_RESTRICTED" for e in client.entries)


def test_cleanup_only_starts_after_target_mode_has_been_written(client):
    c = VlanController(client, NETWORK, "test")
    observed = []
    def observe(n, m, p, kw):
        if p == "/ip/firewall/connection":
            observed.append({e["list"] for e in client.entries})
    client.on_call = observe
    c.set_mode("MODE_RESTRICTED")
    assert observed and all("MODE_RESTRICTED" in s and "MODE_EXAM" not in s for s in observed)


def test_concurrent_mode_change_before_cleanup_is_rejected(client, monkeypatch):
    c = VlanController(client, NETWORK, "test")
    original = c._set_mode_lists
    def intervening(target, allows):
        original(target, allows)
        client.entries = [e for e in client.entries if e["list"] != "MODE_EXAM"]
    monkeypatch.setattr(c, "_set_mode_lists", intervening)
    with pytest.raises(MikroTikError, match="antes de la limpieza"):
        c.set_mode("MODE_EXAM")
    assert not c.status_known
    assert not any("/connection" in p for _, _, p in client.call_log)
