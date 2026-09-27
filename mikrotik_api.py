from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# RouterOS no tiene listas vacías: una address-list solo existe mediante sus entradas,
# por eso el catálogo de listas opcionales se declara aquí en vez de descubrirse por API.
OPTIONAL_ALLOW_LISTS = {
    "ALLOW_AI",
    "ALLOW_SEARCH",
    "ALLOW_M365",
    "ALLOW_SIMARRO",
    "ALLOW_ISOS",
    "ALLOW_VIDEOGAME",
    "ALLOW_FULL_INTERNET",
}

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


@dataclass
class MikroTikRestClient:
    host: str
    port: int
    username: str
    password: str
    verify_ssl: bool = False
    timeout: int = 10

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}/rest"

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
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
            raise MikroTikError(f"REST {method} {path} falló: HTTP {response.status_code} {body}")

        if response.text.strip():
            try:
                return response.json()
            except ValueError:
                return response.text
        return None

    def get_address_list_entries(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/ip/firewall/address-list")
        return data if isinstance(data, list) else []

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
        except MikroTikError:
            # Error propio del REST API (p. ej. PUT no soportado): reintento seguro.
            self._request("POST", "/ip/firewall/address-list/add", json=payload)
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
            except MikroTikError:
                self._request("POST", "/ip/firewall/address-list/remove", json={".id": entry_id})
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
        return set(OPTIONAL_ALLOW_LISTS)

    def get_optional_allows(self, network: str) -> set[str]:
        entries = self.get_address_list_entries()
        return {
            entry["list"]
            for entry in entries
            if isinstance(entry.get("list"), str)
            and entry["list"] in OPTIONAL_ALLOW_LISTS
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
        return sum(self.remove_address(list_name, network) for list_name in self.get_allow_list_names())

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
            invalid = selected.difference(OPTIONAL_ALLOW_LISTS)
            if invalid:
                raise ValueError(f"Listas ALLOW no permitidas: {', '.join(sorted(invalid))}")

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
        data = self._request("GET", "/ip/firewall/connection")
        return data if isinstance(data, list) else []

    @staticmethod
    def _ip_part(value: str | None) -> str | None:
        if not value:
            return None
        return value.split(":", 1)[0]

    def clear_connections_for_network(self, network: str) -> int:
        net = ipaddress.ip_network(network, strict=False)
        to_remove: list[str] = []

        for conn in self.get_connections():
            addresses = (
                self._ip_part(conn.get("src-address")),
                self._ip_part(conn.get("dst-address")),
                self._ip_part(conn.get("reply-src-address")),
                self._ip_part(conn.get("reply-dst-address")),
            )

            match = False
            for ip_text in addresses:
                if not ip_text:
                    continue
                try:
                    if ipaddress.ip_address(ip_text) in net:
                        match = True
                        break
                except ValueError:
                    continue

            if match and conn.get(".id"):
                to_remove.append(conn[".id"])

        removed = 0
        for entry_id in to_remove:
            safe_id = quote(entry_id, safe="*")
            self._request("DELETE", f"/ip/firewall/connection/{safe_id}")
            removed += 1

        return removed
