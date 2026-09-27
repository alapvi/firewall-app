"""Lógica de orquestación independiente de Tkinter.

Se separa de app.py para poder probarla con un backend REST simulado, sin
necesidad de un display gráfico ni de un router real. VlanModeApp (Tkinter)
es una capa fina sobre VlanController: solo se encarga de pintar la interfaz
y de despachar estas llamadas en un hilo de trabajo.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from mikrotik_api import MikroTikError, MikroTikRestClient


class OperationInProgressError(RuntimeError):
    """Ya hay una operación de escritura en curso en esta misma instancia.

    No implica que otra instancia de la app o WinBox no puedan estar
    modificando el router al mismo tiempo: el bloqueo es solo local.
    """


@dataclass
class StatusSnapshot:
    mode: str | None
    active_allows: set[str]
    legacy_allows: set[str]
    verified: bool


@dataclass
class ToggleResult:
    list_name: str
    changed: bool
    active: bool
    fulfilled: bool
    active_allows: set[str]
    verified: bool
    conntrack_cleared: int | None = None
    conntrack_error: str | None = None


@dataclass
class TransitionResult:
    mode: str
    active_allows: set[str] = field(default_factory=set)
    verified: bool = True


class VlanController:
    """Mantiene el estado leído del router y serializa las operaciones de
    escritura de esta instancia mediante un lock no bloqueante."""

    def __init__(self, client: MikroTikRestClient, network: str, comment: str):
        self.client = client
        self.network = network
        self.comment = comment
        self._lock = threading.Lock()

        self.current_mode: str | None = None
        self.current_allows: set[str] = set()
        self.status_known = False

    # -- control de concurrencia -------------------------------------------------
    def begin_operation(self) -> None:
        if not self._lock.acquire(blocking=False):
            raise OperationInProgressError(
                "Ya hay una operación en curso en esta instancia; espera a que termine."
            )

    def end_operation(self) -> None:
        self._lock.release()

    # -- lectura de estado ---------------------------------------------------
    def refresh_status(self) -> StatusSnapshot:
        try:
            mode = self.client.get_vlan_mode(self.network)
            active_allows = (
                self.client.get_optional_allows(self.network) if mode == "MODE_SELECTIVE" else set()
            )
            legacy = self.client.get_legacy_allow_entries(self.network)
        except MikroTikError:
            # Incluye tanto la pérdida de conexión como cualquier error REST (p. ej.
            # HTTP 403): en ambos casos no se puede confirmar el estado.
            self.status_known = False
            self.current_mode = None
            self.current_allows = set()
            raise

        self.current_mode = mode
        self.current_allows = active_allows
        self.status_known = True
        return StatusSnapshot(mode=mode, active_allows=active_allows, legacy_allows=legacy, verified=True)

    def mark_status_unknown(self) -> None:
        self.status_known = False
        self.current_mode = None
        self.current_allows = set()

    # -- cambios de modo ------------------------------------------------------
    def set_mode(self, target_mode: str, allow_lists: tuple[str, ...] = ()) -> TransitionResult:
        if target_mode == "MODE_NORMAL":
            self.client.set_mode_normal(self.network)
        elif target_mode == "MODE_EXAM":
            self.client.set_mode_exam(self.network, comment=self.comment)
        elif target_mode == "MODE_RESTRICTED":
            self.client.set_mode_restricted(self.network, comment=self.comment)
        elif target_mode == "MODE_SELECTIVE":
            self.client.set_mode_selective(self.network, allow_lists=allow_lists, comment=self.comment)
        else:
            raise ValueError(f"Modo desconocido: {target_mode}")

        # Verificación independiente de la que ya hace la propia transición
        # (defensa en profundidad): si el router no responde aquí, se propaga
        # MikroTikConnectionError y el llamador debe mostrar "estado no verificado".
        mode = self.client.get_vlan_mode(self.network)
        self.current_mode = mode
        if mode != target_mode:
            raise MikroTikError(
                f"El modo solicitado era {target_mode} pero el estado verificado es {mode}."
            )

        active_allows = self.client.get_optional_allows(self.network) if mode == "MODE_SELECTIVE" else set()
        self.current_allows = active_allows
        self.status_known = True
        return TransitionResult(mode=mode, active_allows=active_allows, verified=True)

    # -- casillas ALLOW_* en MODE_SELECTIVE -----------------------------------
    def toggle_allow(self, list_name: str, want_enabled: bool) -> ToggleResult:
        mode = self.client.get_vlan_mode(self.network)
        self.current_mode = mode
        if mode != "MODE_SELECTIVE":
            raise MikroTikError(
                "Los permisos ALLOW_* solo se pueden aplicar mientras la VLAN está en "
                f"MODE_SELECTIVE (estado actual: {mode})."
            )

        if want_enabled:
            changed = self.client.add_address_if_missing(list_name, self.network, comment=self.comment)
        else:
            changed = self.client.remove_address(list_name, self.network) > 0

        # Se vuelve a consultar el router: la casilla se sincroniza con lo leído,
        # no con lo que se pidió.
        active_allows = self.client.get_optional_allows(self.network)
        self.current_allows = active_allows
        active = list_name in active_allows
        fulfilled = active == want_enabled

        result = ToggleResult(
            list_name=list_name,
            changed=changed,
            active=active,
            fulfilled=fulfilled,
            active_allows=active_allows,
            verified=True,
        )

        # La limpieza de conntrack solo tiene sentido si hubo un cambio efectivo Y
        # el estado verificado coincide con lo pedido; es especialmente relevante
        # al revocar un permiso. Un fallo de conntrack aquí no debe revertir la
        # lista ni anunciarse como si el corte de tráfico ya existente hubiera sido
        # completamente efectivo.
        if changed and fulfilled:
            try:
                result.conntrack_cleared = self.client.clear_connections_for_network(self.network)
            except MikroTikError as exc:
                result.conntrack_error = str(exc)

        if not fulfilled:
            # Se conserva el estado realmente leído (current_allows ya actualizado)
            # pero se comunica explícitamente que lo solicitado no se ha conseguido.
            raise MikroTikError(
                f"No se pudo confirmar el cambio de {list_name}: se pidió "
                f"{'activar' if want_enabled else 'revocar'} pero el estado verificado en "
                f"el router es {'activo' if active else 'inactivo'}."
            )

        return result
