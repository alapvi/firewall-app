"""Backend REST simulado en memoria para probar mikrotik_api.py y
vlan_controller.py sin conexión a un router real.

Solo reimplementa `_request`: toda la lógica de negocio (transiciones,
verificaciones, etc.) sigue siendo la de MikroTikRestClient real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import unquote

from mikrotik_api import MikroTikConnectionError, MikroTikError, MikroTikRestClient

DEFAULT_ALLOW_LISTS = {
    "ALLOW_AI",
    "ALLOW_SEARCH",
    "ALLOW_M365",
    "ALLOW_SIMARRO",
    "ALLOW_ISOS",
    "ALLOW_VIDEOGAME",
    "ALLOW_FULL_INTERNET",
}

# Firma del hook de inyección de fallos: recibe el número de llamada (1-indexado),
# el método HTTP, la ruta y los kwargs, y puede devolver una excepción a lanzar.
OnCallHook = Callable[[int, str, str, dict], Optional[Exception]]


@dataclass
class FakeMikroTikRestClient(MikroTikRestClient):
    entries: list = field(default_factory=list)
    connections: list = field(default_factory=list)
    filter_rules: list = field(default_factory=list)

    def __post_init__(self):
        self._next_id = 1
        self.call_log: list[tuple[int, str, str]] = []
        self.on_call: Optional[OnCallHook] = None

    @classmethod
    def create(cls, entries=None, connections=None) -> "FakeMikroTikRestClient":
        client = cls(host="fake-router", port=0, username="test", password="test")
        client.entries = [dict(e) for e in (entries or [])]
        client.connections = [dict(c) for c in (connections or [])]
        client.filter_rules = [
            {
                ".id": f"*allow-{name}",
                "chain": "forward",
                "action": "accept",
                "src-address-list": name,
                "disabled": "false",
            }
            for name in DEFAULT_ALLOW_LISTS
        ]
        ids = [e.get(".id") for e in client.entries if isinstance(e.get(".id"), str) and e[".id"].startswith("*")]
        numeric = [int(i[1:]) for i in ids if i[1:].isdigit()]
        client._next_id = (max(numeric) + 1) if numeric else 1
        return client

    def seed_membership(self, list_name: str, address: str, comment: str = "seed") -> None:
        """Añade una entrada directamente al backend simulado, evitando pasar por
        la API bajo prueba (útil para preparar SRC_GENERAL o estados iniciales)."""
        self.entries.append(
            {
                ".id": f"*{self._next_id}",
                "list": list_name,
                "address": address,
                "comment": comment,
                "disabled": "false",
            }
        )
        self._next_id += 1

    def fail_at(self, call_number: int, exc: Exception) -> None:
        """Hace que la llamada REST número `call_number` (1-indexada, contando
        todas las peticiones hechas por el cliente) lance `exc`."""

        def hook(n, method, path, kwargs):
            if n == call_number:
                return exc
            return None

        self.on_call = hook

    def _request(self, method: str, path: str, **kwargs) -> Any:
        self._next_id = getattr(self, "_next_id", 1)
        counter = len(self.call_log) + 1
        self.call_log.append((counter, method, path))

        if self.on_call:
            exc = self.on_call(counter, method, path, kwargs)
            if exc is not None:
                raise exc

        if method == "GET" and path == "/ip/firewall/address-list":
            return [dict(e) for e in self.entries]

        if method == "GET" and path == "/ip/firewall/filter":
            return [dict(rule) for rule in self.filter_rules]

        if method == "GET" and path == "/ip/firewall/connection":
            return [dict(c) for c in self.connections]

        if method == "PUT" and path == "/ip/firewall/address-list":
            payload = kwargs.get("json", {})
            entry = {
                ".id": f"*{self._next_id}",
                "list": payload.get("list"),
                "address": payload.get("address"),
                "comment": payload.get("comment", ""),
                "disabled": payload.get("disabled", "false"),
            }
            self._next_id += 1
            self.entries.append(entry)
            return entry

        if method == "DELETE" and path.startswith("/ip/firewall/address-list/"):
            entry_id = unquote(path.rsplit("/", 1)[-1])
            before = len(self.entries)
            self.entries = [e for e in self.entries if e.get(".id") != entry_id]
            if len(self.entries) == before:
                raise MikroTikError(f"Fake backend: no existe la entrada {entry_id}")
            return None

        if method == "DELETE" and path.startswith("/ip/firewall/connection/"):
            entry_id = unquote(path.rsplit("/", 1)[-1])
            before = len(self.connections)
            self.connections = [c for c in self.connections if c.get(".id") != entry_id]
            if len(self.connections) == before:
                raise MikroTikError(f"Fake backend: no existe la conexión {entry_id}")
            return None

        raise MikroTikError(f"Fake backend: ruta no soportada {method} {path}")


def connection_error(message: str = "fallo de red simulado") -> MikroTikConnectionError:
    return MikroTikConnectionError(message)
