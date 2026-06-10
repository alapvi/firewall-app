# MikroTik VLAN Modes App - Tkinter

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
