from unittest.mock import Mock
import pytest
import requests

from mikrotik_api import MikroTikRestClient, MikroTikConnectionError, MikroTikHTTPError, MikroTikError
from tests.conftest import NETWORK


def test_network_error_classified_without_retry():
    c = MikroTikRestClient("127.0.0.1", 7443, "test", "test")
    c._session = Mock()
    c._session.request.side_effect = requests.ConnectionError("[Errno 101] Network is unreachable")
    with pytest.raises(MikroTikConnectionError):
        c.get_address_list_entries()
    assert c._session.request.call_count == 1


@pytest.mark.parametrize("data", [None, "not json", {"error": "unexpected"}, ["bad row"]])
@pytest.mark.parametrize("method", ["get_address_list_entries", "get_connections", "get_allow_list_names"])
def test_invalid_tables_cannot_be_misinterpreted_as_empty(data, method):
    c = MikroTikRestClient("fake", 7443, "test", "test")
    c._request = Mock(return_value=data)
    with pytest.raises(MikroTikError):
        getattr(c, method)()


def test_lost_delete_response_does_not_trigger_post(client):
    client.seed_membership("MODE_EXAM", NETWORK)
    client.on_call = lambda n, m, p, kw: MikroTikConnectionError("offline") if m == "DELETE" else None
    with pytest.raises(MikroTikConnectionError):
        client.remove_address("MODE_EXAM", NETWORK)
    assert not any(m == "POST" for _, m, _ in client.call_log)


def test_successful_delete_with_lost_response_verified_by_reread(client):
    client.seed_membership("MODE_EXAM", NETWORK)
    def lost(n, m, p, kw):
        if m == "DELETE":
            client.entries = [e for e in client.entries if e["list"] != "MODE_EXAM"]
            return MikroTikConnectionError("lost response")
    client.on_call = lost
    assert client.remove_address("MODE_EXAM", NETWORK) == 1
    assert not any(m == "POST" for _, m, _ in client.call_log)


@pytest.mark.parametrize("status", [400, 401, 403, 500])
def test_failed_put_never_falls_back_to_another_write(client, status):
    client.on_call = lambda n, m, p, kw: MikroTikHTTPError(status, "failed") if m == "PUT" else None
    with pytest.raises(MikroTikHTTPError):
        client.add_address_if_missing("MODE_EXAM", NETWORK)
    assert not any(m == "POST" for _, m, _ in client.call_log)


def test_incomplete_address_row_cannot_look_like_normal():
    c = MikroTikRestClient("fake", 7443, "test", "test")
    c._request = Mock(return_value=[{".id": "*bad"}])
    with pytest.raises(MikroTikError, match="incompleta"):
        c.get_vlan_mode(NETWORK)


def test_legacy_rule_does_not_reappear_as_selectable_option(client):
    client.filter_rules.append({"chain": "forward", "action": "accept", "src-address-list": "ALLOW_MICROSOFT"})
    assert "ALLOW_MICROSOFT" not in client.get_allow_list_names()
