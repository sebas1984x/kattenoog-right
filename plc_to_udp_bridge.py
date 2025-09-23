#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import time
import snap7
from snap7.util import get_real, get_byte

# ----------------------------
# CONFIG
# ----------------------------
PLC_IP   = "2.100.1.243"   # IP van je PLC
RACK, SLOT = 0, 1           # S7-1200/1500 = meestal 0,1
DB       = 1                # Data Block nummer (non-optimized DB)
PERIOD   = 0.02             # 20 ms ≈ 50 Hz zendfrequentie

# UDP doel (oog-daemon draait lokaal; 127.0.0.1 is prima)
EYES_HOST, EYES_PORT = "127.0.0.1", 5005

# Offsets in DB1 (non-optimized!). REAL of BYTE zijn toegestaan.
# Laat Liris/Riris op None als je die (nog) niet gebruikt.
OFF = {
    "Lx": 0,     "Ly": 4,     "Lpupil": 8,     "Llid": 12,      # linkeroog
    "Rx": 100,   "Ry": 104,   "Rpupil": 108,   "Rlid": 112,     # rechteroog
    "Liris": None,            # bv 20  (REAL 0..1 of BYTE 0..255)
    "Riris": None,            # bv 120 (REAL 0..1 of BYTE 0..255)
    # Kaak is voortaan via snap7 direct geregeld → geen UDP meer
}

# ----------------------------
# HELPERS
# ----------------------------
def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v

def scale_to_byte_real(v, lo, hi):
    """Schaal REAL v van [lo..hi] naar byte 0..255 met clamping."""
    if v is None:
        return 0
    v = clamp(v, lo, hi)
    t = 0.0 if hi == lo else (v - lo) / (hi - lo)
    return int(round(clamp(t, 0.0, 1.0) * 255))

def read_val(buf, off, expect="real"):
    """
    Lees een waarde uit buffer:
    - expect="real": probeer REAL; fallback naar BYTE/255.0
    - expect="byte": probeer BYTE; fallback naar REAL*255
    """
    if off is None:
        return None
    if expect == "real":
        try:
            return get_real(buf, off)              # verwacht -1..+1 of 0..1
        except Exception:
            return get_byte(buf, off) / 255.0      # fallback: byte -> 0..1
    else:  # "byte"
        try:
            return get_byte(buf, off)              # verwacht 0..255
        except Exception:
            return int(round(get_real(buf, off) * 255.0))  # fallback: real -> 0..255

def two_axis(buf, nx, ny):
    """Leest twee assen als REAL (-1..1) of BYTE en schaalt naar 0..255."""
    vx = read_val(buf, OFF[nx], "real")
    vy = read_val(buf, OFF[ny], "real")
    bx = scale_to_byte_real(vx, -1.0, 1.0) if isinstance(vx, float) else int(vx or 0)
    by = scale_to_byte_real(vy, -1.0, 1.0) if isinstance(vy, float) else int(vy or 0)
    return bx, by

def build_eye_packet(buf):
    """Maak 8- of 10-byte oogpakket op basis van DB-buffer."""
    Lx, Ly = two_axis(buf, "Lx", "Ly")
    Rx, Ry = two_axis(buf, "Rx", "Ry")

    # pupil/lid: 0..1 → 0..255 (of direct byte)
    Lp = read_val(buf, OFF["Lpupil"], "real")
    Rp = read_val(buf, OFF["Rpupil"], "real")
    Ll = read_val(buf, OFF["Llid"],   "real")
    Rl = read_val(buf, OFF["Rlid"],   "real")

    Lp = scale_to_byte_real(Lp, 0.0, 1.0) if isinstance(Lp, float) else int(Lp or 0)
    Rp = scale_to_byte_real(Rp, 0.0, 1.0) if isinstance(Rp, float) else int(Rp or 0)
    Ll = scale_to_byte_real(Ll, 0.0, 1.0) if isinstance(Ll, float) else int(Ll or 0)
    Rl = scale_to_byte_real(Rl, 0.0, 1.0) if isinstance(Rl, float) else int(Rl or 0)

    pkt8 = bytes([Lx, Ly, Ll, Lp,  Rx, Ry, Rl, Rp])

    # optionele iris
    Li = read_val(buf, OFF["Liris"], "real") if OFF.get("Liris") is not None else None
    Ri = read_val(buf, OFF["Riris"], "real") if OFF.get("Riris") is not None else None
    if isinstance(Li, float): Li = scale_to_byte_real(Li, 0.0, 1.0)
    if isinstance(Ri, float): Ri = scale_to_byte_real(Ri, 0.0, 1.0)

    if Li is not None and Ri is not None:
        return pkt8 + bytes([int(Li), int(Ri)])
    return pkt8

# ----------------------------
# ROBUUSTE MAIN MET RECONNECT
# ----------------------------
def main():
    # UDP socket voor ogen
    sock_eye = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Bepaal een veilige leesgrootte op basis van hoogste offset
    used_offsets = [v for v in OFF.values() if isinstance(v, int)]
    read_size  = (max(used_offsets) + 16) if used_offsets else 64

    print(f"[bridge] start: PLC={PLC_IP} rack/slot={RACK}/{SLOT} DB={DB} read_size={read_size} period={PERIOD}s")
    print(f"[bridge] eyes -> {EYES_HOST}:{EYES_PORT}")

    while True:
        # Blijf verbinden tot het lukt
        try:
            plc = snap7.client.Client()
            plc.connect(PLC_IP, RACK, SLOT)
            print("[bridge] connected to PLC")
        except Exception as e:
            print(f"[bridge] connect failed: {e}")
            time.sleep(2.0)
            continue

        try:
            # Lees/zend lus; verbreek en herconnect bij fout
            while True:
                t0 = time.perf_counter()
                try:
                    buf = plc.db_read(DB, 0, read_size)
                except Exception as e:
                    print(f"[bridge] db_read failed: {e}")
                    time.sleep(0.5)
                    break

                # Ogen
                pkt = build_eye_packet(buf)
                sock_eye.sendto(pkt, (EYES_HOST, EYES_PORT))

                # Ritme aanhouden
                dt = time.perf_counter() - t0
                time.sleep(max(0.0, PERIOD - dt))

        finally:
            try:
                plc.disconnect()
            except Exception:
                pass
            print("[bridge] disconnected; retry in 1s")
            time.sleep(1.0)

if __name__ == "__main__":
    main()
