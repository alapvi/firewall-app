#!/usr/bin/env python3
"""
Aplicación Tkinter para cambiar una VLAN entre MODE_NORMAL, MODE_EXAM, MODE_RESTRICTED y MODE_SELECTIVE
en un MikroTik CCR2216 usando RouterOS REST API.

Diseñada para servidores Ubuntu antiguos donde PySide6/Qt puede fallar por CPU sin SSE4.

Uso:
  python3 app.py --host 10.99.0.1 --port 7443 --user firewall-app --vlan 21 --network 10.0.21.0/24 --name "Saló de Actes"
"""

from __future__ import annotations

import argparse
import sys
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
        self.selective_btn = tk.Button(frame, text="Pasar a MODE_SELECTIVE", width=24, command=self.set_selective)
        self.normal_btn = tk.Button(frame, text="Pasar a MODE_NORMAL", width=22, command=self.set_normal)

        allow_frame = tk.LabelFrame(self, text="Permisos opcionales para MODE_SELECTIVE")
        allow_frame.pack(fill="x", padx=14, pady=(2, 8))
        self.allow_frame = allow_frame
        self.allow_vars = {}
        self.update_allow_options(())

        self.refresh_btn.grid(row=0, column=0, padx=5, pady=5)
        self.exam_btn.grid(row=0, column=1, padx=5, pady=5)
        self.restricted_btn.grid(row=0, column=2, padx=5, pady=5)
        self.selective_btn.grid(row=0, column=3, padx=5, pady=5)
        self.normal_btn.grid(row=0, column=4, padx=5, pady=5)

        self.log = tk.Text(self, height=22, wrap="word")
        self.log.pack(fill="both", expand=True, padx=14, pady=14)

    def append_log(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def update_allow_vars(self, active_lists: set[str]) -> None:
        for name, variable in self.allow_vars.items():
            variable.set(name in active_lists)

    def update_allow_options(self, available_lists) -> None:
        for child in self.allow_frame.winfo_children():
            child.destroy()

        self.allow_vars = {}
        for column, name in enumerate(sorted(available_lists)):
            variable = tk.BooleanVar(value=False)
            self.allow_vars[name] = variable
            tk.Checkbutton(self.allow_frame, text=name, variable=variable).grid(
                row=column // 4, column=column % 4, padx=5, pady=4, sticky="w"
            )

    def set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (self.refresh_btn, self.exam_btn, self.restricted_btn, self.selective_btn, self.normal_btn):
            btn.config(state=state)

    def clear_connections_best_effort(self) -> None:
        """
        Intenta eliminar las conexiones activas de la VLAN.
        Si falla, no invalida el cambio de modo realizado.
        """
        try:
            removed = self.client.clear_connections_for_network(self.config.network)
            self.after(
                0,
                lambda: self.append_log(
                    f"Conexiones eliminadas de conntrack: {removed}"
                ),
            )
        except Exception as exc:
            error_message = str(exc)
            self.after(
                0,
                lambda: self.append_log(
                    "ADVERTENCIA: el modo se ha cambiado correctamente, "
                    f"pero no se pudo limpiar conntrack: {error_message}"
                ),
            )

    def run_async(self, label: str, func) -> None:
        def worker():
            self.after(0, lambda: self.set_buttons_enabled(False))
            self.after(0, lambda: self.append_log(f"\n=== {label} ==="))
            try:
                func()
            except Exception as exc:
                error_message = str(exc)
                self.after(0, lambda: messagebox.showerror("Error", error_message))
                self.after(0, lambda: self.append_log(f"ERROR: {error_message}"))
            finally:
                self.after(0, lambda: self.set_buttons_enabled(True))

        threading.Thread(target=worker, daemon=True).start()

    def apply_mode_change(self, expected_mode: str, apply_func, extra_success_lines=()) -> None:
        apply_func()

        # el cambio de address-list se da por bueno solo si el estado verificado coincide
        mode = self.client.get_vlan_mode(self.config.network)
        self.after(0, lambda: self.status_var.set(f"Estado actual: {mode}"))

        if mode != expected_mode:
            raise MikroTikError(
                f"El modo solicitado era {expected_mode} pero el estado verificado es {mode}."
            )

        # los checkbox ALLOW_* solo tienen sentido mientras la VLAN sigue en MODE_SELECTIVE
        if mode != "MODE_SELECTIVE":
            self.after(0, lambda: self.update_allow_vars(set()))

        self.after(0, lambda: self.append_log("Modo cambiado correctamente."))
        self.after(0, lambda: self.append_log(f"Estado verificado: {mode}."))
        for line in extra_success_lines:
            self.after(0, lambda line=line: self.append_log(line))

        # la limpieza de conntrack es una acción posterior: si falla no invalida el cambio de modo
        self.clear_connections_best_effort()

    def refresh_status(self) -> None:
        def op():
            mode = self.client.get_vlan_mode(self.config.network)
            available_lists = self.client.get_allow_list_names()
            active_allows = self.client.get_optional_allows(self.config.network)
            self.after(0, lambda: self.status_var.set(f"Estado actual: {mode}"))
            self.after(0, lambda: self.update_allow_options(available_lists))
            self.after(0, lambda: self.update_allow_vars(active_allows if mode == "MODE_SELECTIVE" else set()))
            self.after(0, lambda: self.append_log(f"Estado actual de {self.config.network}: {mode}"))
        self.run_async("Actualizar estado", op)

    def set_exam(self) -> None:
        def op():
            self.apply_mode_change(
                "MODE_EXAM",
                lambda: self.client.set_mode_exam(
                    network=self.config.network,
                    comment=f"MODE_EXAM | VLAN{self.config.vlan_id} | {self.config.vlan_name}",
                ),
            )
        self.run_async("Cambiar a MODE_EXAM", op)

    def set_restricted(self) -> None:
        def op():
            self.apply_mode_change(
                "MODE_RESTRICTED",
                lambda: self.client.set_mode_restricted(
                    network=self.config.network,
                    comment=f"MODE_RESTRICTED | VLAN{self.config.vlan_id} | {self.config.vlan_name}",
                ),
            )
        self.run_async("Cambiar a MODE_RESTRICTED", op)

    def set_selective(self) -> None:
        selected = [name for name, variable in self.allow_vars.items() if variable.get()]

        def op():
            self.apply_mode_change(
                "MODE_SELECTIVE",
                lambda: self.client.set_mode_selective(
                    network=self.config.network,
                    allow_lists=selected,
                    comment=f"MODE_SELECTIVE | VLAN{self.config.vlan_id} | {self.config.vlan_name}",
                ),
                extra_success_lines=[f"Listas ALLOW activas: {', '.join(selected) or 'ninguna'}"],
            )

        self.run_async("Cambiar a MODE_SELECTIVE", op)

    def set_normal(self) -> None:
        def op():
            self.apply_mode_change("MODE_NORMAL", lambda: self.client.set_mode_normal(self.config.network))
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

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(
            "No se puede iniciar la interfaz gráfica: no hay un display X disponible. "
            "Ejecuta la aplicación desde un escritorio gráfico o conecta por SSH con "
            "reenvío X11 (ssh -X). Detalle: " + str(exc),
            file=sys.stderr,
        )
        return 2

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
