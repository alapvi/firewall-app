from __future__ import annotations

import ipaddress
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ALLOW_LIST_NAME = re.compile(r"ALLOW_[A-Za-z0-9_-]+\Z")

# Nombres heredados que el catálogo actual ya no usa (p. ej. renombrado a ALLOW_M365).
# Se declaran de forma explícita: la app solo los detecta y documenta su migración,
# nunca los convierte automáticamente en el nombre nuevo ni borra listas ALLOW_* fuera
# de este catálogo.
LEGACY_ALLOW_LISTS = {
    "ALLOW_MICROSOFT",
}

# Modos especiales mutuamente excluyentes; MODE_NORMAL se representa por su ausencia
# (más la pertenencia a SRC_GENERAL, que la app nunca modifica).
SPECIAL_MODES = ("MODE_EXAM", "MODE_RESTRICTED", "MODE_SELECTIVE")

SRC_GENERAL_LIST = "SRC_GENERAL"


class MikroTikError(RuntimeError):
    pass


class MikroTikConnectionError(MikroTikError):
    """No se pudo hablar con el router (red/timeout), a diferencia de un error HTTP
    del propio REST API. Se usa para mostrar "estado no verificado" en vez de
    afirmar éxito o fallo del cambio solicitado."""


class MikroTikHTTPError(MikroTikError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class ConntrackCleanupError(MikroTikError):
    """Las listas pueden estar aplicadas aunque la limpieza esté incompleta."""

    def __init__(self, message: str, cleared: int = 0):
        super().__init__(message)
        self.cleared = cleared


@dataclass
class MikroTikRestClient:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    verify_ssl: bool = False
    timeout: int = 10
    _session: requests.Session | None = field(default=None, init=False, repr=False)

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}/rest"

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        if self._session is None:
            self._session = requests.Session()
            # El CCR es un destino interno; no heredar proxies del escritorio.
            self._session.trust_env = False
        try:
            response = self._session.request(
                method,
                url,
                auth=(self.username, self.password),
                verify=self.verify_ssl,
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise MikroTikConnectionError(f"No se pudo conectar con MikroTik REST: {exc}") from exc

        if not response.ok:
            body = response.text.strip()
            raise MikroTikHTTPError(response.status_code, f"REST {method} {path} falló: HTTP {response.status_code} {body}")

        if response.text.strip():
            try:
                return response.json()
            except ValueError as exc:
                raise MikroTikError(f"Respuesta JSON no válida en {method} {path}") from exc
        return None

    @staticmethod
    def _table(data: Any, path: str) -> list[dict[str, Any]]:
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise MikroTikError(f"Respuesta de tabla no válida en {path}; estado no verificado")
        return data

    def get_address_list_entries(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/ip/firewall/address-list")
        entries = self._table(data, "/ip/firewall/address-list")
        if any(not isinstance(e.get("list"), str) or not isinstance(e.get("address"), str) for e in entries):
            raise MikroTikError("Address-list incompleta; no se puede verificar el modo")
        return entries

    def find_address_entries(self, list_name: str, address: str) -> list[dict[str, Any]]:
        return [
            e for e in self.get_address_list_entries()
            if e.get("list") == list_name
            and e.get("address") == address
            and str(e.get("disabled", "false")).lower() not in ("true", "yes")
        ]

    def is_member_of(self, list_name: str, address: str) -> bool:
        return bool(self.find_address_entries(list_name, address))

    def add_address_if_missing(self, list_name: str, address: str, comment: str = "") -> bool:
        if self.find_address_entries(list_name, address):
            return False

        payload = {
            "list": list_name,
            "address": address,
            "comment": comment,
            "disabled": "false",
        }

        try:
            self._request("PUT", "/ip/firewall/address-list", json=payload)
        except MikroTikConnectionError:
            # Resultado incierto: la petición pudo aplicarse en el router aunque
            # se perdiera la respuesta. Se relee antes de decidir si repetir, para
            # no crear una segunda entrada duplicada por un simple timeout.
            if self.find_address_entries(list_name, address):
                return True
            raise
        return True

    def remove_address(self, list_name: str, address: str) -> int:
        entries = self.find_address_entries(list_name, address)
        removed = 0
        for entry in entries:
            entry_id = entry.get(".id")
            if not entry_id:
                continue
            safe_id = quote(entry_id, safe="*")
            try:
                self._request("DELETE", f"/ip/firewall/address-list/{safe_id}")
            except MikroTikConnectionError:
                # No repetir una escritura cuyo resultado se desconoce.
                if any(e.get(".id") == entry_id for e in self.get_address_list_entries()):
                    raise
            except MikroTikHTTPError as exc:
                if exc.status_code != 404:
                    raise
                if any(e.get(".id") == entry_id for e in self.get_address_list_entries()):
                    raise
            removed += 1
        return removed

    def _read_special_modes(self, network: str) -> set[str]:
        """Modos especiales (EXAM/RESTRICTED/SELECTIVE) a los que pertenece `network`
        ahora mismo, según la última lectura del router."""
        entries = self.get_address_list_entries()
        return {
            entry.get("list")
            for entry in entries
            if entry.get("list") in SPECIAL_MODES
            and entry.get("address") == network
            and str(entry.get("disabled", "false")).lower() not in ("true", "yes")
        }

    def get_vlan_mode(self, network: str) -> str:
        active_modes = self._read_special_modes(network)

        if len(active_modes) > 1:
            return "ERROR: VLAN presente en varios modos"
        if active_modes:
            return next(iter(active_modes))
        if self.is_member_of(SRC_GENERAL_LIST, network):
            return "MODE_NORMAL"
        return "ERROR: VLAN fuera de SRC_GENERAL y sin modo asignado"

    def get_allow_list_names(self) -> set[str]:
        """Listas opcionales declaradas en reglas forward accept activas."""
        rules = self._table(self._request("GET", "/ip/firewall/filter"), "/ip/firewall/filter")

        return {
            name
            for rule in rules
            if isinstance(rule, dict)
            and rule.get("chain") == "forward"
            and rule.get("action") == "accept"
            and str(rule.get("disabled", "false")).lower() not in ("true", "yes")
            and isinstance((name := rule.get("src-address-list")), str)
            and ALLOW_LIST_NAME.fullmatch(name)
            and name not in LEGACY_ALLOW_LISTS
        }

    def get_optional_allows(self, network: str) -> set[str]:
        entries = self.get_address_list_entries()
        return {
            entry["list"]
            for entry in entries
            if isinstance(entry.get("list"), str)
            and ALLOW_LIST_NAME.fullmatch(entry["list"])
            and entry["list"] not in LEGACY_ALLOW_LISTS
            and entry.get("address") == network
            and str(entry.get("disabled", "false")).lower() not in ("true", "yes")
        }

    def get_legacy_allow_entries(self, network: str) -> set[str]:
        """Detecta listas ALLOW_* heredadas (p. ej. ALLOW_MICROSOFT) para la red
        gestionada. Solo detecta: no las convierte al nombre nuevo ni las borra."""
        entries = self.get_address_list_entries()
        return {
            entry["list"]
            for entry in entries
            if isinstance(entry.get("list"), str)
            and entry["list"] in LEGACY_ALLOW_LISTS
            and entry.get("address") == network
            and str(entry.get("disabled", "false")).lower() not in ("true", "yes")
        }

    def remove_legacy_allow_entries(self, network: str) -> int:
        """Limpieza explícita y opcional de nombres heredados, limitada al catálogo
        LEGACY_ALLOW_LISTS y a la red administrada por esta instancia. No toca
        ninguna otra lista ALLOW_* ni otras redes."""
        return sum(self.remove_address(name, network) for name in LEGACY_ALLOW_LISTS)

    def remove_optional_allows(self, network: str) -> int:
        # Also clear orphaned ALLOW_* memberships whose firewall rule was removed,
        # so recreating that rule later cannot restore an old permission.
        names = {
            entry["list"]
            for entry in self.get_address_list_entries()
            if isinstance(entry.get("list"), str)
            and ALLOW_LIST_NAME.fullmatch(entry["list"])
            and entry["list"] not in LEGACY_ALLOW_LISTS
            and entry.get("address") == network
        }
        return sum(self.remove_address(name, network) for name in names)

    def _apply_restrictive_mode(
        self,
        network: str,
        target_mode: str,
        comment: str = "",
        allow_lists: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        """Transición protegida entre MODE_EXAM/MODE_RESTRICTED/MODE_SELECTIVE.

        Orden elegido (las peticiones REST no son una transacción atómica, cada
        paso puede fallar de forma independiente):
        1. Se validan los argumentos (listas ALLOW_* permitidas) antes de tocar
           nada; una solicitud inválida se rechaza sin ninguna escritura.
        2. Se valida que no exista ya un conflicto de modos (pertenencia simultánea
           a más de un modo especial) antes de tocar nada; ese conflicto inicial se
           reporta y aborta sin modificar entradas.
        3. Si la red no tenía ninguna restricción activa (MODE_NORMAL), se añade
           MODE_EXAM como protección puente antes de cualquier otro cambio, para
           que nunca haya un intervalo sin restricción.
        4. Se añade el modo/las listas ALLOW_* de destino y se verifica releyendo
           el router.
        5. Solo cuando el destino está confirmado se retiran las restricciones
           sobrantes (modo anterior y, si se usó, el puente MODE_EXAM).
        Si cualquier paso falla (incluida la pérdida de conexión), la restricción
        anterior (o el puente) permanece activa: no se amplían permisos por una
        recuperación automática.
        """
        if target_mode not in SPECIAL_MODES:
            raise ValueError(f"Modo destino no soportado: {target_mode}")

        selected: set[str] | None = None
        if target_mode == "MODE_SELECTIVE":
            selected = set(allow_lists or ())
            malformed = {name for name in selected if not isinstance(name, str) or not ALLOW_LIST_NAME.fullmatch(name)}
            if malformed:
                raise ValueError(f"Nombres ALLOW no válidos: {', '.join(sorted(map(str, malformed)))}")
            invalid = selected.difference(self.get_allow_list_names())
            if invalid:
                raise ValueError(f"Listas ALLOW sin regla forward accept activa: {', '.join(sorted(invalid))}")

        initial_modes = self._read_special_modes(network)
        if len(initial_modes) > 1:
            raise MikroTikError(
                "Conflicto de modos detectado antes de iniciar la transición: la red ya "
                f"pertenece a {sorted(initial_modes)}. No se ha modificado ninguna entrada; "
                "resuélvelo manualmente antes de repetir el cambio."
            )
        initial_mode = next(iter(initial_modes), None)

        if initial_mode is None:
            # Sin restricción previa (MODE_NORMAL): se añade el puente antes de seguir.
            self.add_address_if_missing("MODE_EXAM", network, comment)

        if target_mode == "MODE_SELECTIVE":
            self.add_address_if_missing("MODE_SELECTIVE", network, comment)

            current_allows = self.get_optional_allows(network)
            # Primero se retiran los permisos no seleccionados (reduce el alcance)...
            for name in current_allows - selected:
                self.remove_address(name, network)
            # ...y solo después se añaden los nuevos, para no ampliar antes de reducir.
            for name in selected - current_allows:
                self.add_address_if_missing(name, network, comment)

            verified_allows = self.get_optional_allows(network)
            if verified_allows != selected:
                raise MikroTikError(
                    "No se pudieron confirmar los permisos ALLOW_* solicitados: "
                    f"esperado {sorted(selected)}, verificado {sorted(verified_allows)}."
                )
        else:
            self.add_address_if_missing(target_mode, network, comment)
            self.remove_optional_allows(network)

        verified_modes = self._read_special_modes(network)
        if target_mode not in verified_modes:
            raise MikroTikError(
                f"No se pudo verificar la activación de {target_mode}; se conserva la "
                "restricción anterior por seguridad y no se retira ninguna protección."
            )

        # El destino ya está confirmado: ahora sí se pueden retirar las restricciones sobrantes.
        stale_modes = verified_modes - {target_mode}
        for mode in stale_modes:
            self.remove_address(mode, network)

        final_modes = self._read_special_modes(network)
        if final_modes != {target_mode}:
            raise MikroTikError(
                f"Estado final inesperado tras la transición a {target_mode}: {sorted(final_modes)}."
            )

    def set_mode_exam(self, network: str, comment: str = "") -> None:
        self._apply_restrictive_mode(network, "MODE_EXAM", comment=comment)

    def set_mode_restricted(self, network: str, comment: str = "") -> None:
        self._apply_restrictive_mode(network, "MODE_RESTRICTED", comment=comment)

    def set_mode_selective(
        self,
        network: str,
        allow_lists: list[str] | tuple[str, ...] = (),
        comment: str = "",
    ) -> None:
        self._apply_restrictive_mode(network, "MODE_SELECTIVE", comment=comment, allow_lists=allow_lists)

    def set_mode_normal(self, network: str) -> None:
        """Transición protegida hacia MODE_NORMAL.

        Comprueba primero el requisito de pertenencia a SRC_GENERAL (la app nunca
        añade ni retira esa lista): si no se cumple, se aborta sin tocar nada. Solo
        entonces se retiran los permisos opcionales y, al final, la última
        restricción activa (MODE_EXAM/MODE_RESTRICTED/MODE_SELECTIVE).
        """
        initial_modes = self._read_special_modes(network)
        if len(initial_modes) > 1:
            raise MikroTikError(
                "Conflicto de modos detectado antes de iniciar la transición: la red ya "
                f"pertenece a {sorted(initial_modes)}. No se ha modificado ninguna entrada."
            )
        initial_mode = next(iter(initial_modes), None)

        if not self.is_member_of(SRC_GENERAL_LIST, network):
            raise MikroTikError(
                "La red no pertenece a SRC_GENERAL: no se cumple el requisito para volver a "
                "MODE_NORMAL. No se ha modificado ninguna entrada; la restricción actual se "
                "mantiene."
            )

        # Los permisos opcionales se limpian primero...
        self.remove_optional_allows(network)
        # ...y la última restricción se retira al final, una vez comprobado SRC_GENERAL.
        if initial_mode:
            self.remove_address(initial_mode, network)

        final_modes = self._read_special_modes(network)
        if final_modes:
            raise MikroTikError(
                f"Estado final inesperado: la red sigue en {sorted(final_modes)} tras "
                "intentar MODE_NORMAL."
            )
        if not self.is_member_of(SRC_GENERAL_LIST, network):
            raise MikroTikError("SRC_GENERAL ya no contiene la red tras la transición: estado inconsistente.")

    def get_connections(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/ip/firewall/connection", params={
            ".proplist": ".id,protocol,src-address,src-port,dst-address,dst-port,reply-src-address,reply-src-port,reply-dst-address,reply-dst-port"
        })
        return self._table(data, "/ip/firewall/connection")

    @staticmethod
    def _ip_part(value: str | None) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            host, separator, port = value.rpartition(":")
            if separator and port.isdigit():
                try:
                    return str(ipaddress.ip_address(host.strip("[]")))
                except ValueError:
                    pass
        return None

    def _is_rest_connection(self, conn: dict[str, Any]) -> bool:
        # No cortar las sesiones de control al ejecutar la app desde la propia VLAN.
        # Solo se excluye TCP hacia el endpoint REST configurado, no la gestión entera.
        if conn.get("protocol") not in ("tcp", "6", 6):
            return False
        value = conn.get("dst-address", "")
        port = conn.get("dst-port")
        if port is None and isinstance(value, str) and ":" in value:
            port = value.rsplit(":", 1)[1]
        return self._ip_part(value) == self.host and str(port) == str(self.port)

    def clear_connections_for_network(self, network: str, budget_seconds: float = 120) -> int:
        """Borra y verifica la instantánea inicial, con dos intentos como máximo.

        Una conexión que caduca durante DELETE no aborta las demás. Después de
        cada pasada se relee: solo se repiten IDs que continúan perteneciendo a
        la red. No se persigue una tabla vacía (DNS y tráfico permitido se recrean).
        El contador incluye entradas de la instantánea que caducaron por sí solas.
        Esto NO prueba que el firewall bloquee conexiones nuevas o recreadas.
        """
        net = ipaddress.ip_network(network, strict=True)
        if net.version != 4 or net.prefixlen == 0:
            raise ValueError("La red gestionada debe ser IPv4 y distinta de 0.0.0.0/0")
        deadline = time.monotonic() + budget_seconds

        def targets():
            result = set()
            for conn in self.get_connections():
                if not conn.get(".id"):
                    raise MikroTikError("Conntrack sin .id; no se puede verificar la limpieza")
                addresses = [self._ip_part(conn.get(key)) for key in (
                    "src-address", "dst-address", "reply-src-address", "reply-dst-address"
                )]
                if not any(addresses):
                    raise MikroTikError("Conntrack sin direcciones válidas; no se puede verificar la limpieza")
                if any(ip and ipaddress.ip_address(ip) in net for ip in addresses) and not self._is_rest_connection(conn):
                    result.add(conn[".id"])
            return result

        initial = targets()
        pending = initial.copy()
        last_error = ""
        for _ in range(2):
            abort = False
            for entry_id in sorted(pending):
                if time.monotonic() >= deadline:
                    last_error = "Límite de tiempo alcanzado"
                    break
                try:
                    self._request("DELETE", f"/ip/firewall/connection/{quote(entry_id, safe='*')}")
                except MikroTikError as exc:
                    last_error = str(exc)
                    # Una entrada caducada o un fallo aislado no detiene el resto.
                    # Pérdida de red/permisos: releer, pero no insistir con escrituras.
                    if isinstance(exc, MikroTikConnectionError) or (
                        isinstance(exc, MikroTikHTTPError) and exc.status_code in (401, 403)
                    ):
                        abort = True
                        break
            try:
                pending &= targets()
            except MikroTikError as exc:
                raise ConntrackCleanupError(
                    f"No se pudo verificar conntrack: {exc}", len(initial) - len(pending)
                ) from exc
            if not pending:
                return len(initial)
            if abort or time.monotonic() >= deadline:
                break

        raise ConntrackCleanupError(
            f"Limpieza incompleta: quedan {len(pending)} de {len(initial)} conexiones previas. {last_error}",
            len(initial) - len(pending),
        )

