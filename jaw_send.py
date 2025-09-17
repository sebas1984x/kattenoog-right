#!/usr/bin/env python3
import argparse, socket, struct, time

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=5006)
parser.add_argument("--value", type=int, help="Jaw value 0-255")
parser.add_argument("--sweep", action="store_true")
args = parser.parse_args()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

if args.sweep:
    print("Sweeping jaw 0..255..0")
    for v in list(range(0,256,10)) + list(range(255,-1,-10)):
        pkt = struct.pack("B", v)
        sock.sendto(pkt, (args.host, args.port))
        time.sleep(0.05)
elif args.value is not None:
    pkt = struct.pack("B", args.value)
    sock.sendto(pkt, (args.host, args.port))
    print(f"Sent jaw value {args.value}")
else:
    print("Use --value N or --sweep")
