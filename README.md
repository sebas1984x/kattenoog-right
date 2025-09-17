# Kattenoog – Rechter Pi

Deze Raspberry Pi bestuurt:
- Het **rechter oog** (UDP 5005 → `eye.service`)
- De **kaakservo** via Dynamixel (UDP 5006 → `jaw.service`)

## Scripts
Alle code staat in `/home/cat/kattenoog/` en in deze repo.

- `kattenoog_plc_udp_oneeye.py` → visualisatie van het rechteroog
- `jaw_udp_dynamixel.py` → aansturing van de kaakservo via Dynamixel
- Extra helper-scripts (`eyes_send.py`, `jaw_send.py`)

## Systemd services
Geïnstalleerd in `/etc/systemd/system/` en ook in `services/` map van deze repo.

- `eye.service` → start het rechter oog (UDP 5005)
- `jaw.service` → start de kaakservo (UDP 5006)

Status bekijken:
```bash
systemctl status eye.service
systemctl status jaw.service

## Herstarten
sudo systemctl restart eye.service
sudo systemctl restart jaw.service

##Autostart
systemctl is-enabled eye.service
systemctl is-enabled jaw.service

