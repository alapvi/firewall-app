# MikroTik VLAN Modes App
Aplicación en **Python + Tkinter** para cambiar una VLAN concreta de un **MikroTik CCR2216 / RouterOS** entre tres modos de firewall:

- `MODE_NORMAL`
- `MODE_EXAM`
- `MODE_RESTRICTED`

La aplicación está pensada para entornos educativos donde se necesita cambiar rápidamente la política de acceso de una VLAN/aula, por ejemplo durante un examen, sin tener que entrar manualmente al firewall del MikroTik.

## Qué hace

La app se conecta al CCR2216 mediante **RouterOS REST API** sobre HTTPS y modifica las listas de direcciones del firewall:

- `MODE_EXAM`
- `MODE_RESTRICTED`

El modo normal no necesita una entrada explícita. Una VLAN está en `MODE_NORMAL` cuando **no aparece** ni en `MODE_EXAM` ni en `MODE_RESTRICTED`.

## Funcionamiento de los modos

### MODE_NORMAL

Es el modo por defecto.

En la configuración actual del CCR2216:

- La VLAN no aparece en `MODE_EXAM`.
- La VLAN no aparece en `MODE_RESTRICTED`.
- Las VLANs de `SRC_GENERAL` tienen salida a Internet.
- Las VLANs de `SRC_GENERAL` solo pueden acceder a:
  - `SRC_SERVIDORES_PROXMOX`
  - `SRC_RED_SERVICIOS`
- Se bloquea el acceso entre VLANs internas no autorizadas.

### MODE_EXAM

Modo examen.

La aplicación:

1. Elimina la red de `MODE_RESTRICTED`, si existía.
2. Añade la red a `MODE_EXAM`.
3. Limpia conexiones activas de esa red.
4. Verifica el estado final.

En el CCR2216, `MODE_EXAM` permite únicamente:

- DNS Conselleria.
- Identidad digital `idGVA`.
- Aules/GVA.

Todo lo demás queda bloqueado.

### MODE_RESTRICTED

Modo restringido.

La aplicación:

1. Elimina la red de `MODE_EXAM`, si existía.
2. Añade la red a `MODE_RESTRICTED`.
3. Limpia conexiones activas de esa red.
4. Verifica el estado final.

En el CCR2216, `MODE_RESTRICTED` permite:

- DNS Conselleria.
- Identidad digital `idGVA`.
- Aules/GVA.
- Microsoft 365.
- Herramientas de IA autorizadas.
- Buscadores autorizados.
- Servicios Simarro.

Todo lo demás queda bloqueado.

## Por qué la app se parametriza por VLAN

La aplicación se lanza para una VLAN concreta mediante parámetros de línea de comandos.

Ejemplo:

```bash
python3 app.py \
  --host 10.99.0.1 \
  --port 7443 \
  --user firewall-app \
  --vlan 21 \
  --network 10.0.21.0/24 \
  --name "Salo de Actes"
```

Esto evita que el usuario seleccione por error otra VLAN desde un desplegable.

## Requisitos

### En Ubuntu/Debian

Instalar Python, Tkinter y herramientas básicas:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-tk unzip
```

## Instalación de la aplicación

Clonar el repositorio:

```bash
git clone https://github.com/alapvi/firewall-app.git
cd firewall-app
```
Crear entorno virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
```
Instalar dependencias:

```bash
pip install -r requirements.txt
```

## Uso

Ejemplo para VLAN21 / Saló de Actes:

```bash
source .venv/bin/activate

python3 app.py \
  --host 10.99.0.1 \
  --port 7443 \
  --user firewall-app \
  --vlan 21 \
  --network 10.0.21.0/24 \
  --name "Salo de Actes"
```

Al iniciar, la app pide la contraseña del usuario MikroTik.

La ventana muestra:

- CCR destino.
- VLAN.
- Nombre.
- Red.
- Estado actual:
  - `MODE_NORMAL`
  - `MODE_EXAM`
  - `MODE_RESTRICTED`

Botones disponibles:

- `Actualizar estado`
- `Pasar a MODE_EXAM`
- `Pasar a MODE_RESTRICTED`
- `Pasar a MODE_NORMAL`

## Lanzador por VLAN

Se puede crear un script por aula/VLAN para evitar errores.

Ejemplo `modo_salo.sh`:

```bash
#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
python3 app.py --host 10.99.0.1 --port 7443 --user firewall-app --vlan 21 --network 10.0.21.0/24 --name "Salo de Actes"
```

Dar permisos:

```bash
chmod +x modo_salo.sh
```

Ejecutar:

```bash
./modo_salo.sh
```
## Estructura del proyecto

```text
.
├── app.py
├── mikrotik_api.py
├── requirements.txt
├── modo_salo.sh
└── README.md
```

### app.py

Interfaz gráfica Tkinter.

Recibe los parámetros de VLAN, solicita la contraseña y permite cambiar entre los tres modos.

### mikrotik_api.py

Cliente REST para RouterOS.

Funciones principales:

- Leer `address-list`.
- Añadir una red a `MODE_EXAM`.
- Añadir una red a `MODE_RESTRICTED`.
- Eliminar una red de los modos.
- Limpiar conexiones activas relacionadas con la red de la VLAN.

### requirements.txt

Dependencias Python:

```text
requests
urllib3
```

Tkinter se instala desde paquetes del sistema con `python3-tk`.

## Flujo recomendado de operación

1. Ejecutar el lanzador de la VLAN correspondiente.
2. Comprobar el estado actual.
3. Pulsar el modo deseado.
4. Verificar que la app confirma la operación.

