"""Descubrimiento de permisos selectivos desde reglas forward del firewall."""

from __future__ import annotations

import pytest

from mikrotik_api import MikroTikError
from tests.conftest import NETWORK


def _rule(name, chain="forward", action="accept", disabled="false"):
    return {
        "chain": chain,
        "action": action,
        "src-address-list": name,
        "disabled": disabled,
    }


def test_discovers_only_active_forward_accept_allow_rules(client):
    client.filter_rules = [
        _rule("ALLOW_NEW_SERVICE"),
        _rule("ALLOW_DISABLED", disabled="true"),
        _rule("ALLOW_INPUT", chain="input"),
        _rule("ALLOW_DROP", action="drop"),
        _rule("!ALLOW_NEGATED"),
        _rule("ALLOW_"),
        _rule("OTHER_LIST"),
    ]

    assert client.get_allow_list_names() == {"ALLOW_NEW_SERVICE"}


def test_new_rule_can_be_selected_and_added_without_a_code_catalog(client):
    client.filter_rules.append(_rule("ALLOW_NEW_SERVICE"))

    client.set_mode_selective(NETWORK, allow_lists=("ALLOW_NEW_SERVICE",), comment="test")

    assert client.get_vlan_mode(NETWORK) == "MODE_SELECTIVE"
    assert client.get_optional_allows(NETWORK) == {"ALLOW_NEW_SERVICE"}


def test_unconfigured_allow_name_is_rejected_before_writes(client):
    with pytest.raises(ValueError, match="sin regla forward accept activa"):
        client.set_mode_selective(NETWORK, allow_lists=("ALLOW_NOT_CONFIGURED",))

    assert not any(method in ("PUT", "POST", "DELETE") for _, method, _ in client.call_log)


def test_leaving_selective_clears_orphaned_allows_but_preserves_legacy(client):
    client.seed_membership("MODE_SELECTIVE", NETWORK)
    client.seed_membership("ALLOW_REMOVED_RULE", NETWORK)
    client.seed_membership("ALLOW_MICROSOFT", NETWORK)

    client.set_mode_normal(NETWORK)

    assert not client.is_member_of("ALLOW_REMOVED_RULE", NETWORK)
    assert client.is_member_of("ALLOW_MICROSOFT", NETWORK)