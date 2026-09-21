# MikroTik VLAN Modes App - Tkinter

La aplicación permite cambiar una VLAN entre `MODE_NORMAL`, `MODE_EXAM`,
`MODE_RESTRICTED` y `MODE_SELECTIVE`.

## Versión 1.1.0

- Añadido `MODE_SELECTIVE`.
- Descubrimiento dinámico de todas las listas `ALLOW_*` disponibles en MikroTik.
- Selección de permisos opcionales desde la interfaz Tkinter.
- Limpieza automática de las listas `ALLOW_*` al cambiar a otro modo.
- Refresco de las listas disponibles mediante "Actualizar estado".

En `MODE_SELECTIVE`, la red se añade siempre a `MODE_SELECTIVE` y, de forma
opcional, a las listas disponibles cuyo nombre empieza por `ALLOW_`. La
aplicación descubre esas listas consultando `/ip/firewall/address-list`, por lo
que una nueva lista aparecerá al pulsar "Actualizar estado" siempre que tenga
alguna entrada. Las reglas del firewall deben interpretar esas listas como
permisos adicionales para una red que ya pertenece a `MODE_SELECTIVE`.

Las listas opcionales conocidas actualmente son `ALLOW_AI`, `ALLOW_SEARCH`,
`ALLOW_M365`, `ALLOW_SIMARRO`, `ALLOW_ISOS`, `ALLOW_VIDEOGAME` y
`ALLOW_FULL_INTERNET`, aunque la aplicación también admite cualquier nueva
lista cuyo nombre empiece por `ALLOW_`.

### Flujo de modos

```text
MODE_EXAM
	-> MODE_RESTRICTED
	-> MODE_SELECTIVE
		 - base: DNS Conselleria
		 - base: idGVA
		 - base: Aules/GVA
		 - permisos opcionales: ALLOW_*
		 - resto: DROP
	-> MODE_NORMAL
```

Las reglas base de `MODE_SELECTIVE` las proporciona la configuración del
firewall. La aplicación solo añade o elimina la red de la VLAN en
`MODE_SELECTIVE` y en las listas `ALLOW_*` que se seleccionen desde la
interfaz.

## Funcionamiento de los modos

Las reglas `forward` de MikroTik consultan la lista de direcciones a la que
pertenece la red de la VLAN. En todos los modos se aceptan primero las
conexiones ya establecidas o relacionadas; el resto del tráfico se evalúa
según el modo activo.

### `MODE_EXAM`

La red pertenece a `MODE_EXAM`. Se permiten los servicios necesarios para el
entorno de examen:

- DNS de Conselleria por UDP y TCP en el puerto 53.
- `idGVA`.
- `Aules/GVA`.
- Acceso al CCR `10.99.0.1`.

El resto del tráfico se descarta (`DROP`).

### `MODE_RESTRICTED`

La red pertenece a `MODE_RESTRICTED`. Mantiene los permisos base de examen y
añade los servicios definidos para el modo restringido:

- DNS de Conselleria por UDP y TCP en el puerto 53.
- `idGVA`.
- `Aules/GVA`.
- `Microsoft365`.
- Servicios de IA y buscadores.
- Servicios de Simarro.
- Acceso al CCR `10.99.0.1`.

El resto del tráfico se descarta (`DROP`).

### `MODE_SELECTIVE`

La red pertenece a `MODE_SELECTIVE` y recibe únicamente la base común:

- DNS de Conselleria por UDP y TCP en el puerto 53.
- `idGVA`.
- `Aules/GVA`.

Desde la aplicación se pueden seleccionar permisos adicionales mediante las
listas `ALLOW_*`. Cada lista seleccionada recibe la red de la VLAN como una
entrada y amplía los destinos permitidos por las reglas del firewall. El resto
del tráfico se descarta (`DROP`).

### `MODE_NORMAL`

La red deja de pertenecer a `MODE_EXAM`, `MODE_RESTRICTED` y
`MODE_SELECTIVE`, y también se eliminan sus entradas de las listas `ALLOW_*`.
Vuelve al comportamiento normal basado en `SRC_GENERAL`, con acceso a los
servicios habituales como Proxmox, Red Servicios e Internet. El tráfico hacia
otras redes internas que no esté permitido se bloquea (`DROP`).

Versión sin Qt/PySide6, pensada para servidores Ubuntu antiguos donde Qt falla por CPU sin SSSE3/SSE4.

## Instalar en Ubuntu

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-tk unzip

cd /opt/firewall-app
unzip mikrotik_vlan_modes_tk_app.zip
cd mikrotik_vlan_modes_tk_app

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecutar

```bash
./modo_salo.sh
```

O manualmente:

```bash
source .venv/bin/activate
python3 app.py --host 10.99.0.1 --port 7443 --user firewall-app --vlan 21 --network 10.0.21.0/24 --name "Saló de Actes"
```

## Requisitos en MikroTik

- `www-ssl` activo en puerto 7443.
- Reglas input permitiendo `SRC_TODAS_LAN -> 10.99.0.1:7443`.
- Usuario con permisos suficientes para modificar `/ip firewall address-list` y limpiar `/ip firewall connection`.
- La lista `MODE_SELECTIVE` y las listas `ALLOW_*` deben existir en las reglas del firewall con la semántica mostrada en el diagrama.

## Historial de versiones

### 1.1.0

Primera versión con `MODE_SELECTIVE`, selección dinámica de listas `ALLOW_*`
y sincronización de los permisos activos desde MikroTik.
