"""Estado final correcto de las 16 combinaciones entre los cuatro modos, y
ausencia de intervalos sin modo restrictivo al transitar entre modos
especiales (EXAM/RESTRICTED/SELECTIVE)."""

from __future__ import annotations

import itertools

import pytest

from mikrotik_api import SPECIAL_MODES
from tests.conftest import NETWORK

MODES = ("MODE_EXAM", "MODE_RESTRICTED", "MODE_SELECTIVE", "MODE_NORMAL")


def _apply(client, network, mode):
    if mode == "MODE_NORMAL":
        client.set_mode_normal(network)
    elif mode == "MODE_EXAM":
        client.set_mode_exam(network, comment="t")
    elif mode == "MODE_RESTRICTED":
        client.set_mode_restricted(network, comment="t")
    elif mode == "MODE_SELECTIVE":
        client.set_mode_selective(network, allow_lists=("ALLOW_AI",), comment="t")


@pytest.mark.parametrize("start,target", list(itertools.product(MODES, MODES)))
def test_all_16_transitions_reach_expected_final_state(client, start, target):
    _apply(client, NETWORK, start)
    assert client.get_vlan_mode(NETWORK) == start

    _apply(client, NETWORK, target)
    assert client.get_vlan_mode(NETWORK) == target

    # nunca debe quedar pertenencia a más de un modo especial a la vez
    active_special = {
        e["list"] for e in client.entries
        if e.get("address") == NETWORK and e.get("list") in SPECIAL_MODES
    }
    assert len(active_special) <= 1

    # SRC_GENERAL nunca se toca por la aplicación
    assert client.is_member_of("SRC_GENERAL", NETWORK)


@pytest.mark.parametrize(
    "start,target",
    [(a, b) for a, b in itertools.product(("MODE_EXAM", "MODE_RESTRICTED", "MODE_SELECTIVE"), repeat=2) if a != b],
)
def test_no_gap_without_restriction_between_special_modes(client, start, target):
    """Durante una transición entre dos modos especiales, la restricción previa
    solo se retira después de confirmar el destino: en ningún punto intermedio
    la red deja de pertenecer a al menos un modo especial (nunca MODE_NORMAL).

    Puede haber un instante en el que la lectura simple (get_vlan_mode) informe
    de pertenencia simultánea a dos modos especiales -aparenta un "conflicto"-
    porque el puente de protección y el destino conviven brevemente; eso es un
    estado transitorio controlado por la propia transición, no una ausencia de
    restricción ni el conflicto detectado al iniciar una operación nueva.
    """
    _apply(client, NETWORK, start)

    observed_active_special = []
    original_remove = client._request

    # Se envuelve _request para inspeccionar el estado tras cada escritura,
    # simulando lo que vería una lectura concurrente durante la transición.
    def spying_request(method, path, **kwargs):
        result = original_remove(method, path, **kwargs)
        if method in ("PUT", "DELETE"):
            observed_active_special.append(client._read_special_modes(NETWORK))
        return result

    client._request = spying_request
    _apply(client, NETWORK, target)
    client._request = original_remove

    assert client.get_vlan_mode(NETWORK) == target
    for active in observed_active_special:
        # nunca vacío (eso equivaldría a MODE_NORMAL) y nunca más de dos modos
        # especiales a la vez (el puente/anterior y el destino, como máximo)
        assert len(active) >= 1
        assert len(active) <= 2
