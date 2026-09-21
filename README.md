# MikroTik VLAN Modes App - Tkinter

La aplicación permite cambiar una VLAN entre `MODE_NORMAL`, `MODE_EXAM`,
`MODE_RESTRICTED` y `MODE_SELECTIVE`.

## Versión 1.3.0

- Los checkbox `ALLOW_*` aplican el cambio inmediatamente al marcarlos o desmarcarlos, sin esperar a pulsar "Pasar a MODE_SELECTIVE".
- Los checkbox `ALLOW_*` solo están habilitados mientras la VLAN está en `MODE_SELECTIVE`; en el resto de modos aparecen deshabilitados.
- La ventana se ajusta automáticamente al tamaño de la pantalla y se puede redimensionar.
- Cada cambio de modo (`MODE_EXAM`, `MODE_RESTRICTED`, `MODE_SELECTIVE`, `MODE_NORMAL`) pide confirmación antes de aplicarse; si se cancela, no se realiza ninguna petición al MikroTik.

## Versión 1.2.0

- Añadido `MODE_SELECTIVE`.
- Catálogo fijo de listas opcionales `ALLOW_*`, visible aunque estén vacías en MikroTik.
- Selección de permisos opcionales desde la interfaz Tkinter.
- Limpieza automática de las listas `ALLOW_*` al cambiar a otro modo, incluidos los checkbox de la interfaz.
- `MODE_NORMAL` se verifica comprobando la pertenencia a `SRC_GENERAL`.
- Limpieza de conexiones (`conntrack`) tratada como una acción best-effort que no invalida un cambio de modo ya confirmado.
- Instalación documentada paso a paso para Ubuntu.

En `MODE_SELECTIVE`, la red se añade siempre a `MODE_SELECTIVE` y, de forma
opcional, a las listas del catálogo `ALLOW_*`. Las reglas del firewall deben
interpretar esas listas como permisos adicionales para una red que ya
pertenece a `MODE_SELECTIVE`.

Las listas opcionales soportadas son `ALLOW_AI`, `ALLOW_SEARCH`,
`ALLOW_M365`, `ALLOW_SIMARRO`, `ALLOW_ISOS`, `ALLOW_VIDEOGAME` y
`ALLOW_FULL_INTERNET`. Se declaran de forma fija en la aplicación porque
RouterOS no representa una address-list vacía como un objeto independiente.

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

## Instalación en Ubuntu

### 1. Instalar Python y Tkinter

Ejecuta estos comandos con un usuario que tenga permisos `sudo`:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip python3-tk unzip git
```

### 2. Obtener la aplicación

Elige una de estas dos opciones.

Desde GitHub:

```bash
sudo mkdir -p /opt/firewall-app
sudo chown "$USER":"$USER" /opt/firewall-app
cd /opt/firewall-app
git clone https://github.com/alapvi/firewall-app.git mikrotik_vlan_modes_tk_app
cd mikrotik_vlan_modes_tk_app
```

Desde un archivo ZIP:

```bash
mkdir -p /opt/firewall-app
cd /opt/firewall-app
unzip mikrotik_vlan_modes_tk_app.zip
cd mikrotik_vlan_modes_tk_app
```

### 3. Crear el entorno virtual

El entorno virtual mantiene las dependencias aisladas del Python del sistema:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

El prompt del terminal mostrará normalmente `(.venv)` mientras esté activo.

### 4. Instalar las dependencias

Con el entorno virtual activo:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 5. Comprobar los requisitos de MikroTik

Antes de ejecutar la aplicación, confirma que en el CCR están disponibles:

- `www-ssl` activo en el puerto `7443`.
- Reglas `input` permitiendo `SRC_TODAS_LAN -> 10.99.0.1:7443`.
- Un usuario con permisos para modificar `/ip firewall address-list` y limpiar
	`/ip firewall connection`.
- La lista `MODE_SELECTIVE` y las listas `ALLOW_*` usadas por las reglas del
	firewall.

### 6. Configurar la VLAN

El script `modo_salo.sh` ya viene preparado para la VLAN 21, red
`10.0.21.0/24` y nombre `Saló de Actes`:

```bash
./modo_salo.sh
```

Si la VLAN es diferente, edita ese script o ejecuta la aplicación manualmente:

```bash
source .venv/bin/activate
python app.py --host 10.99.0.1 --port 7443 --user firewall-app \
	--vlan 21 --network 10.0.21.0/24 --name "Saló de Actes"
```

La aplicación solicitará la contraseña de MikroTik en una ventana, no desde la
línea de comandos.

### 6.1. Ejecutar desde un servidor sin escritorio

La aplicación utiliza Tkinter y necesita una pantalla gráfica. Si el servidor
se administra por SSH y `echo "$DISPLAY"` no muestra ningún valor, no se puede
abrir la ventana directamente en esa terminal.

Opciones recomendadas:

- Ejecutar la aplicación en un ordenador con escritorio gráfico y conectarlo al
	MikroTik usando la IP y el puerto configurados.
- Usar SSH con reenvío X11 desde un equipo Linux o macOS:

	```bash
	ssh -X usuario@servidor
	cd /opt/firewall-app/mikrotik_vlan_modes_tk_app
	source .venv/bin/activate
	./modo_salo.sh
	```

	El equipo cliente debe tener un servidor X instalado y el servidor SSH debe
	permitir `X11Forwarding`.
- Usar un escritorio remoto o VNC en el servidor.

Un display virtual como `Xvfb` solo sirve para ejecutar la aplicación sin verla;
no es útil para manejar esta interfaz de forma interactiva.

### 7. Seleccionar `MODE_SELECTIVE`

Pulsa **Actualizar estado** para consultar las listas `ALLOW_*` disponibles.
Marca las listas que quieras aplicar y pulsa **Pasar a MODE_SELECTIVE**. La red
se añadirá a `MODE_SELECTIVE` y a cada lista seleccionada.

Para salir del modo selectivo, cambia a `MODE_EXAM`, `MODE_RESTRICTED` o
`MODE_NORMAL`. Las entradas `ALLOW_*` de esa VLAN se eliminarán al cambiar de
modo.

## Requisitos en MikroTik

- `www-ssl` activo en puerto 7443.
- Reglas input permitiendo `SRC_TODAS_LAN -> 10.99.0.1:7443`.
- Usuario con permisos suficientes para modificar `/ip firewall address-list` y limpiar `/ip firewall connection`.
- La lista `MODE_SELECTIVE` y las listas `ALLOW_*` deben existir en las reglas del firewall con la semántica mostrada en el diagrama.

## Historial de versiones

### 1.3.0

Los permisos `ALLOW_*` se activan o desactivan al instante mientras la VLAN
está en `MODE_SELECTIVE` y quedan deshabilitados en el resto de modos. La
ventana se adapta al tamaño de la pantalla y todos los cambios de modo piden
confirmación antes de aplicarse.

### 1.2.0

`get_vlan_mode` verifica `SRC_GENERAL` en una sola consulta REST, las listas
`ALLOW_*` pasan a un catálogo fijo, los identificadores `.id` de RouterOS ya
no codifican el `*`, y la limpieza de `conntrack` se trata como una acción
best-effort independiente del cambio de modo.

### 1.1.3

Guía de instalación ampliada con pasos para obtener el código, crear el
entorno virtual, instalar dependencias, configurar la VLAN y ejecutar la
aplicación.

### 1.1.0

Primera versión con `MODE_SELECTIVE`, selección dinámica de listas `ALLOW_*`
y sincronización de los permisos activos desde MikroTik.
