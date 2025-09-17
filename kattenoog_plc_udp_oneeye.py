#!/usr/bin/env python3
import os, socket, struct, pygame, time, math, argparse
import pygame.gfxdraw

# ---------- kleine helpers ----------
def clamp(x,a,b): return a if x<a else b if x>b else x

def smooth_damp(current, target, velocity, smooth_time, dt, max_speed=float("inf")):
    smooth_time = max(1e-4, smooth_time)
    omega = 2.0 / smooth_time
    x = omega * dt
    exp = 1.0 / (1.0 + x + 0.48*x*x + 0.235*x*x*x)
    change = current - target
    max_change = max_speed * smooth_time
    change = max(-max_change, min(max_change, change))
    target_temp = current - change
    temp = (velocity + omega * change) * dt
    new_velocity = (velocity - omega * temp) * exp
    new_value = target_temp + (change + temp) * exp
    if (target - current) * (new_value - target) > 0:
        new_value, new_velocity = target, 0.0
    return new_value, new_velocity

def _hx(h):  # "#rrggbb" -> (r,g,b)
    h = h.lstrip('#'); return tuple(int(h[i:i+2],16) for i in (0,2,4))

# ---------- VISUELE CONFIG ----------
CFG = {
    # Iris (radiale gradient)
    "BG":              _hx("#000000"),
    "IRIS_A":          _hx("#ffff00"),   # middenkleur
    "IRIS_B":          _hx("#000000"),   # randkleur (donker)
    "IRIS_RIM_W":      0,                # optionele rand om iris (px)
    "IRIS_RIM_COL":    _hx("#000000"),
    "IRIS_STEPS":      64,               # kwaliteit gradient

    # Pupilvorm
    "PUPIL_TAPER":     1.4,              # 1.3–2.0 = puntiger; hoger = ronder
    "PUPIL_W_PCT":     12,               # basisbreedte in % van schermbreedte
    "PUPIL_H_PCT":     50,               # basishoogte in % van schermhoogte
    "PUPIL_EDGE_W":    0,                # groene rand-dikte (px)
    "PUPIL_EDGE_COL":  _hx("#7db02a"),
    "PUPIL_COL":       (0,0,0),

    # Oogleden
    "EYELID_COL":      (20,20,20),

    # Smoothing
    "SMOOTH_LOOK":     0.10,
    "SMOOTH_LID":      0.06,
    "SMOOTH_PUPIL":    0.12,
    "SMOOTH_IRIS":     0.20,             # hoe ‘traag’ iris-intensiteit meeloopt
}

BG_COLOR   = CFG["BG"]
PUPIL_COL  = CFG["PUPIL_COL"]
PUPIL_EDGE = CFG["PUPIL_EDGE_COL"]
EYELID_COL = CFG["EYELID_COL"]

