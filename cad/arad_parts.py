#!/usr/bin/env python3
"""ARAD – parametrische Druckteile (Ring, Kameragehäuse, Clips, Elektronikbox für Pi Zero 2 W).

Alle Maße in mm. Koordinaten der Ringteile: Druckbett = Vorderseite des Rings (z=0),
z wächst Richtung Scheibe/Surround (z=DEPTH liegt auf dem Surround auf).

Start:  ../.venv/bin/python arad_parts.py      -> schreibt STLs nach ../print/stl/
Nach Änderung der Parameter danach ../print/slice.sh laufen lassen.
"""
import math
import os
import sys

import numpy as np
import trimesh
from manifold3d import CrossSection, Manifold

# ============================ PARAMETER ============================
# Ring
R_IN = 250.0          # Innenradius (Scheibe Ø451 -> 24,5 mm Luft)
R_OUT = 290.0         # Außenradius
DEPTH = 50.0          # Tiefe Vorderkante -> Surround
N_SEG = 12            # 12 × 30° passt aufs 210er Bett
WALL = 2.0            # Wandstärke Außen-/Mittelwand
FRONT = 2.4           # Stärke Frontplatte
R_MID = 266.0         # Mittelwand (innen) – dazwischen Kabelkanal
MID_H = 20.0          # Höhe Mittelwand (niedrig = schneller Druck; Kabel halten die Kabelstege)
LED_RISE = 16.0       # LED-Schräge (45°) von (R_IN,0) bis (R_IN+16,16)

# Verbinder zwischen Segmenten
TAB_R = (273.0, 285.0)   # radialer Bereich der Lasche
TAB_LEN = 14.0
TAB_H = 6.0
CLR = 0.25               # Spiel
NUT_AF = 5.8             # M3-Mutter Schlüsselweite 5,5 + Spiel
NUT_H = 2.6              # M3-Mutter 2,4 hoch + Spiel
PILOT_D = 2.6            # Vorbohrung: M3-Schraube schneidet direkt ins Plastik
SCREW_D = 3.4            # M3 Durchgang

# Kamera (OV9732 Autodarts-Set = 32×32 mm Platine) – NACHMESSEN!
PCB_W = 32.0
PCB_H = 32.0
PCB_T = 1.6
APERTURE = 16.0          # quadratische Öffnung für den Objektivhalter
FRONT_GAP = 4.0          # Platz zwischen Platine und Frontwand (SMD-Teile)
BACK_GAP = 4.4           # Platz hinter Platine (Stecker)
CAM_WALL = 2.2
PIVOT_R = 228.0          # Schwenkachse radial
PIVOT_Z = 27.0           # Schwenkachse Abstand zur Ringvorderkante

# Elektronikbox (Raspberry Pi Zero 2 W + MOSFET + DC-Buchse)
BOX_L, BOX_W, BOX_H = 110.0, 48.0, 24.0   # Innenmaße
BOX_WALL = 2.4

SEG_FN = 180  # Kreisauflösung für den Vollkreis
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'print', 'stl')


# ============================ HILFEN ============================
def box(x0, x1, y0, y1, z0, z1):
    return Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def cyl_z(x, y, z0, z1, d, fn=48):
    return Manifold.cylinder(z1 - z0, d / 2, circular_segments=fn).translate([x, y, z0])


def cyl_y(x, z, y0, y1, d, fn=48):
    """Zylinder entlang Y (lokal: tangential)."""
    return Manifold.cylinder(y1 - y0, d / 2, circular_segments=fn).rotate([-90, 0, 0]).translate([x, y0, z])


def cyl_x(y, z, x0, x1, d, fn=48):
    return Manifold.cylinder(x1 - x0, d / 2, circular_segments=fn).rotate([0, 90, 0]).translate([x0, y, z])


def at_angle(m, deg):
    """Lokales Teil (X=radial, Y=tangential gegen Uhrzeigersinn) an Winkel deg setzen."""
    return m.rotate([0, 0, deg])


def union(ms):
    ms = [m for m in ms if m is not None]
    return Manifold.batch_boolean(ms, manifold3d_op('Add')) if len(ms) > 1 else ms[0]


