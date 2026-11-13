"""Métodos de UI con widgets simulados; no prueban un escritorio real."""
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess
import sys

import pytest

pytest.importorskip("tkinter")
import app
from mikrotik_api import MikroTikConnectionError, MikroTikError
from vlan_controller import VlanController, StatusSnapshot, TransitionResult
from tests.conftest import NETWORK


def ui(client):
    c = VlanController(client, NETWORK, "test")
    c.refresh_status()
    instance = SimpleNamespace(
        controller=c, current_mode="MODE_NORMAL", _busy=False,
        status_var=Mock(), cleanup_var=Mock(), cleanup_label=Mock(),
        allow_checkbuttons=[Mock()], append_log=Mock(), update_allow_vars=Mock(),
    )
    for name in ("refresh_btn", "exam_btn", "restricted_btn", "selective_btn", "normal_btn", "cleanup_btn"):
        setattr(instance, name, Mock())
    for name in ("set_buttons_enabled", "_show_unknown_state", "_apply_snapshot", "_handle_failure", "_show_cleanup_result"):
        setattr(instance, name, getattr(app.VlanModeApp, name).__get__(instance))
    instance.callbacks = []
    instance.after = lambda delay, callback: instance.callbacks.append(callback)
    return instance


def drain(instance):
    while instance.callbacks:
        instance.callbacks.pop(0)()


def test_network_loss_invalidates_visible_and_controller_state(client, monkeypatch):
    monkeypatch.setattr(app.messagebox, "showerror", Mock())
    instance = ui(client)
    instance._handle_failure(MikroTikConnectionError("offline"))
    drain(instance)
    assert instance.current_mode is None
    assert not instance.controller.status_known
    assert "DESCONOCIDO" in instance.status_var.set.call_args.args[0]
    instance.normal_btn.config.assert_called_with(state="disabled")
    instance.refresh_btn.config.assert_called_with(state="normal")


def test_failed_cleanup_is_visible_warning_not_complete_success(client, monkeypatch):
    warning = Mock()
    monkeypatch.setattr(app.messagebox, "showwarning", warning)
    instance = ui(client)
    instance._show_cleanup_result(TransitionResult("MODE_EXAM", conntrack_error="remaining=1"))
    assert "INCOMPLETA" in instance.cleanup_var.set.call_args.args[0]
    instance.cleanup_label.config.assert_called_with(fg="red")
    warning.assert_called_once()


def test_snapshot_does_not_enable_allow_buttons_mid_operation(client):
    instance = ui(client)
    instance._busy = True
    instance._apply_snapshot(StatusSnapshot("MODE_SELECTIVE", set(), True))
    instance.allow_checkbuttons[0].config.assert_called_with(state="disabled")


def test_lock_held_until_ui_applies_queued_results(client, monkeypatch):
    instance = ui(client)
    monkeypatch.setattr(app.threading, "Thread", lambda target, daemon: SimpleNamespace(start=target))
    app.VlanModeApp.run_async(instance, "test", lambda: None)
    assert instance._busy
    assert instance.controller._lock.locked()
    instance.normal_btn.config.assert_called_with(state="disabled")
    drain(instance)
    assert not instance._busy
    assert not instance.controller._lock.locked()
    instance.normal_btn.config.assert_called_with(state="normal")


def test_read_only_refresh_cannot_erase_previous_cleanup_warning(client):
    instance = ui(client)
    instance._apply_snapshot(StatusSnapshot("MODE_EXAM", set(), True))
    instance.cleanup_var.set.assert_not_called()


def test_error_dialog_shown_after_visible_state_updated(client, monkeypatch):
    instance = ui(client)
    client.on_call = lambda *args: MikroTikError("cannot read")
    seen = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda *args: seen.append(instance.current_mode))
    instance._handle_failure(MikroTikError("HTTP failure"))
    drain(instance)
    assert seen == [None]


def test_version_available_without_display_or_credentials():
    result = subprocess.run([sys.executable, "app.py", "--version"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "firewall-app 1.4.1"
