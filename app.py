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

from mikrotik_api import MikroTikConnectionError, MikroTikError, MikroTikRestClient
from vlan_controller import OperationInProgressError, StatusSnapshot, VlanController

APP_VERSION = "1.3.1"


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
        self.controller = VlanController(
            client=self.client,
            network=config.network,
            comment=f"VLAN{config.vlan_id} | {config.vlan_name}",
        )

        # espejo local de controller.current_mode: los checkbox ALLOW_* solo se
        # habilitan cuando vale "MODE_SELECTIVE" y el estado ha podido verificarse
        self.current_mode: str | None = None

        self.title(f"MikroTik VLAN Modes v{APP_VERSION} - VLAN {config.vlan_id}")
        self.minsize(760, 480)
        self.resizable(True, True)
        self._fit_to_screen()

        self._build_ui()
        self.refresh_status()

    def _fit_to_screen(self) -> None:
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        width = max(760, min(950, int(screen_width * 0.8)))
        height = max(480, min(680, int(screen_height * 0.8)))
        x = max((screen_width - width) // 2, 0)
        y = max((screen_height - height) // 2, 0)

        self.geometry(f"{width}x{height}+{x}+{y}")

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
        self.legacy_btn = tk.Button(
            frame, text="Eliminar ALLOW_MICROSOFT heredada", width=28, command=self.migrate_legacy_allows
        )

        allow_frame = tk.LabelFrame(self, text="Permisos opcionales para MODE_SELECTIVE")
        allow_frame.pack(fill="x", padx=14, pady=(2, 8))
        self.allow_frame = allow_frame
        self.allow_vars = {}
        self.allow_checkbuttons = []
        self.legacy_allows: set[str] = set()
        self.update_allow_options(())

        self.refresh_btn.grid(row=0, column=0, padx=5, pady=5)
        self.exam_btn.grid(row=0, column=1, padx=5, pady=5)
        self.restricted_btn.grid(row=0, column=2, padx=5, pady=5)
        self.selective_btn.grid(row=0, column=3, padx=5, pady=5)
        self.normal_btn.grid(row=0, column=4, padx=5, pady=5)
        self.legacy_btn.grid(row=1, column=0, columnspan=5, padx=5, pady=(0, 5))

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

        allow_state = "normal" if self.current_mode == "MODE_SELECTIVE" else "disabled"
        self.allow_vars = {}
        self.allow_checkbuttons = []
        for column, name in enumerate(sorted(available_lists)):
            variable = tk.BooleanVar(value=False)
            self.allow_vars[name] = variable
            checkbutton = tk.Checkbutton(
                self.allow_frame,
                text=name,
                variable=variable,
                state=allow_state,
                command=lambda name=name: self.toggle_allow_list(name),
            )
            checkbutton.grid(row=column // 4, column=column % 4, padx=5, pady=4, sticky="w")
            self.allow_checkbuttons.append(checkbutton)

    def set_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (
            self.refresh_btn,
            self.exam_btn,
            self.restricted_btn,
            self.selective_btn,
            self.normal_btn,
            self.legacy_btn,
        ):
            btn.config(state=state)

        allow_state = "normal" if enabled and self.current_mode == "MODE_SELECTIVE" else "disabled"
        for checkbutton in self.allow_checkbuttons:
            checkbutton.config(state=allow_state)

    def _show_unknown_state(self) -> None:
        # Estado no verificado: no se afirma éxito ni rollback, y las casillas
        # dejan de presentarse como confirmadas hasta la próxima lectura correcta.
        self.current_mode = None
        self.status_var.set("Estado actual: DESCONOCIDO (no verificado)")
        for checkbutton in self.allow_checkbuttons:
            checkbutton.config(state="disabled")

    def _apply_snapshot(self, snapshot: StatusSnapshot) -> None:
        self.current_mode = snapshot.mode
        self.status_var.set(f"Estado actual: {snapshot.mode}")
        self.update_allow_vars(snapshot.active_allows)
        allow_state = "normal" if snapshot.mode == "MODE_SELECTIVE" else "disabled"
        for checkbutton in self.allow_checkbuttons:
            checkbutton.config(state=allow_state)

        self.legacy_allows = snapshot.legacy_allows
        if snapshot.legacy_allows:
            self.append_log(
                "AVISO: listas ALLOW_* heredadas detectadas para esta red: "
                f"{', '.join(sorted(snapshot.legacy_allows))}. No se migran automáticamente; "
                "usa 'Eliminar ALLOW_MICROSOFT heredada' o revisa el README."
            )

    def clear_connections_best_effort(self) -> None:
        """
        Intenta eliminar las conexiones activas de la VLAN.
        Si falla, no invalida el cambio de modo realizado. Si el firewall acepta
        conexiones ya establecidas antes de evaluar el modo/las listas, esta
        limpieza es la única forma de forzar el corte de sesiones abiertas
        previamente: las listas de address-list por sí solas no lo garantizan.
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

    def run_async(self, label: str, func, on_busy=None) -> None:
        try:
            self.controller.begin_operation()
        except OperationInProgressError as exc:
            if on_busy:
                on_busy()
            messagebox.showwarning("Operación en curso", str(exc))
            return

        def worker():
            self.after(0, lambda: self.set_buttons_enabled(False))
            self.after(0, lambda: self.append_log(f"\n=== {label} ==="))
            try:
                func()
            except Exception as exc:
                self._handle_failure(exc)
            finally:
                self.controller.end_operation()
                self.after(0, lambda: self.set_buttons_enabled(True))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_failure(self, exc: Exception) -> None:
        error_message = str(exc)
        self.after(0, lambda: self.append_log(f"ERROR: {error_message}"))

        if isinstance(exc, MikroTikConnectionError):
            # Se perdió la conexión: no se puede verificar el resultado, así que no
            # se afirma éxito ni rollback del cambio solicitado.
            self.after(
                0,
                lambda: self.append_log(
                    "Estado no verificado: se perdió la conexión con el router antes de "
                    "poder confirmar el resultado."
                ),
            )
            self.after(0, self._show_unknown_state)
            self.after(0, lambda: messagebox.showerror("Sin conexión", error_message))
            return

        self.after(0, lambda: messagebox.showerror("Error", error_message))

        # Se intenta recuperar el estado real tras el error, cuando sea posible.
        try:
            snapshot = self.controller.refresh_status()
        except MikroTikError:
            # Incluye tanto la pérdida de conexión como cualquier error REST (p. ej.
            # HTTP 403) que impida confirmar el estado: en ambos casos no se puede
            # verificar, así que se muestra como desconocido en vez de dejar visible
            # un estado antiguo.
            self.after(
                0,
                lambda: self.append_log(
                    "No se pudo confirmar el estado real tras el error (estado no verificado)."
                ),
            )
            self.after(0, self._show_unknown_state)
            return

        self.after(0, lambda: self._apply_snapshot(snapshot))
        self.after(0, lambda: self.append_log(f"Estado real confirmado tras el error: {snapshot.mode}"))

    def refresh_status(self) -> None:
        def op():
            available_lists = self.client.get_allow_list_names()
            snapshot = self.controller.refresh_status()
            self.after(0, lambda: self.update_allow_options(available_lists))
            self.after(0, lambda: self._apply_snapshot(snapshot))
            self.after(0, lambda: self.append_log(f"Estado actual de {self.config.network}: {snapshot.mode}"))
        self.run_async("Actualizar estado", op)

    def toggle_allow_list(self, list_name: str) -> None:
        # el Checkbutton ya cambió su valor antes de invocar este callback
        want_enabled = self.allow_vars[list_name].get()

        def revert_checkbox():
            self.allow_vars[list_name].set(not want_enabled)

        def op():
            result = self.controller.toggle_allow(list_name, want_enabled)

            self.after(0, lambda: self.update_allow_vars(result.active_allows))

            if not result.changed:
                self.after(
                    0,
                    lambda: self.append_log(
                        f"{list_name}: sin cambios (el estado ya coincidía con el solicitado)."
                    ),
                )
                return

            verb = "añadida" if result.active else "eliminada"
            self.after(
                0,
                lambda: self.append_log(f"{list_name}: entrada {verb}. Estado verificado en el router."),
            )

            if result.conntrack_error:
                self.after(
                    0,
                    lambda: self.append_log(
                        "ADVERTENCIA: el permiso se ha actualizado en las listas, pero no se pudo "
                        f"limpiar conntrack: {result.conntrack_error}. Las conexiones ya existentes "
                        "podrían seguir activas aunque la lista ya refleje el cambio."
                    ),
                )
            elif result.conntrack_cleared is not None:
                self.after(
                    0,
                    lambda: self.append_log(f"Conexiones eliminadas de conntrack: {result.conntrack_cleared}"),
                )

        self.run_async(f"Actualizar {list_name}", op, on_busy=revert_checkbox)

    def migrate_legacy_allows(self) -> None:
        if not self.legacy_allows:
            messagebox.showinfo(
                "Sin entradas heredadas",
                "No se han detectado entradas ALLOW_MICROSOFT heredadas para esta red.",
            )
            return

        if not messagebox.askyesno(
            "Eliminar entradas heredadas",
            "Se eliminarán las entradas heredadas "
            f"({', '.join(sorted(self.legacy_allows))}) de esta red exclusivamente. "
            "No se crea ninguna entrada nueva ni se toca ALLOW_M365. ¿Continuar?",
        ):
            return

        def op():
            removed = self.client.remove_legacy_allow_entries(self.config.network)
            self.after(0, lambda: self.append_log(f"Entradas heredadas eliminadas: {removed}"))
            snapshot = self.controller.refresh_status()
            self.after(0, lambda: self._apply_snapshot(snapshot))

        self.run_async("Eliminar listas heredadas", op)

    def confirm_mode_change(self, mode_label: str) -> bool:
        return messagebox.askyesno(
            "Confirmar cambio de modo",
            f"¿Seguro que quieres cambiar la VLAN {self.config.vlan_id} ({self.config.network}) "
            f"a {mode_label}?",
        )

    def apply_mode_change(self, target_mode: str, allow_lists: tuple[str, ...] = (), extra_success_lines=()) -> None:
        result = self.controller.set_mode(target_mode, allow_lists=allow_lists)

        self.after(
            0,
            lambda: self._apply_snapshot(
                StatusSnapshot(
                    mode=result.mode,
                    active_allows=result.active_allows,
                    legacy_allows=self.legacy_allows,
                    verified=True,
                )
            ),
        )
        self.after(0, lambda: self.append_log("Modo cambiado correctamente."))
        self.after(0, lambda: self.append_log(f"Estado verificado: {result.mode}."))
        for line in extra_success_lines:
            self.after(0, lambda line=line: self.append_log(line))

        # La limpieza de conntrack es una acción posterior best-effort: si falla no
        # invalida el cambio de modo ya confirmado por la lectura anterior.
        self.clear_connections_best_effort()

    def set_exam(self) -> None:
        if not self.confirm_mode_change("MODE_EXAM"):
            return

        def op():
            self.apply_mode_change("MODE_EXAM")
        self.run_async("Cambiar a MODE_EXAM", op)

    def set_restricted(self) -> None:
        if not self.confirm_mode_change("MODE_RESTRICTED"):
            return

        def op():
            self.apply_mode_change("MODE_RESTRICTED")
        self.run_async("Cambiar a MODE_RESTRICTED", op)

    def set_selective(self) -> None:
        selected = tuple(name for name, variable in self.allow_vars.items() if variable.get())

        allow_summary = ', '.join(sorted(selected)) or 'ninguna lista ALLOW_*'
        if not messagebox.askyesno(
            "Confirmar cambio de modo",
            f"¿Seguro que quieres cambiar la VLAN {self.config.vlan_id} ({self.config.network}) "
            f"a MODE_SELECTIVE con {allow_summary}?",
        ):
            return

        def op():
            self.apply_mode_change(
                "MODE_SELECTIVE",
                allow_lists=selected,
                extra_success_lines=[f"Listas ALLOW activas: {', '.join(selected) or 'ninguna'}"],
            )

        self.run_async("Cambiar a MODE_SELECTIVE", op)

    def set_normal(self) -> None:
        if not self.confirm_mode_change("MODE_NORMAL"):
            return

        def op():
            self.apply_mode_change("MODE_NORMAL")
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