def manifold3d_op(name):
    import manifold3d
    return getattr(manifold3d.OpType, name)


def save(m, name):
    os.makedirs(OUT, exist_ok=True)
    mesh = m.to_mesh()
    tm = trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts))
    path = os.path.join(OUT, name + '.stl')
    tm.export(path)
    bb = m.bounding_box()
    print(f'  {name:28s} {bb[3]-bb[0]:6.1f} x {bb[4]-bb[1]:6.1f} x {bb[5]-bb[2]:5.1f} mm  '
          f'{m.volume()/1000:6.1f} cm³  watertight={tm.is_watertight}')
    return path


# ============================ RING ============================
SEG_DEG = 360.0 / N_SEG
A_END = 90 - SEG_DEG / 2   # Ende A (Aufnahme)  – Segmentmitte liegt auf +Y
B_END = 90 + SEG_DEG / 2   # Ende B (Lasche)


def profile(depth=DEPTH):
    r0, r1 = R_IN, R_OUT
    polys = [
        [(r0, 0), (r1, 0), (r1, FRONT), (r0 + 3.5, FRONT)],                    # Frontplatte
        [(r1 - WALL, 0), (r1, 0), (r1, depth), (r1 - WALL, depth)],            # Außenwand
        [(R_MID, 0), (R_MID + WALL, 0), (R_MID + WALL, min(MID_H, depth)), (R_MID, min(MID_H, depth))],  # Mittelwand
        [(r0, 0), (r0 + 3.5, 0), (R_MID, LED_RISE - 3.5), (R_MID, LED_RISE)],  # LED-Schräge 45°
        [(r0 - 1.5, 0), (r0 + 0.5, 0), (r0 + 1.6, 1.1), (r0 - 0.2, 2.9)],      # Lippe unten am LED-Streifen
    ]
    return CrossSection(polys)


def ring_body(deg=SEG_DEG, depth=DEPTH):
    cs = profile(depth)
    n = max(8, int(SEG_FN * deg / 360))
    return Manifold.revolve(cs, n, deg).rotate([0, 0, 90 - deg / 2])


def joint_tab(end_deg, h_total):
    """Lasche an Ende B, ragt in +tangential über das Ende hinaus."""
    rc = (TAB_R[0] + TAB_R[1]) / 2
    tab = box(TAB_R[0], TAB_R[1], -2, TAB_LEN, 0, TAB_H)
    # M3×10 von hinten endet 0,95 mm über der Front -> Bohrung bis 0,6 mm, Front bleibt geschlossen.
    # Oben Sechskant-Tasche für die M3-Mutter.
    tab = tab - cyl_z(rc, TAB_LEN / 2, 0.6, TAB_H + 1, SCREW_D)
    nut = Manifold.cylinder(NUT_H + 1, NUT_AF / 2 / math.cos(math.radians(30)), circular_segments=6)
    tab = tab - nut.translate([rc, TAB_LEN / 2, TAB_H - NUT_H])
    return at_angle(tab, end_deg)


def joint_socket(body, end_deg):
    """Aussparung + Brücke mit Schraubloch an Ende A."""
    rc = (TAB_R[0] + TAB_R[1]) / 2
    cut = box(TAB_R[0] - CLR, TAB_R[1] + CLR, -3, TAB_LEN + CLR, -1, TAB_H + CLR)
    # Block zwischen den Wänden bis zur Frontplatte -> nur kurze Brücke (12,5 mm) über der Aufnahme
    pad = box(R_MID + WALL - 0.1, R_OUT - WALL + 0.1, 0, TAB_LEN + 4, 0, TAB_H + CLR + 4.7)
    hole = cyl_z(rc, TAB_LEN / 2, TAB_H - 1, TAB_H + 20, SCREW_D)
    body = body + at_angle(pad, end_deg)
    body = body - at_angle(cut, end_deg)
    return body - at_angle(hole, end_deg)


def clip_features(body, depth=DEPTH):
    """Kerbe hinten in der Außenwand + radiale Bohrung für Halteclip (Segmentmitte)."""
    notch = box(R_OUT - WALL - 1, R_OUT + 1, -10.5, 10.5, depth - 2.5, depth + 1)
    hole = cyl_x(0, depth - 12, R_OUT - WALL - 2, R_OUT + 2, SCREW_D)
    return body - at_angle(notch + hole, 90)


