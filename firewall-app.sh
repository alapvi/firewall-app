#!/usr/bin/env bash
# Lanzador personalizable por aula. Edita únicamente el bloque siguiente.
set -euo pipefail

# ===== CONFIGURACIÓN DEL AULA: editar una vez en cada equipo =====
CCR_HOST="10.99.0.1"          # IP o nombre del CCR, sin https://
CCR_PORT="7443"              # Puerto HTTPS de la API REST
CCR_USER="firewall-app"      # Usuario de MikroTik; la contraseña se pide al abrir
VLAN_ID="207"               # ID para la ventana y los comentarios
VLAN_NETWORK="10.20.7.0/24"  # IP/subred exacta gestionada en las address-list
VLAN_NAME="2SMXB"           # Nombre descriptivo del aula
VERIFY_SSL="false"          # true: verificar certificado TLS; false: no verificar
# No guardar contraseñas aquí. Revisar siempre VLAN_ID y VLAN_NETWORK juntos.
# ===== FIN DE LA CONFIGURACIÓN DEL AULA =====

show_help() {
    cat <<'HELP'
Uso:
  ./firewall-app.sh            Abre la app con la configuración del aula.
  ./firewall-app.sh [opciones] Sobrescribe valores solo para esta ejecución.

Edita el bloque CONFIGURACIÓN DEL AULA al principio de este fichero una vez.
Opciones para sobrescribir sus valores:
  --user USUARIO    Usuario de MikroTik con permisos REST para la aplicación.
  --vlan ID         Identificador de la VLAN, usado en la ventana y comentarios.
  --network RED     IP o subred IPv4 exacta que se gestionará en las address-list
                    (ejemplo: 10.20.7.0/24). Es el ámbito efectivo de los cambios.
  --name "NOMBRE"   Nombre descriptivo del aula; entre comillas si tiene espacios.

Opcionales:
  --host HOST      IP o nombre del CCR, sin https:// (configurado en CCR_HOST).
  --port PUERTO    Puerto HTTPS REST, entre 1 y 65535 (configurado en CCR_PORT).
  --verify-ssl     Valida el certificado TLS del CCR con las CA de confianza.
                    Si se omite, se utiliza VERIFY_SSL del bloque de configuración.
  --version        Muestra la versión de la aplicación y termina.
  -h, --help       Muestra esta ayuda sin abrir la interfaz ni conectar al CCR.

Ejemplo para 2SMXB (adaptar a cada aula):
  ./firewall-app.sh --host 10.99.0.1 --port 7443 --user firewall-app \
    --vlan 207 --network 10.20.7.0/24 --name "2SMXB"

La contraseña se solicita en una ventana; no se guarda en este fichero.
Requiere un escritorio gráfico (o X11) y el entorno .venv junto al lanzador.
La ayuda funciona sin instalar dependencias. Sin argumentos abre el aula configurada.
--vlan no deduce ni comprueba la red: revisa siempre --network antes de operar.
HELP
    printf '\nConfiguración guardada en este fichero:\n'
    printf '  CCR: %s:%s | Usuario: %s\n  VLAN: %s | Red: %s | Nombre: %s\n  Verificar TLS: %s\n' \
        "$CCR_HOST" "$CCR_PORT" "$CCR_USER" "$VLAN_ID" "$VLAN_NETWORK" "$VLAN_NAME" "$VERIFY_SSL"
}

if [[ $# -eq 1 && ( "$1" == "--help" || "$1" == "-h" ) ]]; then
    show_help
    exit 0
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    printf '%s\n' "Error: falta el entorno virtual $SCRIPT_DIR/.venv." \
        "Desde la carpeta de la aplicación, ejecuta:" \
        "  python3 -m venv .venv" \
        "  .venv/bin/python -m pip install -r requirements.txt" >&2
    exit 1
fi

# Las opciones de la línea de comandos van al final: prevalecen sobre el bloque.
args=(--host "$CCR_HOST" --port "$CCR_PORT" --user "$CCR_USER"
      --vlan "$VLAN_ID" --network "$VLAN_NETWORK" --name "$VLAN_NAME")
case "$VERIFY_SSL" in
    true) args+=(--verify-ssl) ;;
    false) ;;
    *) printf '%s\n' "Error: VERIFY_SSL debe ser true o false." >&2; exit 2 ;;
esac

exec "$PYTHON" "$SCRIPT_DIR/app.py" "${args[@]}" "$@"
