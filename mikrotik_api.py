from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ALLOW_LIST_PREFIX = "ALLOW_"


class MikroTikError(RuntimeError):
    pass


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
            raise MikroTikError(f"No se pudo conectar con MikroTik REST: {exc}") from exc

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
        except MikroTikError:
            self._request("POST", "/ip/firewall/address-list/add", json=payload)
        return True

    def remove_address(self, list_name: str, address: str) -> int:
        entries = self.find_address_entries(list_name, address)
        removed = 0
        for entry in entries:
            entry_id = entry.get(".id")
            if not entry_id:
                continue
            safe_id = quote(entry_id, safe="")
            try:
                self._request("DELETE", f"/ip/firewall/address-list/{safe_id}")
            except MikroTikError:
                self._request("POST", "/ip/firewall/address-list/remove", json={".id": entry_id})
            removed += 1
        return removed

    def get_vlan_mode(self, network: str) -> str:
        in_exam = bool(self.find_address_entries("MODE_EXAM", network))
        in_restricted = bool(self.find_address_entries("MODE_RESTRICTED", network))
        in_selective = bool(self.find_address_entries("MODE_SELECTIVE", network))

        active_modes = sum((in_exam, in_restricted, in_selective))
        if active_modes > 1:
            return "ERROR: VLAN presente en varios modos"
        if in_exam:
            return "MODE_EXAM"
        if in_restricted:
            return "MODE_RESTRICTED"
        if in_selective:
            return "MODE_SELECTIVE"
        return "MODE_NORMAL"

    def get_allow_list_names(self) -> set[str]:
        return {
            entry["list"]
            for entry in self.get_address_list_entries()
            if isinstance(entry.get("list"), str)
            and entry["list"].startswith(ALLOW_LIST_PREFIX)
        }

    def get_optional_allows(self, network: str) -> set[str]:
        entries = self.get_address_list_entries()
        return {
            entry["list"]
            for entry in entries
            if isinstance(entry.get("list"), str)
            and entry["list"].startswith(ALLOW_LIST_PREFIX)
            and entry.get("address") == network
            and str(entry.get("disabled", "false")).lower() not in ("true", "yes")
        }

    def set_mode_exam(self, network: str, comment: str = "") -> None:
        self.remove_address("MODE_RESTRICTED", network)
        self.remove_address("MODE_SELECTIVE", network)
        self.remove_optional_allows(network)
        self.add_address_if_missing("MODE_EXAM", network, comment)

    def set_mode_restricted(self, network: str, comment: str = "") -> None:
        self.remove_address("MODE_EXAM", network)
        self.remove_address("MODE_SELECTIVE", network)
        self.remove_optional_allows(network)
        self.add_address_if_missing("MODE_RESTRICTED", network, comment)

    def set_mode_selective(
        self,
        network: str,
        allow_lists: list[str] | tuple[str, ...] = (),
        comment: str = "",
    ) -> None:
        selected = set(allow_lists)
        invalid = {name for name in selected if not name.startswith(ALLOW_LIST_PREFIX)}
        if invalid:
            raise ValueError(f"Las listas deben empezar por {ALLOW_LIST_PREFIX}: {', '.join(sorted(invalid))}")

        self.remove_address("MODE_EXAM", network)
        self.remove_address("MODE_RESTRICTED", network)
        self.remove_address("MODE_SELECTIVE", network)
        self.remove_optional_allows(network)
        self.add_address_if_missing("MODE_SELECTIVE", network, comment)
        for list_name in selected:
            self.add_address_if_missing(list_name, network, comment)

    def remove_optional_allows(self, network: str) -> int:
        return sum(self.remove_address(list_name, network) for list_name in self.get_allow_list_names())

    def set_mode_normal(self, network: str) -> None:
        self.remove_address("MODE_EXAM", network)
        self.remove_address("MODE_RESTRICTED", network)
        self.remove_address("MODE_SELECTIVE", network)
        self.remove_optional_allows(network)

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
            src = self._ip_part(conn.get("src-address"))
            dst = self._ip_part(conn.get("dst-address"))

            match = False
            for ip_text in (src, dst):
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
            safe_id = quote(entry_id, safe="")
            try:
                self._request("DELETE", f"/ip/firewall/connection/{safe_id}")
            except MikroTikError:
                self._request("POST", "/ip/firewall/connection/remove", json={".id": entry_id})
            removed += 1

        return removed
