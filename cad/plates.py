#!/usr/bin/env python3
"""Verteilt die Teile auf Druckplatten (210×210, Anycubic i3 Mega S) und exportiert
pro Platte die positionierten STLs nach ../print/platten/<platte>/."""
import os
import shutil

import manifold3d
import numpy as np
import trimesh
from manifold3d import Manifold

import arad_parts as A

BED = 210.0
MARGIN_X = (8.0, 202.0)   # Skirt + Rand
MARGIN_Y = (10.0, 202.0)  # vorne liegt die Einstreichlinie (Y 1–2)
GAP = 4.0
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'print', 'platten')


def flat(m):
    bb = m.bounding_box()
    return m.translate([0, 0, -bb[2]])


def footprint(m):
    return m.project().offset(GAP / 2, manifold3d.JoinType.Round)


def stack_y(parts):
    """Bögen nacheinander in +Y schachteln (Form-genau, nicht nur Bounding Box)."""
    placed, fps = [], []
    for m in parts:
        m = flat(m)
        bb = m.bounding_box()
        m = m.translate([-(bb[0] + bb[3]) / 2, -bb[1], 0])
        y = 0.0
        if fps:
            prev = max(p.bounding_box()[4] for p in placed)
            y = prev - (m.bounding_box()[4] - m.bounding_box()[1]) - 1  # optimistisch starten
            y = max(y, min(p.bounding_box()[1] for p in placed))
            fp = footprint(m)
            while any((fp.translate([0, y]) ^ f).area() > 1e-3 for f in fps):
                y += 0.5
        m = m.translate([0, y, 0])
        placed.append(m)
        fps.append(footprint(m))
    return placed


def place(parts, cx, y0):
    xs0 = min(p.bounding_box()[0] for p in parts)
    xs1 = max(p.bounding_box()[3] for p in parts)
    ys0 = min(p.bounding_box()[1] for p in parts)
    return [p.translate([cx - (xs0 + xs1) / 2, y0 - ys0, 0]) for p in parts]


def center_on_bed(parts):
    xs0 = min(p.bounding_box()[0] for p in parts)
    xs1 = max(p.bounding_box()[3] for p in parts)
    ys0 = min(p.bounding_box()[1] for p in parts)
    ys1 = max(p.bounding_box()[4] for p in parts)
    cx = (MARGIN_X[0] + MARGIN_X[1]) / 2 - (xs0 + xs1) / 2
    cy = (MARGIN_Y[0] + MARGIN_Y[1]) / 2 - (ys0 + ys1) / 2
    out = [p.translate([cx, cy, 0]) for p in parts]
    check(out)
    return out


def check(parts):
    for p in parts:
        bb = p.bounding_box()
        if bb[0] < 2 or bb[3] > BED - 2 or bb[1] < 5 or bb[4] > BED - 2 or bb[5] > 200:
            raise SystemExit(f'Teil passt nicht aufs Bett: {bb}')
    fps = [p.project() for p in parts]
    for i in range(len(fps)):
        for j in range(i + 1, len(fps)):
            if (fps[i] ^ fps[j]).area() > 1e-3:
                raise SystemExit(f'Teile {i} und {j} überlappen')


def grid(parts, x0, y0, x1, y1, gap=GAP):
    """Einfaches Reihen-Packen nach Bounding Box in einem Rechteck (Bettkoordinaten)."""
    out, x, y, row_h = [], x0, y0, 0.0
    for m in parts:
        m = flat(m)
        bb = m.bounding_box()
        w, h = bb[3] - bb[0], bb[4] - bb[1]
        if x + w > x1:
            x, y, row_h = x0, y + row_h + gap, 0.0
        if y + h > y1:
            raise SystemExit('Kleinteile passen nicht in den Bereich')
        out.append(m.translate([x - bb[0], y - bb[1], 0]))
        x += w + gap
        row_h = max(row_h, h)
    return out


def export(plate, named):
    d = os.path.join(OUT, plate)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    for i, (name, m) in enumerate(named):
        me = m.to_mesh()
        tm = trimesh.Trimesh(np.asarray(me.vert_properties)[:, :3], np.asarray(me.tri_verts))
        tm.export(os.path.join(d, f'{i:02d}_{name}.stl'))
    bb = [min(m.bounding_box()[k] for _, m in named) for k in (0, 1)] + \
         [max(m.bounding_box()[k] for _, m in named) for k in (3, 4, 5)]
    print(f'  {plate:32s} {len(named):2d} Teile  X {bb[0]:5.1f}–{bb[2]:5.1f}  Y {bb[1]:5.1f}–{bb[3]:5.1f}  H {bb[4]:4.1f}')


def main():
    std = A.segment('std')
    cam = A.segment('cam')
    outlet = A.segment('outlet')
    housing = A.cam_housing()
    lid = A.cam_lid()
    clip = A.mount_clip()
    bar = A.cable_bar()
    jt = A.joint_test()
    ebox, posts = A.ebox()
    elid = A.ebox_lid(posts)

    print('Platten ->', os.path.normpath(OUT))

    # 00 – Passtest (≈1,5 h): Kameragehäuse + Deckel + 2 Verbinderstücke
    p = place(stack_y([jt, jt]), 105, 12)
    top = max(m.bounding_box()[4] for m in p)
    small = grid([housing, lid], 50, top + 8, 200, 200)
    parts = [('verbinder_test', p[0]), ('verbinder_test', p[1]), ('kamera_gehaeuse', small[0]), ('kamera_deckel', small[1])]
    check([m for _, m in parts])
    export('00_passtest', parts)

    # 01/02 – je 4 Standardsegmente
    for plate in ('01_ring_standard_1-4', '02_ring_standard_5-8'):
        p = center_on_bed(stack_y([std] * 4))
        export(plate, [('ring_standard', m) for m in p])

    # 03 – Auslasssegment + Kamerasegment 1
    p = center_on_bed(stack_y([outlet, cam]))
    export('03_ring_auslass_kamera_1', [('ring_auslass', p[0]), ('ring_kamera', p[1])])

    # 04 – Kamerasegmente 2 + 3
    p = center_on_bed(stack_y([cam, cam]))
    export('04_ring_kamera_2-3', [('ring_kamera', m) for m in p])

    # 05 – Kleinteile: 3 Kameragehäuse, 3 Deckel, 4 Halteclips, 10 Kabelstege
    small = grid([housing] * 3 + [lid] * 3 + [clip] * 4 + [bar] * 10, 10, 12, 200, 200)
    names = ['kamera_gehaeuse'] * 3 + ['kamera_deckel'] * 3 + ['halteclip'] * 4 + ['kabelsteg'] * 10
    check(small)
    export('05_kleinteile', list(zip(names, small)))

    # 06 – Elektronikbox (Pi Zero 2 W) + Deckel
    p = grid([ebox, elid], 30, 20, 200, 200, gap=8)
    check(p)
    export('06_elektronikbox', [('elektronikbox', p[0]), ('elektronikbox_deckel', p[1])])


if __name__ == '__main__':
    main()