def segment(kind='std'):
    body = ring_body()
    body = body + joint_tab(B_END, DEPTH)
    body = joint_socket(body, A_END)
    if kind in ('std', 'cam'):
        body = clip_features(body)
    if kind == 'outlet':
        slot = box(R_OUT - WALL - 1, R_OUT + 1, -15, 15, DEPTH - 25, DEPTH + 1)
        body = body - at_angle(slot, 90)
    if kind == 'cam':
        body = body + at_angle(cam_mount(), 90)
    return body


# ---------- Kamerahalter am Ring ----------
def cam_dims():
    wp, hp = PCB_W + 0.4, PCB_H + 0.4
    ox, oy = wp + 2 * CAM_WALL, hp + 2 * CAM_WALL
    dep = 2 + FRONT_GAP + PCB_T + 0.4 + BACK_GAP + 2
    return wp, hp, ox, oy, dep


BOSS_L, BOSS_D = 3.5, 9.0
EAR_T = 4.5


def cam_mount():
    wp, hp, ox, oy, dep = cam_dims()
    gap_half = ox / 2 + BOSS_L + 0.4
    ear_out = gap_half + EAR_T
    parts = [box(PIVOT_R - 10, R_IN + 3, -ear_out, ear_out, 0, 6)]  # Arm an der Ringvorderkante
    for s in (-1, 1):
        y0, y1 = sorted([s * gap_half, s * ear_out])
        ear = box(PIVOT_R - 8, PIVOT_R + 8, y0, y1, 0, PIVOT_Z) + cyl_y(PIVOT_R, PIVOT_Z, y0, y1, 16)
        ear = ear - cyl_y(PIVOT_R, PIVOT_Z, y0 - 1, y1 + 1, SCREW_D)
        # Verstärkung Ohr -> Ring
        rib = box(PIVOT_R + 8 - 0.01, R_IN + 1, y0, y1, 0, 12)
        parts += [ear, rib]
    return union(parts)


def cam_housing():
    """Kameragehäuse, gedruckt mit Frontseite (Objektiv) aufs Bett."""
    wp, hp, ox, oy, dep = cam_dims()
    body = box(-ox / 2, ox / 2, -oy / 2, oy / 2, 0, dep)
    zc = dep / 2
    for s in (-1, 1):
        # Tropfenform (45°) -> ohne Stützen druckbar
        x0, x1 = sorted([s * ox / 2 - s * 0.01, s * (ox / 2 + BOSS_L)])
        boss = cyl_x(0, zc, x0, x1, BOSS_D)
        tip = box(x0, x1, -0.01, 0.01, max(0.0, zc - BOSS_D / 2 * math.sqrt(2)), zc)
        body = body + Manifold.hull(boss + tip)
    # Innenraum
    body = body - box(-APERTURE / 2, APERTURE / 2, -APERTURE / 2, APERTURE / 2, -1, 2.01)
    body = body - box(-wp / 2 + 1.5, wp / 2 - 1.5, -hp / 2 + 1.5, hp / 2 - 1.5, 2, 2 + FRONT_GAP + 0.01)
    body = body - box(-wp / 2, wp / 2, -hp / 2, hp / 2, 2 + FRONT_GAP, dep + 1)
    # Gewinde-Vorbohrung für M3 (selbstschneidend) in den Zapfen
    for s in (-1, 1):
        x_out = s * (ox / 2 + BOSS_L + 0.1)
        x_in = s * (wp / 2 + 0.6)
        body = body - cyl_x(0, zc, min(x_in, x_out), max(x_in, x_out), 2.6)
    # Kerbe für Kabel an der Rückseite (unten)
    body = body - box(-5, 5, -oy / 2 - 1, -hp / 2 + 0.01, dep - 2.5, dep + 1)
    return body


