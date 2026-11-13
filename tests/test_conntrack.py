"""Regresiones reales de conntrack, sin red ni router."""
import pytest

from mikrotik_api import ConntrackCleanupError, MikroTikConnectionError, MikroTikError, MikroTikHTTPError
from tests.conftest import NETWORK


def connection(id="*c1", **kwargs):
    return {".id": id, "protocol": "tcp", "src-address": "10.0.21.10:1234", "dst-address": "203.0.113.1:443", **kwargs}


@pytest.mark.parametrize("key", ["src-address", "dst-address", "reply-src-address", "reply-dst-address"])
@pytest.mark.parametrize("endpoint", ["10.0.21.20", "10.0.21.20:443"])
def test_matches_all_original_and_nat_endpoints(client, key, endpoint):
    client.connections = [{".id": "*c1", key: endpoint}, {".id": "*other", "src-address": "10.0.22.10:443"}]
    assert client.clear_connections_for_network(NETWORK) == 1
    assert [c[".id"] for c in client.connections] == ["*other"]


def test_expired_entry_does_not_abort_remaining_deletions(client):
    client.connections = [connection(), connection("*c2")]
    def expire(n, method, path, kwargs):
        if method == "DELETE" and path.endswith("/*c1"):
            client.connections = [c for c in client.connections if c[".id"] != "*c1"]
            return MikroTikHTTPError(404, "Not Found")
    client.on_call = expire
    assert client.clear_connections_for_network(NETWORK) == 2
    assert not client.connections


def test_error_on_one_entry_does_not_skip_others_and_is_reported(client):
    client.connections = [connection(), connection("*c2")]
    client.on_call = lambda n, method, path, kwargs: MikroTikError("failed") if method == "DELETE" and path.endswith("/*c1") else None
    with pytest.raises(ConntrackCleanupError, match="quedan 1 de 2") as failure:
        client.clear_connections_for_network(NETWORK)
    assert failure.value.cleared == 1
    assert [c[".id"] for c in client.connections] == ["*c1"]


def test_transient_failure_retried_only_after_read(client):
    client.connections = [connection()]
    client.fail_at(2, MikroTikError("temporary"))
    assert client.clear_connections_for_network(NETWORK) == 1
    assert [m for _, m, _ in client.call_log] == ["GET", "DELETE", "GET", "DELETE", "GET"]


def test_missing_id_404_is_not_ignored_if_entry_still_exists(client):
    client.connections = [connection()]
    client.on_call = lambda n, method, path, kwargs: MikroTikHTTPError(404, "wrong endpoint") if method == "DELETE" else None
    with pytest.raises(ConntrackCleanupError):
        client.clear_connections_for_network(NETWORK)


def test_response_lost_after_delete_can_be_verified_without_second_write(client):
    client.connections = [connection()]
    def lost(n, method, path, kwargs):
        if method == "DELETE":
            client.connections.clear()
            return MikroTikConnectionError("response lost")
    client.on_call = lost
    assert client.clear_connections_for_network(NETWORK) == 1
    assert [m for _, m, _ in client.call_log] == ["GET", "DELETE", "GET"]


def test_no_blind_retry_after_network_failure(client):
    client.connections = [connection(), connection("*c2")]
    client.on_call = lambda n, method, path, kwargs: MikroTikConnectionError("offline") if method == "DELETE" else None
    with pytest.raises(ConntrackCleanupError):
        client.clear_connections_for_network(NETWORK)
    assert [m for _, m, _ in client.call_log] == ["GET", "DELETE", "GET"]


def test_failure_of_final_read_is_not_success(client):
    client.connections = [connection()]
    client.fail_at(3, MikroTikConnectionError("offline"))
    with pytest.raises(ConntrackCleanupError, match="verificar"):
        client.clear_connections_for_network(NETWORK)


def test_new_allowed_connections_do_not_require_endless_empty_table(client):
    client.connections = [connection()]
    def new_flow(n, method, path, kwargs):
        if n == 3:
            client.connections.append(connection("*new"))
    client.on_call = new_flow
    assert client.clear_connections_for_network(NETWORK) == 1
    assert [c[".id"] for c in client.connections] == ["*new"]


@pytest.mark.parametrize("separate_port", [False, True])
def test_rest_control_preserved_but_other_traffic_to_router_removed(client, separate_port):
    client.host = "10.99.0.1"
    client.port = 7443
    rest = connection()
    rest["dst-address"] = "10.99.0.1" if separate_port else "10.99.0.1:7443"
    if separate_port:
        rest["dst-port"] = "7443"
    client.connections = [rest, connection("*ssh", **{"dst-address": "10.99.0.1:22"})]
    assert client.clear_connections_for_network(NETWORK) == 1
    assert [c[".id"] for c in client.connections] == ["*c1"]


def test_large_snapshot_does_not_touch_other_networks(client):
    client.connections = [connection(f"*c{i}") for i in range(1500)] + [connection("*other", **{"src-address": "10.0.22.1:50"})]
    assert client.clear_connections_for_network(NETWORK) == 1500
    assert [c[".id"] for c in client.connections] == ["*other"]


def test_budget_exhaustion_reports_partial_without_writes(client):
    client.connections = [connection()]
    with pytest.raises(ConntrackCleanupError, match="Límite"):
        client.clear_connections_for_network(NETWORK, budget_seconds=0)
    assert not any(m == "DELETE" for _, m, _ in client.call_log)


@pytest.mark.parametrize("network", ["0.0.0.0/0", "10.0.21.5/24", "::/0", "bad"])
def test_invalid_or_global_network_rejected_before_request(client, network):
    with pytest.raises(ValueError):
        client.clear_connections_for_network(network)
    assert not client.call_log


@pytest.mark.parametrize("row", [{"src-address": "10.0.21.1:5"}, {".id": "*bad"}])
def test_malformed_snapshot_is_not_empty_success(client, row):
    client.connections = [row]
    with pytest.raises(MikroTikError):
        client.clear_connections_for_network(NETWORK)


@pytest.mark.parametrize("status", [401, 403])
def test_permission_failure_stops_writes_and_does_not_claim_cleanup(client, status):
    client.connections = [connection(), connection("*c2")]
    client.on_call = lambda n, m, p, kw: MikroTikHTTPError(status, "denied") if m == "DELETE" else None
    with pytest.raises(ConntrackCleanupError):
        client.clear_connections_for_network(NETWORK)
    assert len([1 for _, m, _ in client.call_log if m == "DELETE"]) == 1
