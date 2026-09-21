#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
python3 app.py --host 10.99.0.1 --port 7443 --user firewall-app --vlan 21 --network 10.0.21.0/24 --name "Saló de Actes"