def cam_lid():
    """Deckel hinten, drückt Platine gegen die Auflage."""
    wp, hp, ox, oy, dep = cam_dims()
    w, h = wp - 0.3, hp - 0.3
    plate = box(-w / 2, w / 2, -h / 2, h / 2, 0, 2)
    rib_len = BACK_GAP - 0.1
    ribs = box(-w / 2, -w / 2 + 1.4, -h / 2 + 2, h / 2 - 2, 2, 2 + rib_len) + \
        box(w / 2 - 1.4, w / 2, -h / 2 + 2, h / 2 - 2, 2, 2 + rib_len)
    lid = plate + ribs
    lid = lid - box(-5, 5, -h / 2 - 1, -h / 2 + 5, -1, 10)   # Kabelschlitz
    return lid


# ---------- Clips / Stege ----------
def mount_clip():
    """Halteclip: greift über die Außenwand (Kerbe), Lasche liegt auf dem Surround,
    Holzschraube durch Langloch + Surround in die Wand. Profil im (r,z), 20 mm breit."""
    w = 20.0
    t = 2.0
    ri, ro = R_OUT - WALL - 0.2, R_OUT + 0.2
    z0, z1 = DEPTH - 20, DEPTH
    polys = [
        [(ri - t, z0), (ri, z0), (ri, z1 - 2.5), (ri - t, z1 - 2.5)],              # innerer Schenkel
        [(ro, z0), (ro + t + 1, z0), (ro + t + 1, z1 - 2.5), (ro, z1 - 2.5)],      # äußerer Schenkel
        [(ri - t, z1 - 2.5), (R_OUT + 50, z1 - 2.5), (R_OUT + 50, z1), (ri - t, z1)],  # Steg + Lasche
    ]
    prof = CrossSection(polys)
    m = Manifold.extrude(prof, w).translate([0, 0, -w / 2])  # X=r, Y=z, Z=tangential
    # Schraubloch M3 quer durch Schenkel (auf z = DEPTH-12)
    m = m - Manifold.cylinder(40, SCREW_D / 2, circular_segments=32).rotate([0, 90, 0]).translate([ri - t - 5, DEPTH - 12, 0])
    # Langloch Ø5 für Holzschraube
    slot = Manifold.hull(
        Manifold.cylinder(10, 2.6, circular_segments=32).rotate([90, 0, 0]).translate([R_OUT + 18, z1 + 5, 0]) +
        Manifold.cylinder(10, 2.6, circular_segments=32).rotate([90, 0, 0]).translate([R_OUT + 42, z1 + 5, 0]))
    m = m - slot
    m = m.translate([-(R_OUT + 20), -(DEPTH - 10), w / 2])
    return m  # liegt flach (Profil in XY), 20 mm hoch


def cable_bar():
    """Kabelsteg: klemmt quer im Kabelkanal und hält die Kabel drin."""
    w = (R_OUT - WALL) - (R_MID + WALL) - 0.3
    m = box(0, w, 0, 10, 0, 2.4)
    for x in (-0.35, w - 0.25):
        m = m + box(x, x + 0.6, 3, 7, 0, 2.4)
    return m


# ---------- Elektronikbox ----------
ZERO_X0, ZERO_Y0 = 11.0, 3.0  # Pi Zero 2 W (65×30), frei von den Eckpfosten
STANDOFF = 4.0


