#!/usr/bin/env python3
"""
Aplicación Tkinter para cambiar una VLAN entre MODE_NORMAL, MODE_EXAM y MODE_RESTRICTED
en un MikroTik CCR2216 usando RouterOS REST API.

Diseñada para servidores Ubuntu antiguos donde PySide6/Qt puede fallar por CPU sin SSE4.

Uso:
  python3 app.py --host 10.99.0.1 --port 7443 --user firewall-app --vlan 21 --network 10.0.21.0/24 --name "Saló de Actes"
"""

from __future__ import annotations

import argparse
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog
from dataclasses import dataclass

from mikrotik_api import MikroTikRestClient, MikroTikError


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    username: str
    password: str
    vlan_id: str
    network: str
    vlan_name: str
    verify_ssl: bool


class VlanModeApp(tk.Tk):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.client = MikroTikRestClient(
            host=config.host,
            port=config.port,
            username=config.username,
            password=config.password,
            verify_ssl=config.verify_ssl,
            timeout=12,
        )

        self.title(f"MikroTik VLAN Modes - VLAN {config.vlan_id}")
        self.geometry("850x560")

        self._build_ui()
        self.refresh_status()

    def _build_ui(self) -> None:
        title = tk.Label(self, text="Gestión de modo de VLAN", font=("Arial", 18, "bold"))
        title.pack(pady=(14, 8))

        info_text = (
            f"CCR: {self.config.host}:{self.config.port}    "
            f"VLAN: {self.config.vlan_id}    "
            f"Nombre: {self.config.vlan_name}    "
            f"Red: {self.config.network}"
        )
        info = tk.Label(self, text=info_text, font=("Arial", 11))
        info.pack(pady=(0, 8))

        self.status_var = tk.StringVar(value="Estado actual: pendiente")
        status = tk.Label(self, textvariable=self.status_var, font=("Arial", 14, "bold"))
        status.pack(pady=(0, 12))

        frame = tk.Frame(self)
        frame.pack(pady=6)

        self.refresh_btn = tk.Button(frame, text="Actualizar estado", width=20, command=self.refresh_status)
        self.exam_btn = tk.Button(frame, text="Pasar a MODE_EXAM", width=22, command=self.set_exam)
        self.restricted_btn = tk.Button(frame, text="Pasar a MODE_RESTRICTED", width=24, command=self.set_restricted)
        self.normal_btn = tk.Button(frame, text="Pasar a MODE_NORMAL", width=22, command=self.set_normal)

        self.refresh_btn.grid(row=0, column=0, padx=5, pady=5)
        self.exam_btn.grid(row=0, column=1, padx=5, pady=5)
        self.restricted_btn.grid(row=0, column=2, padx=5, pady=5)
        self.normal_btn.grid(row=0, column=3, padx=5, pady=5)

        self.log = tk.Text(self, height=22, wrap="word")
        self.log.pack(fill="both", expand=True, padx=14, pady=14)

    def append_log(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (self.refresh_btn, self.exam_btn, self.restricted_btn, self.normal_btn):
            btn.config(state=state)

    def run_async(self, label: str, func) -> None:
        def worker():
            self.after(0, lambda: self.set_buttons_enabled(False))
            self.after(0, lambda: self.append_log(f"\n=== {label} ==="))
            try:
                func()
                mode = self.client.get_vlan_mode(self.config.network)
                self.after(0, lambda: self.status_var.set(f"Estado actual: {mode}"))
                self.after(0, lambda: self.append_log("Operación completada correctamente."))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Error", str(exc)))
                self.after(0, lambda: self.append_log(f"ERROR: {exc}"))
            finally:
                self.after(0, lambda: self.set_buttons_enabled(True))

        threading.Thread(target=worker, daemon=True).start()

    def refresh_status(self) -> None:
        def op():
            mode = self.client.get_vlan_mode(self.config.network)
            self.after(0, lambda: self.status_var.set(f"Estado actual: {mode}"))
            self.after(0, lambda: self.append_log(f"Estado actual de {self.config.network}: {mode}"))
        self.run_async("Actualizar estado", op)

    def set_exam(self) -> None:
        def op():
            self.client.set_mode_exam(
                network=self.config.network,
                comment=f"MODE_EXAM | VLAN{self.config.vlan_id} | {self.config.vlan_name}",
            )
            removed = self.client.clear_connections_for_network(self.config.network)
            self.after(0, lambda: self.append_log(f"Conexiones eliminadas: {removed}"))
        self.run_async("Cambiar a MODE_EXAM", op)

    def set_restricted(self) -> None:
        def op():
            self.client.set_mode_restricted(
                network=self.config.network,
                comment=f"MODE_RESTRICTED | VLAN{self.config.vlan_id} | {self.config.vlan_name}",
            )
            removed = self.client.clear_connections_for_network(self.config.network)
            self.after(0, lambda: self.append_log(f"Conexiones eliminadas: {removed}"))
        self.run_async("Cambiar a MODE_RESTRICTED", op)

    def set_normal(self) -> None:
        def op():
            self.client.set_mode_normal(self.config.network)
            removed = self.client.clear_connections_for_network(self.config.network)
            self.after(0, lambda: self.append_log(f"Conexiones eliminadas: {removed}"))
        self.run_async("Cambiar a MODE_NORMAL", op)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="App Tkinter para modos de VLAN en MikroTik CCR2216.")
    parser.add_argument("--host", default="10.99.0.1")
    parser.add_argument("--port", type=int, default=7443)
    parser.add_argument("--user", required=True)
    parser.add_argument("--vlan", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--verify-ssl", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    root = tk.Tk()
    root.withdraw()
    password = simpledialog.askstring(
        "Credenciales MikroTik",
        f"Contraseña para {args.user}@{args.host}:",
        show="*",
        parent=root,
    )
    root.destroy()

    if not password:
        return 1

    config = AppConfig(
        host=args.host,
        port=args.port,
        username=args.user,
        password=password,
        vlan_id=args.vlan,
        network=args.network,
        vlan_name=args.name,
        verify_ssl=args.verify_ssl,
    )

    app = VlanModeApp(config)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
