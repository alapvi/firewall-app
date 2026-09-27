"""Bloqueo de operaciones simultáneas en la misma instancia y recuperación de
la interfaz tras errores. No cubre bloqueos entre instancias distintas ni
frente a cambios hechos desde WinBox: eso queda fuera del alcance del lock
local."""

from __future__ import annotations

import threading

import pytest

from tests.conftest import NETWORK
from vlan_controller import OperationInProgressError, VlanController


def test_second_concurrent_operation_is_rejected(client):
    controller = VlanController(client, NETWORK, comment="t")
    controller.begin_operation()
    try:
        with pytest.raises(OperationInProgressError):
            controller.begin_operation()
    finally:
        controller.end_operation()


def test_lock_is_released_after_operation_completes(client):
    controller = VlanController(client, NETWORK, comment="t")
    controller.begin_operation()
    controller.end_operation()

    # una vez liberado, una nueva operación puede empezar sin problema
    controller.begin_operation()
    controller.end_operation()


def test_lock_prevents_concurrent_writes_from_two_threads(client):
    controller = VlanController(client, NETWORK, comment="t")
    started = threading.Event()
    release = threading.Event()
    rejected = []

    def holder():
        controller.begin_operation()
        started.set()
        release.wait(timeout=2)
        controller.end_operation()

    t = threading.Thread(target=holder)
    t.start()
    assert started.wait(timeout=2)

    try:
        controller.begin_operation()
        controller.end_operation()
        rejected.append(False)
    except OperationInProgressError:
        rejected.append(True)
    finally:
        release.set()
        t.join(timeout=2)

    assert rejected == [True]
