#!/usr/bin/env python3
import argparse, socket, time, sys, signal
from dynamixel_sdk import PortHandler, PacketHandler, COMM_SUCCESS

# Control table (Protocol 2.0, X-serie)
ADDR_OPERATING_MODE   = 11
ADDR_TORQUE_ENABLE    = 64
ADDR_PROFILE_ACCEL    = 108
ADDR_PROFILE_VELOCITY = 112
ADDR_GOAL_POSITION    = 116
ADDR_MAX_POS_LIMIT    = 48   # 4 bytes
ADDR_MIN_POS_LIMIT    = 52   # 4 bytes

TORQUE_ON, TORQUE_OFF = 1, 0
TICKS_PER_REV = 4096.0

def deg_to_tick(deg: float) -> int:
    return max(0, min(4095, int(round((deg % 360.0) * TICKS_PER_REV / 360.0))))

def tick_to_deg(ticks: int) -> float:
    return (ticks % 4096) * 360.0 / TICKS_PER_REV

def clamp(x, lo, hi): 
    return lo if x < lo else hi if x > hi else x

def main():
    ap = argparse.ArgumentParser(description="UDP→Dynamixel jaw controller (0..255 → min_deg..max_deg)")
    ap.add_argument("--dev", default="/dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=57600)
    ap.add_argument("--id",   type=int, default=1)
    ap.add_argument("--port", type=int, default=5006, help="UDP poort (1 byte)")
    ap.add_argument("--min_deg", type=float, default=200.0, help="ondergrens in graden")
    ap.add_argument("--max_deg", type=float, default=245.0, help="bovengrens in graden")
    ap.add_argument("--prof_acc", type=int, default=30000)
    ap.add_argument("--prof_vel", type=int, default=50000)
    ap.add_argument("--invert", action="store_true", help="keer mapping om (0->max_deg, 255->min_deg)")
    args = ap.parse_args()

    # Serial/open
    ph = PortHandler(args.dev)
    if not ph.openPort():
        print(f"[ERR] open {args.dev}", file=sys.stderr); sys.exit(1)
    if not ph.setBaudRate(args.baud):
        print(f"[ERR] baud {args.baud}", file=sys.stderr); sys.exit(1)
    pk = PacketHandler(2.0)

    def ok(rc, er, ctx=""):
        if rc != COMM_SUCCESS or er != 0:
            print(f"[DXL] rc={rc} err={er} {ctx}", file=sys.stderr)
        return rc == COMM_SUCCESS and er == 0

    def cleanup(*_):
        try: pk.write1ByteTxRx(ph, args.id, ADDR_TORQUE_ENABLE, TORQUE_OFF)
        except: pass
        try: ph.closePort()
        except: pass
        sys.exit(0)

    signal.signal(signal.SIGINT,  cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Init (schrijft GEEN limieten)
    pk.write1ByteTxRx(ph, args.id, ADDR_TORQUE_ENABLE, TORQUE_OFF)
    ok(*pk.write1ByteTxRx(ph, args.id, ADDR_OPERATING_MODE, 3), "set mode=position")
    ok(*pk.write4ByteTxRx(ph, args.id, ADDR_PROFILE_ACCEL,    int(args.prof_acc)), "set prof_acc")
    ok(*pk.write4ByteTxRx(ph, args.id, ADDR_PROFILE_VELOCITY, int(args.prof_vel)), "set prof_vel")
    ok(*pk.write1ByteTxRx(ph, args.id, ADDR_TORQUE_ENABLE, TORQUE_ON), "torque on")

    # HW-limieten lezen
    max_ticks, rc1, er1 = pk.read4ByteTxRx(ph, args.id, ADDR_MAX_POS_LIMIT)
    min_ticks, rc2, er2 = pk.read4ByteTxRx(ph, args.id, ADDR_MIN_POS_LIMIT)
    if rc1 != COMM_SUCCESS or rc2 != COMM_SUCCESS:
        min_ticks, max_ticks = 0, 4095
        print("[WARN] kon HW-limieten niet lezen, val terug op 0..4095", file=sys.stderr)
    if min_ticks > max_ticks:
        min_ticks, max_ticks = max_ticks, min_ticks

    sw_min = min(args.min_deg, args.max_deg)
    sw_max = max(args.min_deg, args.max_deg)

    print(f"[INFO] HW limits: {min_ticks}..{max_ticks} ticks  "
          f"({tick_to_deg(min_ticks):.1f}..{tick_to_deg(max_ticks):.1f}°)")
    print(f"[INFO] SW range: {sw_min:.1f}..{sw_max:.1f}°  baud={args.baud}  invert={args.invert}")
    print(f"[OK] Luistert op UDP :{args.port} (1 byte 0..255)")

    # UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.port))
    sock.setblocking(True)

    last_b = None
    while True:
        data, _ = sock.recvfrom(8)
        if not data: 
            continue
        b = int(data[0]) & 0xFF
        if args.invert:
            b = 255 - b
        if b == last_b:
            continue
        last_b = b

        # 0..255 → graden
        deg = sw_min + (b/255.0) * (sw_max - sw_min)
        ticks = deg_to_tick(deg)
        # clamp op HW-limieten
        ticks = clamp(ticks, min_ticks, max_ticks)

        rc, er = pk.write4ByteTxRx(ph, args.id, ADDR_GOAL_POSITION, int(ticks))
        if rc != COMM_SUCCESS or er != 0:
            print(f"[DXL] write goal failed rc={rc} err={er}", file=sys.stderr)
        # print(f"RX {b:3d} -> {deg:6.2f}° -> {ticks} ticks")  # desgewenst aanzetten

if __name__ == "__main__":
    main()

