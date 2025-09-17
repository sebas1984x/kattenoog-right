
---

## 🔹 `kattenoog-right/README.md`

```markdown
# Kattenoog – Rechter Pi

Deze Raspberry Pi bestuurt het **rechteroog** en de **kaakservo**.

## Functie
- Visualiseert het **rechteroog** op een display
- Ontvangt UDP-data (poort 5005) met 4 waarden: `look_x`, `look_y`, `pupil`, `lid`
- Stuurt de **Dynamixel kaakservo** via UDP-data (poort 5006)

## Scripts
Alle code staat in `/home/cat/kattenoog/` en in deze repo:
- `kattenoog_plc_udp_oneeye.py` → aansturing rechteroog
- `jaw_udp_dynamixel.py` → kaakservo controller
- `eyes_send.py` → test/diagnose script voor ogen
- `jaw_send.py` → test/diagnose script voor kaak

## Systemd services
Geïnstalleerd in `/etc/systemd/system/` en ook in de map `services/` van deze repo:
- `eye.service` → hoofdservice voor rechteroog
- `jaw.service` → hoofdservice voor kaakservo

### Voorbeelden
Status bekijken:
```bash
systemctl status eye.service
systemctl status jaw.service