# ---------- iris base (radiale gradient) ----------
def make_eye_base(w,h, iris_margin=20, strength=0.5):
    """
    strength 0..1: 0 = vlak/zwak, 1 = sterke gradient.
    """
    base = pygame.Surface((w,h)).convert()
    base.fill(BG_COLOR)

    cx, cy = w//2, h//2
    iris_r = min(w,h)//2 - iris_margin

    grad = pygame.Surface((w,h), pygame.SRCALPHA).convert_alpha()
    steps = max(8, int(CFG["IRIS_STEPS"]))
    # curve iets afhankelijk van strength: hoger = “hardere” overgang
    gamma = 1.0 + (1.5 - 1.5*strength)
    for i in range(steps, 0, -1):
        t = i/steps                  # 0..1
        k = t**gamma                 # curve
        col = tuple(
            int(CFG["IRIS_A"][c]*(1-k) + CFG["IRIS_B"][c]*k)
            for c in range(3)
        )
        pygame.gfxdraw.filled_circle(grad, cx, cy, int(iris_r * t), col)
    base.blit(grad, (0,0))

    if CFG["IRIS_RIM_W"] > 0:
        pygame.draw.circle(base, CFG["IRIS_RIM_COL"], (cx,cy),
                           iris_r - CFG["IRIS_RIM_W"]//2, CFG["IRIS_RIM_W"])
    return base,(cx,cy)

# ---------- pupil surface ----------
def make_pupil_surface(pupil_w, pupil_h_half, edge=None):
    """
    Tekent een ‘tapered’ super-ellipse pupil met puntige uiteinden.
    pupil_w: volle breedte
    pupil_h_half: halve hoogte
    edge: randdikte (px)
    """
    if edge is None: edge = CFG["PUPIL_EDGE_W"]
    n = max(1.2, float(CFG.get("PUPIL_TAPER", 1.6)))  # vorm-exponent

    full_h = pupil_h_half * 2
    pad = edge + 12
    W = pupil_w + pad*2
    H = full_h + pad*2
    surf = pygame.Surface((W, H), pygame.SRCALPHA).convert_alpha()
    cx, cy = W//2, H//2

    a = pupil_w / 2.0               # halve breedte
    b = full_h / 2.0                # halve hoogte
    steps = 400                     # smooth

    def superellipse_points(scale=1.0):
        aa = a*scale
        bb = b*scale
        pts = []
        for i in range(steps+1):
            t = (i/steps)*math.tau
            c = math.cos(t); s = math.sin(t)
            x = math.copysign((abs(c)**(2.0/n))*aa, c)
            y = math.copysign((abs(s)**(2.0/n))*bb, s)
            pts.append((int(cx + x), int(cy + y)))
        return pts

    min_axis = max(1.0, min(a, b))
    ring_scale = 1.0 + (edge + 6) / min_axis

    outer = superellipse_points(scale=ring_scale) if edge > 0 else None
    inner = superellipse_points(scale=1.0)

    if edge > 0:
        pygame.gfxdraw.filled_polygon(surf, outer, CFG["PUPIL_EDGE_COL"])
        pygame.gfxdraw.aapolygon(surf, outer, CFG["PUPIL_EDGE_COL"])

    pygame.gfxdraw.filled_polygon(surf, inner, CFG["PUPIL_COL"])
    pygame.gfxdraw.aapolygon(surf, inner, CFG["PUPIL_COL"])

    return surf

def draw_eyelids(scr, openness):
    w,h = scr.get_size()
    cover = int(h*(1-openness)*0.5)
    if cover<=0: return
    pygame.draw.rect(scr, EYELID_COL, (0,0,w,cover))
    pygame.draw.rect(scr, EYELID_COL, (0,h-cover,w,cover))

# ---------- monitor helpers ----------
def get_desktops():
    try:
        sizes = pygame.display.get_desktop_sizes()
        if not sizes: raise RuntimeError
        return sizes
    except Exception:
        return [(1080,1080)]

def choose_driver():
    # Pi: probeer KMSDRM als er geen X11 DISPLAY is, anders x11
    if "SDL_VIDEODRIVER" in os.environ:
        return
    if os.environ.get("XDG_RUNTIME_DIR") and not os.environ.get("DISPLAY"):
        os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    else:
        os.environ["SDL_VIDEODRIVER"] = "x11"
        os.environ["SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR"] = "1"
        os.environ["DISPLAY"] = os.environ.get("DISPLAY", ":0")

def open_window_on_monitor(monitor, width, height, vsync=True, fullscreen=True):
    pygame.display.init()
    sizes=get_desktops()
    monitor = max(0, min(monitor, len(sizes)-1))
    x_off = sum(w for w,_ in sizes[:monitor])
    os.environ["SDL_VIDEO_WINDOW_POS"] = f"{x_off},0"
    flags = pygame.NOFRAME | pygame.DOUBLEBUF
    if fullscreen: flags |= pygame.FULLSCREEN
    try:
        screen = pygame.display.set_mode((width, height), flags, vsync=1 if vsync else 0)
    except TypeError:
        screen = pygame.display.set_mode((width, height), flags)
    pygame.mouse.set_visible(False)
    pygame.event.set_grab(True)
    return screen

# ---------- oog ----------
class Eye:
    def __init__(self, screen, width, height, ampx=240, ampy=140):
        self.scr=screen; self.w=width; self.h=height
        # iris-sterkte (0..1)
        self.iris_strength = 0.5
        self.iris_strength_target = 0.5
        self.iris_v = 0.0
        self._last_iris_strength = None

        self.base,(self.cx,self.cy)=make_eye_base(width,height, strength=self.iris_strength)
        self.ampx=ampx; self.ampy=ampy
        self.look_x=self.look_y=0.0; self.vx=self.vy=0.0
        self.smooth=CFG["SMOOTH_LOOK"]; self.maxspeed=2000

        # Pupil basisgrootte uit % van scherm
        base_pw = max(16, int(self.w * CFG["PUPIL_W_PCT"] / 100.0))
        full_ph = max(16, int(self.h * CFG["PUPIL_H_PCT"] / 100.0))
        base_ph = max(8, full_ph // 2)  # halve hoogte intern

        self.base_pw=base_pw; self.base_ph=base_ph
        self.scale=1.0; self.scale_target=1.0; self.sv=0.0
        self.min_scale=0.6; self.max_scale=1.8
        self.cur_pw=int(base_pw); self.cur_ph=int(base_ph)
        self.pupil=make_pupil_surface(self.cur_pw, self.cur_ph, CFG["PUPIL_EDGE_W"])
        self.prect=self.pupil.get_rect(center=(self.cx,self.cy))
        self.openness=1.0
        self.tx=self.ty=0.0
        self.open_target=1.0

    def set_targets_from_bytes(self, bx, by, bblink, bpupil, biris=None):
        # 0..255 -> -1..+1 -> pixels
        ax = (bx/255.0)*2.0 - 1.0
        ay = (by/255.0)*2.0 - 1.0
        self.tx = ax*self.ampx
        self.ty = ay*self.ampy
        self.open_target = 1.0 - (bblink/255.0)
        self.scale_target = self.min_scale + (self.max_scale - self.min_scale)*(bpupil/255.0)
        if biris is not None:
            self.iris_strength_target = biris/255.0

    def update(self, dt):
        self.look_x,self.vx = smooth_damp(self.look_x, self.tx, self.vx, self.smooth, dt, self.maxspeed)
        self.look_y,self.vy = smooth_damp(self.look_y, self.ty, self.vy, self.smooth, dt, self.maxspeed)
        self.openness,_     = smooth_damp(self.openness, self.open_target, 0.0, CFG["SMOOTH_LID"], dt, 99)
        self.scale,self.sv  = smooth_damp(self.scale, self.scale_target, self.sv, CFG["SMOOTH_PUPIL"], dt, 10)
        self.iris_strength,self.iris_v = smooth_damp(self.iris_strength, self.iris_strength_target,
                                                     self.iris_v, CFG["SMOOTH_IRIS"], dt, 10)

        # Rebuild pupil als grootte wijzigt
        desired_pw=int(self.base_pw*self.scale)
        desired_ph=int(self.base_ph*self.scale)
        if abs(desired_pw-self.cur_pw)>=2 or abs(desired_ph-self.cur_ph)>=2:
            self.cur_pw, self.cur_ph = desired_pw, desired_ph
            self.pupil = make_pupil_surface(self.cur_pw, self.cur_ph, CFG["PUPIL_EDGE_W"])
            self.prect = self.pupil.get_rect(center=(self.cx,self.cy))

        # Rebuild iris/achtergrond als sterkte zichtbaar wijzigt
        if (self._last_iris_strength is None) or (abs(self.iris_strength - self._last_iris_strength) > 0.02):
            self.base,(self.cx,self.cy) = make_eye_base(self.w, self.h, strength=self.iris_strength)
            self._last_iris_strength = self.iris_strength

    def draw(self):
        self.scr.blit(self.base,(0,0))
        self.prect.center=(int(self.cx+self.look_x), int(self.cy+self.look_y))
        self.scr.blit(self.pupil, self.prect)
        draw_eyelids(self.scr, clamp(self.openness,0.0,1.0))

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="PLC UDP -> één oog per proces (radiale iris + pupilrand + iris-intensiteit)")
    ap.add_argument("--eye", choices=["left","right"], required=True)
    ap.add_argument("--monitor", type=int, default=0)
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--novsync", action="store_true")
    ap.add_argument("--borderless", action="store_true")
    ap.add_argument("--fullscreen", action="store_true")
    args = ap.parse_args()

    choose_driver()
    scr = open_window_on_monitor(args.monitor, args.width, args.height,
                                 vsync=not args.novsync,
                                 fullscreen=(not args.borderless) or args.fullscreen)
    pygame.display.set_caption(f"Kattenoog {args.eye} (monitor {args.monitor})")

    eye = Eye(scr, args.width, args.height)

    # UDP listener: accepteert 8 of 10 bytes
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.port))
    sock.setblocking(False)
    print(f"[{args.eye}] UDP :{args.port} verwacht 8 of 10 bytes:")
    print("   8  = Lx,Ly,Lblink,Lpupil, Rx,Ry,Rblink,Rpupil")
    print("   10 = bovenstaande + Liris,Riris (0..255)")

    # defaults
    eye.set_targets_from_bytes(128,128,0,128)

    clock = pygame.time.Clock()
    prev = time.perf_counter()
    running=True
    while running:
        for e in pygame.event.get():
            if e.type==pygame.QUIT: running=False
            if e.type==pygame.KEYDOWN and e.key in (pygame.K_q, pygame.K_ESCAPE): running=False

        # lees laatste pakket
        try:
            while True:
                data, _ = sock.recvfrom(64)
                n = len(data)
                if n >= 10:
                    Lx,Ly,Lb,Lp,Rx,Ry,Rb,Rp,Li,Ri = struct.unpack("10B", data[:10])
                    if args.eye == "left":
                        eye.set_targets_from_bytes(Lx,Ly,Lb,Lp, biris=Li)
                    else:
                        eye.set_targets_from_bytes(Rx,Ry,Rb,Rp, biris=Ri)
                elif n >= 8:
                    Lx,Ly,Lb,Lp,Rx,Ry,Rb,Rp = struct.unpack("8B", data[:8])
                    if args.eye == "left":
                        eye.set_targets_from_bytes(Lx,Ly,Lb,Lp)
                    else:
                        eye.set_targets_from_bytes(Rx,Ry,Rb,Rp)
                else:
                    break
        except BlockingIOError:
            pass

        now=time.perf_counter(); dt=max(0.0005, min(0.05, now-prev)); prev=now
        eye.update(dt)
        eye.draw()
        pygame.display.flip()
        if args.novsync: clock.tick(60)

    pygame.quit()

if __name__=="__main__":
    main()
