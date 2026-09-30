#!/usr/bin/env python3
"""Kleiner Maßtest für die Kameraplatine; noch keine Kamera-Klemmhalterung.

Aufruf: .venv/bin/python cad/kamera_passtest.py [Platinenbreite_mm]
Das Foto legt ungefähr 38 mm nahe; dieser Wert ist NICHT nachgemessen.
"""
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import Manifold

OUT = Path(__file__).resolve().parents[1] / 'print' / 'kamera_einfach'


def box(x, y, z, dx, dy, dz):
    return Manifold.cube((dx, dy, dz)).translate((x, y, z))


def main():
    pcb = float(sys.argv[1]) if len(sys.argv) > 1 else 38.0
    if not 20 <= pcb <= 60:
        raise ValueError('Platinenbreite muss zwischen 20 und 60 mm liegen')
    clearance = 0.4  # Gesamtspiel, 0,2 mm je Seite
    inner = pcb + clearance
    wall = 2.0
    outer = inner + 2 * wall
    # Offener Rahmen ohne Boden: keine Berührung mit Bauteilen auf der Rückseite.
    # Kamera beim Prüfen von Hand halten. Keine Halte- oder Rastfunktion!
    part = box(0, 0, 0, outer, outer, 3.0) - box(wall, wall, -1, inner, inner, 5)
    mesh = part.to_mesh()
    tm = trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts))
    assert tm.is_watertight and tm.is_volume and len(tm.split()) == 1
    OUT.mkdir(parents=True, exist_ok=True)
    tm.export(OUT / 'KAMTEST.stl')
    data = {'purpose': 'Maßlehre, keine Halterung', 'pcb_assumed_mm': pcb,
            'opening_mm': inner, 'outside_mm': outer, 'height_mm': 3,
            'watertight': bool(tm.is_watertight), 'components': len(tm.split()),
            'volume_mm3': float(tm.volume)}
    (OUT / 'geometrie.json').write_text(json.dumps(data, indent=2) + '\n')
    print(json.dumps(data, indent=2))


if __name__ == '__main__':
    main()