def ebox():
    """Box für Pi Zero 2 W + MOSFET-Modul + DC-Buchse. Der Zero wird über seinen 5V-Pin
    aus dem LED-Netzteil versorgt -> keine USB-Öffnungen nötig."""
    L, W, H, t = BOX_L, BOX_W, BOX_H, BOX_WALL
    b = box(-t, L + t, -t, W + t, -t, H) - box(0, L, 0, W, 0, H + 1)
    # Zero-Abstandshalter (58×23) mit Stift Ø2,3 – Platine aufstecken, Tropfen Heißkleber
    for hx in (3.5, 61.5):
        for hy in (3.5, 26.5):
            x, y = ZERO_X0 + hx, ZERO_Y0 + hy
            b = b + cyl_z(x, y, -0.01, STANDOFF, 6.0) + cyl_z(x, y, STANDOFF - 0.01, STANDOFF + 2.5, 2.3, 24)
    # Anschlag für das MOSFET-Modul (35×16, wird mit Klebepad fixiert)
    mx0 = ZERO_X0 + 65 + 4
    b = b + box(mx0 - 1.5, mx0, 4, 40, -0.01, 3) + box(mx0 + 17.5, mx0 + 19, 4, 40, -0.01, 3)
    # Eckpfosten mit Einschmelzmuttern für den Deckel
    posts = []
    for x, y in ((0, 0), (L, 0), (0, W), (L, W)):
        cx, cy = min(max(x, 4.5), L - 4.5), min(max(y, 4.5), W - 4.5)
        posts.append((cx, cy))
        b = b + box(cx - 4.5, cx + 4.5, cy - 4.5, cy + 4.5, -0.01, H - 0.01) - cyl_z(cx, cy, H - 9, H + 1, PILOT_D)
    # +X: DC-Buchse (Ø8) + LED-Kabel (Ø7)
    b = b - cyl_x(W / 2 - 11, 12, L - 1, L + t + 1, 8)
    b = b - cyl_x(W / 2 + 11, 12, L - 1, L + t + 1, 7)
    # Wandbefestigung (Boden) Ø4,5 mit Senkung
    for x, y in ((ZERO_X0 + 32.5, ZERO_Y0 + 15), (mx0 + 9, 44.0)):   # unter dem Zero / neben dem MOSFET
        b = b - cyl_z(x, y, -t - 1, 1, 4.6)
        b = b - Manifold.cylinder(2.4, 2.3, 4.6, circular_segments=40).translate([x, y, -t + 0.01])
    # Lüftungsschlitze Seitenwand +Y
    for i in range(7):
        x = 14 + i * 12
        b = b - box(x, x + 4, W - 1, W + t + 1, 6, H - 6)
    return b.translate([t, t, t]), posts


def ebox_lid(posts):
    L, W, t = BOX_L, BOX_W, BOX_WALL
    lid = box(-t, L + t, -t, W + t, 0, 2.4)
    rim = box(0.3, L - 0.3, 0.3, W - 0.3, 2.4, 5.4) - box(1.5, L - 1.5, 1.5, W - 1.5, 2.3, 6)
    for cx, cy in posts:
        rim = rim - box(cx - 5, cx + 5, cy - 5, cy + 5, 0, 10)
    lid = lid + rim
    for cx, cy in posts:
        lid = lid - cyl_z(cx, cy, -1, 5, SCREW_D) - cyl_z(cx, cy, -1, 1.8, 6.2)
    for i in range(8):
        x = 15 + i * 10
        lid = lid - box(x, x + 3, 12, W - 12, -1, 3)
    return lid.translate([t, t, 0])


# ---------- Passtest ----------
def joint_test():
    deg = 8.0
    d = 14.0
    body = ring_body(deg, d)
    a_end, b_end = 90 - deg / 2, 90 + deg / 2
    body = body + joint_tab(b_end, d)
    body = joint_socket(body, a_end)
    return body


# ============================ PLATTEN ============================
def to_bed(m):
    """Teil auf z=0 setzen und X/Y auf 0 zentrieren (Bounding Box)."""
    bb = m.bounding_box()
    return m.translate([-(bb[0] + bb[3]) / 2, -(bb[1] + bb[4]) / 2, -bb[2]])


def main():
    print('Erzeuge STLs ->', os.path.normpath(OUT))
    parts = {
        'ring_segment_standard': segment('std'),
        'ring_segment_kamera': segment('cam'),
        'ring_segment_auslass': segment('outlet'),
        'kamera_gehaeuse': cam_housing(),
        'kamera_deckel': cam_lid(),
        'halteclip': mount_clip(),
        'kabelsteg': cable_bar(),
        'passtest_verbinder': joint_test(),
    }
    box_m, posts = ebox()
    parts['elektronikbox'] = box_m
    parts['elektronikbox_deckel'] = ebox_lid(posts)
    for name, m in parts.items():
        if m.status().name != 'NoError' or m.is_empty():
            sys.exit(f'Fehler bei {name}: {m.status()}')
        save(to_bed(m), name)
    return parts


if __name__ == '__main__':
    main()
