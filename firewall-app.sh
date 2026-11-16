#!/usr/bin/env bash
# Lanzador genérico. Los parámetros se pasan a app.py sin reinterpretarlos.
set -euo pipefail

show_help() {
    cat <<'HELP'
Uso:
  ./firewall-app.sh --user USUARIO --vlan ID --network RED --name "NOMBRE" [opciones]

Obligatorios:
  --user USUARIO    Usuario de MikroTik con permisos REST para la aplicación.
  --vlan ID         Identificador de la VLAN, usado en la ventana y comentarios.
  --network RED     IP o subred IPv4 exacta que se gestionará en las address-list
                    (ejemplo: 10.20.7.0/24). Es el ámbito efectivo de los cambios.
  --name "NOMBRE"   Nombre descriptivo del aula; entre comillas si tiene espacios.

Opcionales:
  --host HOST      IP o nombre del CCR, sin https:// (por defecto: 10.99.0.1).
  --port PUERTO    Puerto HTTPS REST, entre 1 y 65535 (por defecto: 7443).
  --verify-ssl     Valida el certificado TLS del CCR con las CA de confianza.
                    Si se omite, no se verifica el certificado.
  --version        Muestra la versión de la aplicación y termina.
  -h, --help       Muestra esta ayuda sin abrir la interfaz ni conectar al CCR.

Ejemplo para 2SMXB (adaptar a cada aula):
  ./firewall-app.sh --host 10.99.0.1 --port 7443 --user firewall-app \
    --vlan 207 --network 10.20.7.0/24 --name "2SMXB"

La contraseña se solicita en una ventana; no se guarda en este fichero.
Requiere un escritorio gráfico (o X11) y el entorno .venv junto al lanzador.
La ayuda funciona sin instalar dependencias. Sin argumentos solo muestra ayuda.
--vlan no deduce ni comprueba la red: revisa siempre --network antes de operar.
HELP
}

if [[ $# -eq 0 ]]; then
    show_help
    exit 0
fi
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

exec "$PYTHON" "$SCRIPT_DIR/app.py" "$@"
