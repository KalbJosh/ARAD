#!/usr/bin/env python3
"""Schraubenloser Surround-Halter V1. Maße sind Prototyp-Annahmen, mm.

Weltachsen: X vom Scheibenrand radial nach außen, Y tangential,
Z vom Surround nach vorne. Druck auf der tangentialen Seite.
"""
import json
from pathlib import Path
import numpy as np
import trimesh
from manifold3d import Manifold, CrossSection

OUT = Path(__file__).resolve().parents[1] / 'print/kamera_einfach/prototyp'
PCB = 38.0
PCB_T = 1.6
GAP = PCB_T + .4
HALF = (PCB + .4) / 2
WIDTH = PCB + 4.8
ANGLE = 20.0


def box(x0, x1, y0, y1, z0, z1):
    return Manifold.cube((x1-x0, y1-y0, z1-z0)).translate((x0,y0,z0))


def section(points, width=WIDTH):
    # XY contour -> world XZ, extrusion -> -Y.
    return CrossSection([points]).extrude(width).rotate((90,0,0)).translate((0,width/2,0))


def camera_transform(m):
    return m.rotate((0,-ANGLE,0)).translate((40,0,110))


def create():
    h = WIDTH/2
    # Tapered 28-mm tongue, flat shoulder and ribbed cantilever.
    tongue = section([(0,-28),(.8,-28),(2,-23),(2,4),(0,4)])
    foot = box(0,60,-h,h,0,4)
    arm = section([(45,4),(60,4),(60,104),(53,104),(53,18)])
    # Open camera front, 7.2-mm rear component clearance for assumed PCB.
    head = box(8,11,-h,h,-23,23)
    for a,b in [(-23,-HALF+1),(HALF-1,23)]:
        rail = box(-3,11,-h,h,a,b)
        rail -= box(-GAP/2,GAP/2,-HALF,h+1,-HALF,HALF)
        head += rail
    head += box(-3,11,-h,-HALF,-23,23)
    # Shorten open rails to board edge, so cap seats against the PCB edge.
    head -= box(-4,12,HALF,h+1,-24,24)
    # Clearance for the cap sleeves at the tangential end of the arm.
    arm -= camera_transform(box(-5,14,HALF-6.3,h+1,-25,25))
    holder = tongue + foot + arm + camera_transform(head)
    # C-shaped friction sleeves wrap the outer rail surfaces; their inward
    # sides stay open so that they do not foul the PCB in its grooves.
    cap = box(-4.8,12.8,HALF,HALF+2,-24.8,24.8)
    for sign in (-1,1):
        a,b = (HALF-1,24.8) if sign==1 else (-24.8,-HALF+1)
        cap += box(-4.8,-3.15,HALF-6,HALF+.1,a,b)
        cap += box(11.15,12.8,HALF-6,HALF+.1,a,b)
        a,b = (23.15,24.8) if sign==1 else (-24.8,-23.15)
        cap += box(-4.8,12.8,HALF-6,HALF+.1,a,b)
        # Small ribs give 0.10-mm nominal interference, only at outer edge.
        a,b = (21.5,23) if sign==1 else (-23,-21.5)
        cap += box(-3.2,-2.9,HALF-3,HALF+.1,a,b)
    return holder, camera_transform(cap), cap


def mesh(m):
    x=m.to_mesh()
    return trimesh.Trimesh(vertices=np.array(x.vert_properties)[:,:3],faces=np.array(x.tri_verts))


def grounded(m):
    bb=m.bounding_box()
    return m.translate((-bb[0],-bb[1],-bb[2]))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    holder, assembled_cap, cap = create()
    # Both parts have their broad side on the bed. Camera grooves run upward;
    # the cap's crossbar prints first, its six sleeve walls build above it.
    hp=grounded(holder.rotate((90,0,0)))
    cp=grounded(cap.rotate((-90,0,0)))
    hb=hp.bounding_box()
    cp=cp.translate((hb[3]+12,25,0))
    plate=hp+cp
    coupon=section([(0,-28),(.8,-28),(2,-23),(2,0),(14,0),(14,4),(0,4)])
    coupon=grounded(coupon.rotate((90,0,0)))
    data={'prototype':True,'assumptions':{'pcb_mm':[PCB,PCB,PCB_T],
          'groove_mm':GAP,'tongue_max_mm':2,'insertion_mm':28,
          'camera_center_above_surround_mm':110,'tilt_deg':ANGLE},'parts':{}}
    for name,m in [('HALTER',hp),('KAPPE',grounded(cp)),('KAM1',plate),('KLEMM',coupon)]:
        t=mesh(m)
        assert t.is_watertight and t.is_volume
        components=len(t.split()); assert components==(2 if name=='KAM1' else 1)
        assert np.all(t.extents<=np.array([190,190,200]))
        # Cura CLI uses the STL origin; center XY explicitly before slicing.
        t.apply_translation([-t.bounds[:,0].mean(),-t.bounds[:,1].mean(),-t.bounds[0,2]])
        t.export(OUT/(name+'.stl'))
        data['parts'][name]={'dimensions_mm':t.extents.tolist(),'volume_mm3':t.volume,
                             'closed':bool(t.is_watertight),'components':components}
    # Camera clearance: board must not intersect holder; cap interference is
    # deliberately confined to tiny friction ribs outside the PCB perimeter.
    board=camera_transform(box(-PCB_T/2,PCB_T/2,-PCB/2,PCB/2,-PCB/2,PCB/2))
    data['pcb_intersection_mm3']=(holder^board).volume()
    data['cap_pcb_intersection_mm3']=(assembled_cap^board).volume()
    data['cap_friction_intersection_mm3']=(holder^assembled_cap).volume()
    assert data['pcb_intersection_mm3']<1e-6
    assert data['cap_pcb_intersection_mm3']<1e-6
    assert 0 < data['cap_friction_intersection_mm3'] < 5
    (OUT/'geometrie.json').write_text(json.dumps(data,indent=2)+'\n')
    mesh(holder).export(OUT/'montage_halter.stl')
    mesh(assembled_cap).export(OUT/'montage_kappe.stl')
    print(json.dumps(data,indent=2))


if __name__=='__main__': main()
