#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Snap7 → Dynamixel kaakcontroller met snelheidsregeling per commando.

PLC schrijft DB_Command, Pi leest en stuurt Dynamixel.
Pi schrijft DB_Status terug met feedback en heartbeat.

DB_Command (PLC → Pi)  [DB num: --db_cmd]
  INT   jaw_pos_sp    @ 0   # 0..1000
  INT   jaw_vel_sp    @ 2   # 0..1000
  INT   jaw_acc_sp    @ 4   # 0..1000
  BOOL  jaw_invert    @ 6.0
  BOOL  enable        @ 6.1
  UINT  cmd_seq       @ 8

DB_Status (Pi → PLC)   [DB num: --db_sts]
  INT   jaw_pos_fb    @ 0
  INT   jaw_vel_fb    @ 2
  UINT  ack_seq       @ 4
  BOOL  hw_ok         @ 6.0
  BOOL  sw_ok         @ 6.1
  DWORD ts_ms         @ 8

Start:
  pip install python-snap7 dynamixel-sdk
"""

import argparse
import struct
import time
import sys
import signal
from typing import Optional

# python-snap7
import snap7
from snap7.util import get_bool
# dynamixel-sdk
from dynamixel_sdk import PortHandler, PacketHandler, COMM_SUCCESS

# ---------------------- Dynamixel control table (Protocol 2.0, X-serie) ----------------------
ADDR_OPERATING_MODE     = 11     # 1B
ADDR_TORQUE_ENABLE      = 64     # 1B
ADDR_VELOCITY_LIMIT     = 44     # 4B
ADDR_ACCEL_LIMIT        = 40     # 4B
ADDR_MIN_POS_LIMIT      = 52     # 4B
ADDR_MAX_POS_LIMIT      = 48     # 4B
ADDR_BUS_WATCHDOG       = 98     # 1B (value = N*20ms, 0=off)
ADDR_PROFILE_ACCEL      = 108    # 4B
ADDR_PROFILE_VELOCITY   = 112    # 4B
ADDR_GOAL_VELOCITY      = 104    # 4B (not used in position mode)
ADDR_GOAL_POSITION      = 116    # 4B
ADDR_PRESENT_VELOCITY   = 128    # 4B (signed)
ADDR_PRESENT_POSITION   = 132    # 4B

TORQUE_ON, TORQUE_OFF = 1, 0
OPERATING_MODE_POSITION = 3      # Position Control
TICKS_PER_REV = 4096.0

# ---------------------------------------------------------------------------------------------

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

def deg_to_tick(deg: float) -> int:
    # Map 0..360 naar 0..4095
    return int(round((deg % 360.0) * (TICKS_PER_REV / 360.0)))

def tick_to_deg(ticks: int) -> float:
    return (ticks % 4096) * 360.0 / TICKS_PER_REV

def now_ms() -> int:
    return int(time.time() * 1000)

# ---------------------- S7 helpers (big-endian) ----------------------------------------------

def u16_be(b: bytes, off: int) -> int:
    return struct.unpack_from(">H", b, off)[0]

def i16_be(b: bytes, off: int) -> int:
    return struct.unpack_from(">h", b, off)[0]

def u32_be(b: bytes, off: int) -> int:
    return struct.unpack_from(">I", b, off)[0]

def set_i16_be(barr: bytearray, off: int, val: int):
    struct.pack_into(">h", barr, off, val)

def set_u16_be(barr: bytearray, off: int, val: int):
    struct.pack_into(">H", barr, off, val)

def set_u32_be(barr: bytearray, off: int, val: int):
    struct.pack_into(">I", barr, off, val)

# ---------------------- Main -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Snap7 → Dynamixel jaw controller")
    # PLC / snap7  (default PLC-adres ingebouwd, kan worden overschreven met --plc_host)
    ap.add_argument("--plc_host", default="192.168.0.10", help="PLC IP/host")
    ap.add_argument("--rack", type=int, default=0)
    ap.add_argument("--slot", type=int, default=1)
    ap.add_argument("--db_cmd", type=int, default=1, help="DB number for Command")
    ap.add_argument("--db_sts", type=int, default=2, help="DB number for Status")
    # Dynamixel serial
    ap.add_argument("--dev", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=57600)
    ap.add_argument("--id",   type=int, default=1)
    # Schaal en grenzen
    ap.add_argument("--min_deg", type=float, default=200.0)
    ap.add_argument("--max_deg", type=float, default=245.0)
    ap.add_argument("--vel_floor", type=int, default=1, help="min Profile Velocity LSB")
    ap.add_argument("--acc_floor", type=int, default=1, help="min Profile Accel LSB")
    # Profile defaults (fallbacks als PLC 0 stuurt of limits niet leesbaar zijn)
    ap.add_argument("--prof_acc_default", type=int, default=30000)
    ap.add_argument("--prof_vel_default", type=int, default=50000)
    # Loop
    ap.add_argument("--hz", type=float, default=100.0)
    ap.add_argument("--watchdog_20ms", type=int, default=3, help="Bus Watchdog ticks (N*20ms). 0=off, 3≈60ms")
    args = ap.parse_args()

    dt = 1.0 / args.hz
    scale = 1000.0  # PLC-schaal 0..1000

    # ------------------- Connect PLC -------------------
    plc = snap7.client.Client()
    try:
        plc.connect(args.plc_host, args.rack, args.slot)
    except Exception as e:
        print(f"[ERR] PLC connect: {e}", file=sys.stderr)
        sys.exit(1)

    # Dummy read om te checken
    try:
        _ = plc.db_read(args.db_cmd, 0, 12)
    except Exception as e:
        print(f"[ERR] PLC DB{args.db_cmd} read test: {e}", file=sys.stderr)
        sys.exit(1)

    # ------------------- Connect Dynamixel -------------------
    ph = PortHandler(args.dev)
    if not ph.openPort():
        print(f"[ERR] open {args.dev}", file=sys.stderr); sys.exit(1)
    if not ph.setBaudRate(args.baud):
        print(f"[ERR] baud {args.baud}", file=sys.stderr); sys.exit(1)
    pk = PacketHandler(2.0)

    def dx_ok(rc, er, ctx=""):
        if rc != COMM_SUCCESS or er != 0:
            print(f"[DXL] rc={rc} err={er} {ctx}", file=sys.stderr)
        return rc == COMM_SUCCESS and er == 0

    # Netjes afsluiten
    def cleanup(*_):
        try: pk.write1ByteTxRx(ph, args.id, ADDR_TORQUE_ENABLE, TORQUE_OFF)
        except: pass
        try: ph.closePort()
        except: pass
        try: plc.disconnect()
        except: pass
        sys.exit(0)

    signal.signal(signal.SIGINT,  cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Init Dynamixel
    pk.write1ByteTxRx(ph, args.id, ADDR_TORQUE_ENABLE, TORQUE_OFF)
    dx_ok(*pk.write1ByteTxRx(ph, args.id, ADDR_OPERATING_MODE, OPERATING_MODE_POSITION), "set mode=position")

    # Lees hardware limits (fallbacks naar defaults)
    vel_lim, rc, er = pk.read4ByteTxRx(ph, args.id, ADDR_VELOCITY_LIMIT)
    if rc != COMM_SUCCESS: vel_lim = args.prof_vel_default
    acc_lim, rc, er = pk.read4ByteTxRx(ph, args.id, ADDR_ACCEL_LIMIT)
    if rc != COMM_SUCCESS: acc_lim = args.prof_acc_default

    max_ticks, rc1, er1 = pk.read4ByteTxRx(ph, args.id, ADDR_MAX_POS_LIMIT)
    min_ticks, rc2, er2 = pk.read4ByteTxRx(ph, args.id, ADDR_MIN_POS_LIMIT)
    if rc1 != COMM_SUCCESS or rc2 != COMM_SUCCESS:
        min_ticks, max_ticks = 0, 4095
        print("[WARN] kon HW-limieten niet lezen, val terug op 0..4095", file=sys.stderr)
    if min_ticks > max_ticks:
        min_ticks, max_ticks = max_ticks, min_ticks

    # Init profielwaarden en torque
    pv0 = clamp(args.prof_vel_default, args.vel_floor, vel_lim)
    pa0 = clamp(args.prof_acc_default, args.acc_floor, acc_lim)
    dx_ok(*pk.write4ByteTxRx(ph, args.id, ADDR_PROFILE_VELOCITY, pv0), "init prof_vel")
    dx_ok(*pk.write4ByteTxRx(ph, args.id, ADDR_PROFILE_ACCEL,    pa0), "init prof_acc")

    if args.watchdog_20ms and args.watchdog_20ms > 0:
        dx_ok(*pk.write1ByteTxRx(ph, args.id, ADDR_BUS_WATCHDOG, args.watchdog_20ms), "bus watchdog")

    dx_ok(*pk.write1ByteTxRx(ph, args.id, ADDR_TORQUE_ENABLE, TORQUE_ON), "torque on")

    sw_min = min(args.min_deg, args.max_deg)
    sw_max = max(args.min_deg, args.max_deg)

    print(f"[INFO] DXL HW limits ticks: {min_ticks}..{max_ticks}  "
          f"({tick_to_deg(max_ticks):.1f}° max)")
    print(f"[INFO] SW range: {sw_min:.1f}..{sw_max:.1f}°, vel_lim={vel_lim}, acc_lim={acc_lim}, hz={args.hz}")

    # ------------------- Runtime state -------------------
    last_seq: Optional[int] = None
    torque_enabled = True

    # ------------------- Main loop -------------------
    while True:
        loop_t0 = time.perf_counter()

        # 1) Lees Command DB
        try:
            cmd_raw = plc.db_read(args.db_cmd, 0, 12)  # 0..11
        except Exception as e:
            print(f"[ERR] PLC DB{args.db_cmd} read: {e}", file=sys.stderr)
            cmd_raw = bytes(12)

        jaw_pos_sp = i16_be(cmd_raw, 0)          # 0..1000
        jaw_vel_sp = i16_be(cmd_raw, 2)          # 0..1000
        jaw_acc_sp = i16_be(cmd_raw, 4)          # 0..1000
        jaw_invert = get_bool(cmd_raw, 6, 0)     # byte 6, bit 0
        enable     = get_bool(cmd_raw, 6, 1)     # byte 6, bit 1
        cmd_seq    = u16_be(cmd_raw, 8)

        # 2) Torque gating
        if not enable and torque_enabled:
            dx_ok(*pk.write1ByteTxRx(ph, args.id, ADDR_TORQUE_ENABLE, TORQUE_OFF), "torque off")
            torque_enabled = False
        if enable and not torque_enabled:
            dx_ok(*pk.write1ByteTxRx(ph, args.id, ADDR_TORQUE_ENABLE, TORQUE_ON), "torque on")
            torque_enabled = True

        # 3) Als nieuw commando: profielen + doelpositie
        if enable and (last_seq is None or cmd_seq != last_seq):
            # Map PLC 0..1000 naar graden
            pos_u = clamp(jaw_pos_sp, 0, 1000) / scale
            vel_u = clamp(jaw_vel_sp, 0, 1000) / scale
            acc_u = clamp(jaw_acc_sp, 0, 1000) / scale

            deg = sw_min + pos_u * (sw_max - sw_min)
            if jaw_invert:
                deg = sw_min + (1.0 - pos_u) * (sw_max - sw_min)

            ticks = clamp(deg_to_tick(deg), min_ticks, max_ticks)

            # Map snelheid/acc naar DXL LSB's via hardware-limits
            prof_vel = clamp(int(args.vel_floor + vel_u * (vel_lim - args.vel_floor)), args.vel_floor, vel_lim)
            prof_acc = clamp(int(args.acc_floor + acc_u * (acc_lim - args.acc_floor)), args.acc_floor, acc_lim)

            # Schrijf profiel en doel
            dx_ok(*pk.write4ByteTxRx(ph, args.id, ADDR_PROFILE_VELOCITY, prof_vel), "set prof_vel")
            dx_ok(*pk.write4ByteTxRx(ph, args.id, ADDR_PROFILE_ACCEL,    prof_acc), "set prof_acc")
            rc, er = pk.write4ByteTxRx(ph, args.id, ADDR_GOAL_POSITION, int(ticks))
            if rc != COMM_SUCCESS or er != 0:
                print(f"[DXL] write goal failed rc={rc} err={er}", file=sys.stderr)

            last_seq = cmd_seq

        # 4) Lees feedback van Dynamixel
        pos_fb_ticks, rcP, erP = pk.read4ByteTxRx(ph, args.id, ADDR_PRESENT_POSITION)
        if rcP != COMM_SUCCESS:
            pos_fb_ticks = 0

        vel_fb_raw, rcV, erV = pk.read4ByteTxRx(ph, args.id, ADDR_PRESENT_VELOCITY)
        if rcV != COMM_SUCCESS:
            vel_fb_raw = 0

        # Normaliseer snelheid tov vel_lim naar 0..1000
        vel_fb_abs = abs(vel_fb_raw)
        vel_fb_scaled = int(clamp(round((vel_fb_abs / max(1, vel_lim)) * 1000.0), 0, 1000))

        # Positie feedback terug op 0..1000 schaal binnen SW-range
        pos_fb_deg = tick_to_deg(pos_fb_ticks)
        if sw_max > sw_min:
            pos_fb_u = (clamp(pos_fb_deg, sw_min, sw_max) - sw_min) / (sw_max - sw_min)
        else:
            pos_fb_u = 0.0
        if jaw_invert:
            pos_fb_u = 1.0 - pos_fb_u
        jaw_pos_fb = int(clamp(round(pos_fb_u * 1000.0), 0, 1000))

        # 5) Schrijf Status DB
        sts = bytearray(12)  # 0..11
        set_i16_be(sts, 0, jaw_pos_fb)
        set_i16_be(sts, 2, vel_fb_scaled)
        set_u16_be(sts, 4, last_seq if last_seq is not None else 0)
        # byte 6: bits 0=hw_ok, 1=sw_ok
        hw_ok = int(rcP == COMM_SUCCESS and rcV == COMM_SUCCESS and torque_enabled)
        sw_ok = 1  # script loopt
        sts[6] = (hw_ok & 1) | ((sw_ok & 1) << 1)
        set_u32_be(sts, 8, now_ms())

        try:
            plc.db_write(args.db_sts, 0, bytes(sts))
        except Exception as e:
            print(f"[ERR] PLC DB{args.db_sts} write: {e}", file=sys.stderr)

        # 6) Houd de loopfrequentie vast
        elapsed = time.perf_counter() - loop_t0
        sleep_t = dt - elapsed
        if sleep_t > 0:
            time.sleep(sleep_t)

# ---------------------------------------------------------------------------------------------

if __name__ == "__main__":
    main()
```0
