"""Rechazo previo de MODE_NORMAL cuando no se cumple el requisito de
pertenencia a SRC_GENERAL, y comprobación de que la app nunca añade ni retira
esa lista."""

from __future__ import annotations

import pytest

from mikrotik_api import MikroTikError
from tests.conftest import NETWORK
from tests.fake_backend import FakeMikroTikRestClient


def test_normal_rejected_without_src_general():
    client = FakeMikroTikRestClient.create()
    client.seed_membership("MODE_EXAM", NETWORK)  # sin SRC_GENERAL

    with pytest.raises(MikroTikError, match="SRC_GENERAL"):
        client.set_mode_normal(NETWORK)

    # no se ha modificado ninguna entrada: la restricción se mantiene
    assert client.get_vlan_mode(NETWORK) == "MODE_EXAM"


def test_normal_succeeds_when_src_general_present(client):
    client.set_mode_exam(NETWORK, comment="t")
    client.set_mode_normal(NETWORK)
    assert client.get_vlan_mode(NETWORK) == "MODE_NORMAL"
    assert client.is_member_of("SRC_GENERAL", NETWORK)


def test_app_never_adds_or_removes_src_general(client):
    entries_before = [e for e in client.entries if e["list"] == "SRC_GENERAL"]

    client.set_mode_exam(NETWORK, comment="t")
    client.set_mode_restricted(NETWORK, comment="t")
    client.set_mode_selective(NETWORK, allow_lists=("ALLOW_AI",), comment="t")
    client.set_mode_normal(NETWORK)

    entries_after = [e for e in client.entries if e["list"] == "SRC_GENERAL"]
    assert entries_before == entries_after
