#!/usr/bin/env python3
import argparse, socket, struct, time

ap = argparse.ArgumentParser()
ap.add_argument("--left",  default="127.0.0.1")  # cateye-left IP
ap.add_argument("--right", default="127.0.0.1")  # cateye-right IP
ap.add_argument("--port",  type=int, default=5005)
ap.add_argument("--lx", type=int, default=128)
ap.add_argument("--ly", type=int, default=128)
ap.add_argument("--lblink", type=int, default=0)
ap.add_argument("--lpupil", type=int, default=180)
ap.add_argument("--rx", type=int, default=128)
ap.add_argument("--ry", type=int, default=128)
ap.add_argument("--rblink", type=int, default=0)
ap.add_argument("--rpupil", type=int, default=180)
ap.add_argument("--sweep", action="store_true", help="sweep horizontaal L/R")
args = ap.parse_args()

def clamp(x): return max(0, min(255, int(x)))
def payload(lx,ly,lb,lp, rx,ry,rb,rp):
    vals = [clamp(v) for v in (lx,ly,lb,lp, rx,ry,rb,rp)]
    return struct.pack("8B", *vals)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_once(lx,ly,lb,lp, rx,ry,rb,rp):
    p = payload(lx,ly,lb,lp, rx,ry,rb,rp)
    sock.sendto(p, (args.left,  args.port))
    sock.sendto(p, (args.right, args.port))
    print("sent:", [lx,ly,lb,lp, rx,ry,rb,rp])

if args.sweep:
    for x in list(range(0,256,8)) + list(range(255,-1,-8)):
        send_once(x,128,0,180, 255-x,128,0,180); time.sleep(0.02)
else:
    send_once(args.lx,args.ly,args.lblink,args.lpupil,
              args.rx,args.ry,args.rblink,args.rpupil)
