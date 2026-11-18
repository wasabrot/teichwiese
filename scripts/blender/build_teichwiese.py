"""Teichwiese – 3D-Modell für Marketing und Website (Blender 4.2+ / 5.x).

Aufbau:
  python3 scripts/blender/fetch_context.py             # Umgebungsdaten laden (einmalig)
  blender -b -P scripts/blender/build_teichwiese.py -- [Optionen]

Optionen:
  --quick            kleine Auflösung, wenige Samples (Vorschau)
  --shots a,b        nur diese Kameras rendern (Standard: alle)
  --no-render        nur Szene bauen und speichern
  --glb              zusätzlich docs/assets/3d/teichwiese.glb exportieren
  --tag v5           Ausgabe als modell-<name>-v5.jpg / teichwiese-v5.glb (neue Variante, alte bleiben)

Grundlage der Gebäude: Plan "22-029_002 Entwurf GR SN", Entwurf 3 vom 25.10.2025
(IGW Baumanagement): Grundrisse EG/OG, Systemschnitt, Übersicht M 1:1000.
Bauteil 2 ist spiegelgleich zu Bauteil 1; für Bauteil 3 und 4 liegen keine
Grundrisse vor, sie werden mit demselben Gebäudetyp angenommen. Gestaltung
(Fassaden, Holzlamellen, PV, Bepflanzung) folgt den vorhandenen Renderings.
Lage und Zufahrt: verkehrstechnische Stellungnahme ZT Fruhmann vom 14.12.2023 ("TW Einfahrt"):
Grundstück östlich der LB54, nördlich an Gst. 105 gegenüber Billa; eine Zufahrt als vierter
Knotenarm gegenüber der geplanten Aufschließung West.
Das Ergebnis ist eine Visualisierung, kein Nachweis von Ausstattung oder Bauzustand.
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector, noise

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "build" / "3d"
IMG_OUT = ROOT / "docs" / "assets" / "images"
GLB_OUT = ROOT / "docs" / "assets" / "3d" / "teichwiese.glb"  # mit --tag: teichwiese<TAG>.glb
LOGO = ROOT / "docs" / "assets" / "brand" / "teichwiese-obstbaeume.png"
FONT = ROOT / "docs" / "assets" / "fonts" / "NunitoSans-ExtraBold.ttf"

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
QUICK = "--quick" in argv
NO_RENDER = "--no-render" in argv
DO_GLB = "--glb" in argv
SHOTS = None
TAG = ""  # --tag v5 → modell-<name>-v5.jpg / teichwiese-v5.glb, ältere Varianten bleiben unverändert
if "--tag" in argv:
    TAG = "-" + argv[argv.index("--tag") + 1]
if "--shots" in argv:
    SHOTS = argv[argv.index("--shots") + 1].split(",")

random.seed(54)
META = json.loads((DATA / "meta.json").read_text())
EXT, INNER, FAR = META["extent"], META["inner"], META["far"]
Z0 = 366.0  # m ü. A. → Blender z = 0

# Planrahmen = Übersicht M 1:1000 so wie gezeichnet: B54 unten, Grundstück darüber, rechts Gst. 105.
# Das Grundstück liegt ÖSTLICH der B54 (Gst. 110 ff., Verkehrsgutachten Fruhmann 12/2023).
# pu entlang der B54, positiv Richtung SSW (Ortszentrum/Billa); pv von der B54 weg Richtung OSO.
# Ursprung = Südwestecke an der B54 (Grenze zu Gst. 105, gegenüber der Nordkante Billa).
# Bauteil 1+2 liegen damit im Süden (Ortsseite), Bauteil 3 und 4 im Norden.
# Lage an der Digitalen Katastralmappe (BEV, WMS DKM_GST) ausgerichtet: Grundstücksgrenze des Plans
# per Chamfer-Fit auf die Katastergrenzen gelegt (Median-Abweichung ca. 3 cm).
PLAN_ROT = math.radians(258.05)  # pu zeigt nach SSW (Ortszentrum), pv nach OSO
PLAN_T = (1.48, -169.79)
PX_PER_M = 5.673  # Übersicht M 1:1000, gerastert


def plan_px(u, v):
    return ((u - 1600) / PX_PER_M, -(v - 525) / PX_PER_M)


SITE = np.array([plan_px(u, v) for u, v in [
    (100, 215), (276, 205), (276, 241), (287, 236), (474, 203), (528, 193), (629, 198), (710, 203),
    (726, 203), (792, 196), (845, 190), (940, 173), (1087, 148), (1350, 143), (1360, 143),
    (1553, 163), (1655, 195), (1600, 525), (1480, 521), (850, 521), (593, 529), (533, 524),
    (311, 539), (133, 545)]])

# Höhen (relativ zu Z0, aus DGM am Standort): Bauteile 1+2 im Süden auf Ebene A (Urgelände ca. -1,3),
# Bauteile 3+4 im Norden auf Ebene B (Urgelände ca. -0,4), Rampe in der Lücke dazwischen
LEVEL_A, LEVEL_B = -1.0, -0.2
RAMP = (-140.0, -118.0)
RAMP_CUTS = [RAMP[0] + i * 2.0 for i in range(12)]


def zl(pu):
    t = np.clip((np.asarray(pu, float) - RAMP[0]) / (RAMP[1] - RAMP[0]), 0, 1)
    t = t * t * (3 - 2 * t)
    return LEVEL_B + (LEVEL_A - LEVEL_B) * t


def plan_to_world(pu, pv):
    c, s = math.cos(PLAN_ROT), math.sin(PLAN_ROT)
    return (pu * c - pv * s + PLAN_T[0], pu * s + pv * c + PLAN_T[1])


def world_to_plan(x, y):
    c, s = math.cos(PLAN_ROT), math.sin(PLAN_ROT)
    dx, dy = np.asarray(x) - PLAN_T[0], np.asarray(y) - PLAN_T[1]
    return dx * c + dy * s, -dx * s + dy * c


# Querschnitt vor den Gebäuden (pv in m ab Grundstücksgrenze an der B54)
PV_GREEN, PV_PARK, PV_AISLE, PV_WALK, PV_FRONT = 0.0, 2.0, 7.0, 13.5, 19.57
PV_BACK, PV_YARD = 44.57, 51.0
FRONT_PU = (-251.0, -14.0)
# Einzige Zufahrt: 4. Knotenarm gegenüber der geplanten Aufschließung West (nördlich Billa),
# danach Nebenfahrbahn parallel zur B54 (Verkehrsgutachten Fruhmann 12/2023). Lage aus dem
# Übersichtslageplan abgegriffen (ca. 17 m nördlich der Grenze zu Gst. 105), nicht vermessen.
ACCESS_PU = (-21.0, -13.0)
PARK_END = ACCESS_PU[0] - 6.5  # Stellplätze enden vor der Ausrundung

# --------------------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------------------


def srgb(h, a=1.0):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c) + (a,)


def coll(name, parent=None):
    c = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(c)
    return c


def empty(name, parent=None, loc=(0, 0, 0), rot_z=0.0, scale=(1, 1, 1), collection=None):
    ob = bpy.data.objects.new(name, None)
    (collection or bpy.context.scene.collection).objects.link(ob)
    ob.parent = parent
    ob.location = loc
    ob.rotation_euler = (0, 0, rot_z)
    ob.scale = scale
    return ob


class MB:
    """Sammelt Flächen mit Materialindex und metrischen Box-UVs zu einem Mesh."""

    def __init__(self):
        self.v, self.f, self.m, self.uv = [], [], [], []

    def face(self, pts, mat, uv=None):
        i = len(self.v)
        self.v.extend(tuple(p) for p in pts)
        self.f.append(tuple(range(i, i + len(pts))))
        self.m.append(mat)
        if uv is None:
            a, b, c = (Vector(p) for p in pts[:3])
            n = (b - a).cross(c - a)
            ax = max(range(3), key=lambda k: abs(n[k]))
            uv = [(p[1], p[2]) if ax == 0 else (p[0], p[2]) if ax == 1 else (p[0], p[1]) for p in pts]
        self.uv.append(uv)

    def oriented(self, pts, mat, want, uv=None):
        a, b, c = (Vector(p) for p in pts[:3])
        if (b - a).cross(c - a).dot(Vector(want)) < 0:
            pts = list(reversed(pts))
            uv = list(reversed(uv)) if uv else None
        self.face(pts, mat, uv)

    def box(self, x0, x1, y0, y1, z0, z1, mat, top=None, bottom=None, skip=()):
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        t = mat if top is None else top
        b = mat if bottom is None else bottom
        if "bottom" not in skip:
            self.face([(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)], b)
        if "top" not in skip:
            self.face([(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], t)
        if "-y" not in skip:
            self.face([(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], mat)
        if "+y" not in skip:
            self.face([(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)], mat)
        if "-x" not in skip:
            self.face([(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)], mat)
        if "+x" not in skip:
            self.face([(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)], mat)

    def build(self, name, mats, parent=None, collection=None, smooth=False):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.v, [], self.f)
        for m in mats:
            me.materials.append(m)
        me.polygons.foreach_set("material_index", self.m)
        uvl = me.uv_layers.new(name="UVMap")
        flat = [c for face in self.uv for p in face for c in p]
        uvl.data.foreach_set("uv", flat)
        if smooth:
            me.polygons.foreach_set("use_smooth", [True] * len(self.f))
        me.validate()
        ob = bpy.data.objects.new(name, me)
        (collection or bpy.context.scene.collection).objects.link(ob)
        ob.parent = parent
        return ob


def pip(px, py, poly):
    inside = np.zeros(np.shape(px), bool)
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cond = ((y1 > py) != (y2 > py)) & (px < (x2 - x1) * (py - y1) / (y2 - y1 + 1e-12) + x1)
        inside ^= cond
    return inside


def dist_poly(px, py, poly):
    d = np.full(np.shape(px), 1e9)
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        t = np.clip(((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy + 1e-12), 0, 1)
        d = np.minimum(d, np.hypot(px - ax - t * dx, py - ay - t * dy))
    return d


# --------------------------------------------------------------------------------------
# Gelände
# --------------------------------------------------------------------------------------
DEM = np.load(DATA / "dem.npy").astype(np.float64)
DEM_FAR = np.load(DATA / "dem_far.npy").astype(np.float64)


def sample(grid, half, res, x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    n = grid.shape[0]
    c = np.clip((x + half) / res - 0.5, 0, n - 1.001)
    r = np.clip((half - y) / res - 0.5, 0, n - 1.001)
    c0, r0 = c.astype(int), r.astype(int)
    fx, fy = c - c0, r - r0
    return (grid[r0, c0] * (1 - fx) * (1 - fy) + grid[r0, c0 + 1] * fx * (1 - fy)
            + grid[r0 + 1, c0] * (1 - fx) * fy + grid[r0 + 1, c0 + 1] * fx * fy)


SITE_BLEND = 12.0


def ground(x, y):
    """Geländehöhe (relativ zu Z0) inkl. Planierung des Grundstücks."""
    h = sample(DEM, EXT, 4.0, x, y) - Z0
    pu, pv = world_to_plan(x, y)
    inside = pip(pu, pv, SITE)
    d = dist_poly(pu, pv, SITE)
    w = np.where(inside, 1.0, np.clip(1 - d / SITE_BLEND, 0, 1))
    w = w * w * (3 - 2 * w)
    return h * (1 - w) + (zl(pu) - 0.06) * w


def grid_mesh(name, X, Y, Z, mat, collection):
    ny, nx = Z.shape
    verts = np.stack([X, Y, Z], -1).reshape(-1, 3)
    idx = np.arange(ny * nx).reshape(ny, nx)
    quads = np.stack([idx[1:, :-1], idx[1:, 1:], idx[:-1, 1:], idx[:-1, :-1]], -1).reshape(-1, 4)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts.tolist(), [], quads.tolist())
    me.polygons.foreach_set("use_smooth", [True] * len(quads))
    me.materials.append(mat)
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    return ob


# --------------------------------------------------------------------------------------
# Materialien
# --------------------------------------------------------------------------------------
MATS: dict[str, bpy.types.Material] = {}
EMISSIVE: list[tuple[bpy.types.Node, float, float]] = []  # (Node, Tag, Abend)
DUSK_LIGHTS: list[bpy.types.Object] = []  # nur in der Abendansicht aktiv
WEB_COLOR: dict[str, tuple] = {}


class NT:
    def __init__(self, mat):
        self.nt = mat.node_tree
        self.nt.nodes.clear()
        self.out = self.n("ShaderNodeOutputMaterial")

    def n(self, kind, **kw):
        node = self.nt.nodes.new(kind)
        for k, v in kw.items():
            if k.startswith("i_"):
                key = k[2:].replace("_", " ")
                node.inputs[key].default_value = v
            else:
                setattr(node, k, v)
        return node

    def link(self, a, b):
        self.nt.links.new(a, b)

    def bsdf(self, color=None, rough=0.5, metal=0.0, **kw):
        b = self.n("ShaderNodeBsdfPrincipled")
        if color is not None:
            b.inputs["Base Color"].default_value = color
        b.inputs["Roughness"].default_value = rough
        b.inputs["Metallic"].default_value = metal
        for k, v in kw.items():
            b.inputs[k.replace("_", " ")].default_value = v
        return b


def material(name, web=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    MATS[name] = m
    if web:
        WEB_COLOR[name] = web
    return m, NT(m)


def mat_simple(name, color, rough=0.5, metal=0.0, bump=0.0, bump_scale=8.0, **kw):
    m, t = material(name, color)
    b = t.bsdf(color, rough, metal, **kw)
    if bump:
        tc = t.n("ShaderNodeTexCoord")
        nz = t.n("ShaderNodeTexNoise", i_Scale=bump_scale, i_Detail=6.0)
        t.link(tc.outputs["Object"], nz.inputs["Vector"])
        bp = t.n("ShaderNodeBump", i_Strength=bump, i_Distance=0.02)
        t.link(nz.outputs["Fac"], bp.inputs["Height"])
        t.link(bp.outputs["Normal"], b.inputs["Normal"])
    t.link(b.outputs[0], t.out.inputs[0])
    return m


def mat_stripes(name, color, rough, metal, period, axis="v", groove=0.012, dark=0.75):
    """Paneelfugen über UV (Meter) – Fassadenkassetten, Sektionaltore."""
    m, t = material(name, color)
    b = t.bsdf(color, rough, metal)
    uv = t.n("ShaderNodeUVMap")
    sep = t.n("ShaderNodeSeparateXYZ")
    t.link(uv.outputs[0], sep.inputs[0])
    md = t.n("ShaderNodeMath", operation="PINGPONG")
    md.inputs[1].default_value = period / 2
    t.link(sep.outputs[1 if axis == "v" else 0], md.inputs[0])
    st = t.n("ShaderNodeMath", operation="LESS_THAN")
    st.inputs[1].default_value = groove
    t.link(md.outputs[0], st.inputs[0])
    mix = t.n("ShaderNodeMix", data_type="RGBA")
    mix.inputs[6].default_value = color
    mix.inputs[7].default_value = tuple(c * dark for c in color[:3]) + (1,)
    t.link(st.outputs[0], mix.inputs[0])
    t.link(mix.outputs[2], b.inputs["Base Color"])
    bp = t.n("ShaderNodeBump", i_Strength=0.6, i_Distance=0.01, invert=True)
    t.link(st.outputs[0], bp.inputs["Height"])
    t.link(bp.outputs["Normal"], b.inputs["Normal"])
    t.link(b.outputs[0], t.out.inputs[0])
    return m


def mat_bricks(name, c1, c2, mortar, w, h, rough=0.8, mortar_size=0.008, bump=0.3, coord="UV"):
    m, t = material(name, c1)
    b = t.bsdf(None, rough)
    if coord == "UV":
        co = t.n("ShaderNodeUVMap").outputs[0]
    else:
        co = t.n("ShaderNodeTexCoord").outputs["Object"]
    br = t.n("ShaderNodeTexBrick", offset=0.5, squash=1.0)
    br.inputs["Color1"].default_value = c1
    br.inputs["Color2"].default_value = c2
    br.inputs["Mortar"].default_value = mortar
    br.inputs["Scale"].default_value = 1.0
    br.inputs["Mortar Size"].default_value = mortar_size
    br.inputs["Brick Width"].default_value = w
    br.inputs["Row Height"].default_value = h
    br.inputs["Bias"].default_value = 0.0
    t.link(co, br.inputs["Vector"])
    nz = t.n("ShaderNodeTexNoise", i_Scale=3.0, i_Detail=4.0)
    t.link(co, nz.inputs["Vector"])
    mix = t.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", i_Factor=0.25)
    t.link(br.outputs["Color"], mix.inputs[6])
    t.link(nz.outputs["Color"], mix.inputs[7])
    t.link(mix.outputs[2], b.inputs["Base Color"])
    bp = t.n("ShaderNodeBump", i_Strength=bump, i_Distance=0.01)
    t.link(br.outputs["Fac"], bp.inputs["Height"])
    t.link(bp.outputs["Normal"], b.inputs["Normal"])
    t.link(b.outputs[0], t.out.inputs[0])
    return m


def mat_grass(name, c1="#4c7526", c2="#7a9c3a", scale=0.35):
    m, t = material(name, srgb(c1))
    tc = t.n("ShaderNodeTexCoord")
    n1 = t.n("ShaderNodeTexNoise", i_Scale=scale, i_Detail=8.0, i_Roughness=0.6)
    n2 = t.n("ShaderNodeTexNoise", i_Scale=40.0, i_Detail=4.0)
    t.link(tc.outputs["Object"], n1.inputs["Vector"])
    t.link(tc.outputs["Object"], n2.inputs["Vector"])
    ramp = t.n("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = srgb(c1)
    ramp.color_ramp.elements[1].color = srgb(c2)
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[1].position = 0.7
    t.link(n1.outputs["Fac"], ramp.inputs[0])
    mul = t.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", i_Factor=0.35)
    t.link(ramp.outputs[0], mul.inputs[6])
    t.link(n2.outputs["Color"], mul.inputs[7])
    b = t.bsdf(None, 0.92)
    t.link(mul.outputs[2], b.inputs["Base Color"])
    bp = t.n("ShaderNodeBump", i_Strength=0.5, i_Distance=0.02)
    t.link(n2.outputs["Fac"], bp.inputs["Height"])
    t.link(bp.outputs["Normal"], b.inputs["Normal"])
    t.link(b.outputs[0], t.out.inputs[0])
    return m


def mat_emissive(name, color, base, day, dusk, rough=0.5):
    m, t = material(name, base)
    b = t.bsdf(base, rough)
    b.inputs["Emission Color"].default_value = color
    b.inputs["Emission Strength"].default_value = day
    EMISSIVE.append((b, day, dusk))
    t.link(b.outputs[0], t.out.inputs[0])
    return m


def haze(t, col_socket):
    """Luftperspektive für weite Ansichten: Farbe mit Entfernung zum Himmelston mischen."""
    cam = t.n("ShaderNodeCameraData")
    d = t.n("ShaderNodeMath", operation="MULTIPLY")
    d.inputs[1].default_value = -1 / 9000
    t.link(cam.outputs["View Distance"], d.inputs[0])
    e = t.n("ShaderNodeMath", operation="EXPONENT")
    t.link(d.outputs[0], e.inputs[0])
    f = t.n("ShaderNodeMath", operation="SUBTRACT")
    f.inputs[0].default_value = 1.0
    t.link(e.outputs[0], f.inputs[1])
    f2 = t.n("ShaderNodeMath", operation="MULTIPLY")
    f2.inputs[1].default_value = 0.6
    t.link(f.outputs[0], f2.inputs[0])
    mix = t.n("ShaderNodeMix", data_type="RGBA")
    t.link(f2.outputs[0], mix.inputs[0])
    t.link(col_socket, mix.inputs[6])
    mix.inputs[7].default_value = srgb("#b7c6d6")
    return mix.outputs[2]


def ortho_color(t, img_outer, img_inner=None, half_outer=EXT, half_inner=INNER):
    tc = t.n("ShaderNodeTexCoord")

    def tex(img, half, ext):
        mp = t.n("ShaderNodeMapping", vector_type="POINT")
        mp.inputs["Location"].default_value = (0.5, 0.5, 0)
        mp.inputs["Scale"].default_value = (1 / (2 * half), 1 / (2 * half), 1)
        t.link(tc.outputs["Object"], mp.inputs["Vector"])
        it = t.n("ShaderNodeTexImage", image=img, extension=ext, interpolation="Cubic")
        t.link(mp.outputs[0], it.inputs[0])
        return it

    # Mapping: v = x/(2h) + 0.5 → Location wirkt nach Skalierung; daher Reihenfolge prüfen
    o = tex(img_outer, half_outer, "EXTEND")
    col = o.outputs["Color"]
    if img_inner is not None:
        i = tex(img_inner, half_inner, "CLIP")
        mix = t.n("ShaderNodeMix", data_type="RGBA")
        t.link(i.outputs["Alpha"], mix.inputs[0])
        t.link(col, mix.inputs[6])
        t.link(i.outputs["Color"], mix.inputs[7])
        col = mix.outputs[2]
    hsv = t.n("ShaderNodeHueSaturation", i_Saturation=1.18, i_Value=0.96)
    t.link(col, hsv.inputs["Color"])
    bc = t.n("ShaderNodeBrightContrast", i_Contrast=0.12)
    t.link(hsv.outputs[0], bc.inputs["Color"])
    return bc.outputs[0]


def build_materials():
    img = lambda p: bpy.data.images.load(str(p), check_existing=True)  # noqa: E731
    o_out, o_in, o_far = img(DATA / "ortho_outer.jpg"), img(DATA / "ortho_inner.jpg"), img(DATA / "ortho_far.jpg")

    m, t = material("terrain", srgb("#7f9a5a"))
    b = t.bsdf(None, 0.9)
    t.link(haze(t, ortho_color(t, o_out, o_in)), b.inputs["Base Color"])
    t.link(b.outputs[0], t.out.inputs[0])

    m, t = material("terrain_far", srgb("#7f9a5a"))
    b = t.bsdf(None, 0.95)
    t.link(haze(t, ortho_color(t, o_far, None, FAR)), b.inputs["Base Color"])
    t.link(b.outputs[0], t.out.inputs[0])

    m, t = material("ctx_roof", srgb("#8a6a5a"))
    b = t.bsdf(None, 0.75)
    t.link(haze(t, ortho_color(t, o_out, o_in)), b.inputs["Base Color"])
    t.link(b.outputs[0], t.out.inputs[0])

    m, t = material("ctx_wall", srgb("#ebe7de"))
    b = t.bsdf(srgb("#ebe7de"), 0.85)
    rgb = t.n("ShaderNodeRGB")
    rgb.outputs[0].default_value = srgb("#d9d2c5")
    t.link(haze(t, rgb.outputs[0]), b.inputs["Base Color"])
    t.link(b.outputs[0], t.out.inputs[0])

    # Teichwiese-Gebäude
    mat_simple("plaster", srgb("#ebe8e1"), 0.85, bump=0.08, bump_scale=30)
    mat_stripes("cladding", srgb("#4a4e4d"), 0.5, 0.35, 0.62)
    mat_simple("frame", srgb("#2b2e30"), 0.4, 0.6)
    mat_simple("coping", srgb("#a3a6a8"), 0.35, 0.85)
    mat_simple("soffit", srgb("#f1efea"), 0.8)
    mat_simple("roof", srgb("#7a7c7b"), 0.9, bump=0.15, bump_scale=6)
    mat_simple("gravel", srgb("#9a968e"), 0.95, bump=0.6, bump_scale=60)
    mat_stripes("door", srgb("#3a3e41"), 0.45, 0.5, 0.55)
    mat_simple("concrete", srgb("#c3bfb6"), 0.85, bump=0.1, bump_scale=20)

    m, t = material("glass", srgb("#1b2228"))
    b = t.bsdf(srgb("#a9b9c0"), 0.0, 0.0)
    b.inputs["Transmission Weight"].default_value = 1.0
    b.inputs["IOR"].default_value = 1.52
    b.inputs["Thin Wall"].default_value = True
    t.link(b.outputs[0], t.out.inputs[0])

    # Holzlamellen: warmer Lärchenton, nah am Gold der Marke
    m, t = material("timber", srgb("#b8783a"))
    uv = t.n("ShaderNodeUVMap")
    mp = t.n("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (18.0, 0.6, 1.0)
    t.link(uv.outputs[0], mp.inputs[0])
    w = t.n("ShaderNodeTexNoise", i_Scale=4.0, i_Detail=10.0, i_Distortion=0.6)
    t.link(mp.outputs[0], w.inputs["Vector"])
    ramp = t.n("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = srgb("#9a5f2c")
    ramp.color_ramp.elements[1].color = srgb("#cf9150")
    t.link(w.outputs["Fac"], ramp.inputs[0])
    b = t.bsdf(None, 0.55)
    t.link(ramp.outputs[0], b.inputs["Base Color"])
    t.link(b.outputs[0], t.out.inputs[0])

    # PV-Module: Zellraster über Flächen-UV (0..1 je Modul)
    m, t = material("pv", srgb("#0d1424"))
    uv = t.n("ShaderNodeUVMap")
    br = t.n("ShaderNodeTexBrick", offset=0.0, squash=1.0)
    br.inputs["Color1"].default_value = srgb("#0b1222")
    br.inputs["Color2"].default_value = srgb("#0f1830")
    br.inputs["Mortar"].default_value = srgb("#5d6470")
    br.inputs["Scale"].default_value = 1.0
    br.inputs["Mortar Size"].default_value = 0.008
    br.inputs["Brick Width"].default_value = 1 / 6
    br.inputs["Row Height"].default_value = 1 / 10
    t.link(uv.outputs[0], br.inputs["Vector"])
    b = t.bsdf(None, 0.12)
    b.inputs["Coat Weight"].default_value = 1.0
    b.inputs["Coat Roughness"].default_value = 0.03
    t.link(br.outputs["Color"], b.inputs["Base Color"])
    t.link(b.outputs[0], t.out.inputs[0])

    mat_simple("int_floor", srgb("#bdb7ad"), 0.4)
    mat_simple("int_wall", srgb("#efe9df"), 0.8)
    mat_emissive("int_ceiling", srgb("#ffd9a8"), srgb("#f4f2ee"), 0.6, 6.0, 0.8)

    # Außenanlagen
    mat_grass("grass")
    mat_grass("grass_dark", "#3f6620", "#62862e", 0.6)
    mat_simple("asphalt", srgb("#353638"), 0.82, bump=0.25, bump_scale=120)
    mat_simple("asphalt_road", srgb("#3d3e40"), 0.8, bump=0.25, bump_scale=120)
    mat_simple("marking", srgb("#ecebe6"), 0.55)
    mat_bricks("pavers", srgb("#cfcac0"), srgb("#c3bdb2"), srgb("#8f8a80"), 0.6, 0.3)
    mat_bricks("pavers_plaza", srgb("#d6cfc2"), srgb("#c9c0b1"), srgb("#958d80"), 0.5, 0.5)
    mat_bricks("grasspavers", srgb("#b3aea4"), srgb("#a9a499"), srgb("#5f8a30"), 0.4, 0.4,
               mortar_size=0.09, bump=0.4)
    mat_simple("kerb", srgb("#c9c5bc"), 0.8, bump=0.1)

    # Vegetation
    for name, c1, c2 in [("leaf", "#2f5b1d", "#6f9a33"), ("leaf_obst", "#3d6b22", "#8db14a"),
                         ("leaf_conifer", "#1f3b1c", "#3d5e2a")]:
        m, t = material(name, srgb(c1))
        tc = t.n("ShaderNodeTexCoord")
        oi = t.n("ShaderNodeObjectInfo")
        nz = t.n("ShaderNodeTexNoise", i_Scale=1.5, i_Detail=6.0)
        t.link(tc.outputs["Object"], nz.inputs["Vector"])
        add = t.n("ShaderNodeMath", operation="MULTIPLY_ADD")
        add.inputs[1].default_value = 0.45
        t.link(oi.outputs["Random"], add.inputs[0])
        t.link(nz.outputs["Fac"], add.inputs[2])
        ramp = t.n("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = srgb(c1)
        ramp.color_ramp.elements[1].color = srgb(c2)
        ramp.color_ramp.elements[0].position = 0.2
        ramp.color_ramp.elements[1].position = 0.95
        t.link(add.outputs[0], ramp.inputs[0])
        b = t.bsdf(None, 0.75)
        b.inputs["Subsurface Weight"].default_value = 0.0
        # Kronen unten dunkler (Selbstverschattung), oben heller
        sep = t.n("ShaderNodeSeparateXYZ")
        t.link(tc.outputs["Object"], sep.inputs[0])
        mr = t.n("ShaderNodeMapRange")
        mr.inputs["From Min"].default_value = 1.5
        mr.inputs["From Max"].default_value = 11.0
        mr.inputs["To Min"].default_value = 0.55
        mr.inputs["To Max"].default_value = 1.15
        t.link(sep.outputs[2], mr.inputs["Value"])
        shade = t.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", i_Factor=1.0)
        t.link(ramp.outputs[0], shade.inputs[6])
        t.link(mr.outputs[0], shade.inputs[7])
        t.link(shade.outputs[2], b.inputs["Base Color"])
        fine = t.n("ShaderNodeTexVoronoi", i_Scale=22.0)
        t.link(tc.outputs["Object"], fine.inputs["Vector"])
        leafn = t.n("ShaderNodeTexNoise", i_Scale=45.0, i_Detail=3.0)
        t.link(tc.outputs["Object"], leafn.inputs["Vector"])
        hsum = t.n("ShaderNodeMath", operation="ADD")
        t.link(fine.outputs["Distance"], hsum.inputs[0])
        t.link(leafn.outputs["Fac"], hsum.inputs[1])
        bp = t.n("ShaderNodeBump", i_Strength=1.0, i_Distance=0.06)
        t.link(hsum.outputs[0], bp.inputs["Height"])
        t.link(bp.outputs["Normal"], b.inputs["Normal"])
        tr = t.n("ShaderNodeBsdfTranslucent")
        t.link(shade.outputs[2], tr.inputs["Color"])
        ms = t.n("ShaderNodeMixShader", i_Fac=0.18)
        t.link(b.outputs[0], ms.inputs[1])
        t.link(tr.outputs[0], ms.inputs[2])
        t.link(ms.outputs[0], t.out.inputs[0])
    mat_simple("bark", srgb("#5b4a3b"), 0.9, bump=0.4, bump_scale=15)
    # Gründach: Sedum-Teppich (grün, rötlich, gelbgrün gefleckt)
    m, t = material("sedum", srgb("#6f8a3c"))
    tc = t.n("ShaderNodeTexCoord")
    n1 = t.n("ShaderNodeTexNoise", i_Scale=1.6, i_Detail=6.0, i_Roughness=0.65)
    n2 = t.n("ShaderNodeTexNoise", i_Scale=55.0, i_Detail=3.0)
    t.link(tc.outputs["Object"], n1.inputs["Vector"])
    t.link(tc.outputs["Object"], n2.inputs["Vector"])
    ramp = t.n("ShaderNodeValToRGB")
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = 0.32, srgb("#8a4f35")
    els[1].position, els[1].color = 0.72, srgb("#a7ad4c")
    e = els.new(0.5)
    e.color = srgb("#5f8434")
    t.link(n1.outputs["Fac"], ramp.inputs[0])
    mul = t.n("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", i_Factor=0.45)
    t.link(ramp.outputs[0], mul.inputs[6])
    t.link(n2.outputs["Color"], mul.inputs[7])
    bsdf = t.bsdf(None, 0.9)
    t.link(mul.outputs[2], bsdf.inputs["Base Color"])
    bp = t.n("ShaderNodeBump", i_Strength=0.8, i_Distance=0.03)
    t.link(n2.outputs["Fac"], bp.inputs["Height"])
    t.link(bp.outputs["Normal"], bsdf.inputs["Normal"])
    t.link(bsdf.outputs[0], t.out.inputs[0])
    mat_simple("grass_tuft", srgb("#8a9a48"), 0.8)
    mat_simple("leaf_vine", srgb("#2e5a22"), 0.6, bump=0.5, bump_scale=40)
    mat_simple("akebia_bloom", srgb("#7a3a6e"), 0.5)
    mat_simple("steel_cable", srgb("#b8bcc0"), 0.25, 0.95)
    mat_simple("planter", srgb("#3a3d40"), 0.6, 0.3)
    mat_simple("parasol", srgb("#f1ede4"), 0.8)
    mat_simple("skin", srgb("#d2a386"), 0.6)
    for i, c in enumerate(["#2b4a73", "#c9980a", "#8b2b2b", "#e8e4dc", "#3d5c3a", "#56595c", "#6b4b8a", "#d97a3a"]):
        mat_simple(f"cloth_{i}", srgb(c), 0.8)
    mat_simple("apple", srgb("#b8371f"), 0.45)

    # Ausstattung
    mat_simple("pylon", srgb("#f3f2ee"), 0.4)
    mat_simple("anthracite", srgb("#2a2c2d"), 0.45, 0.5)
    mat_simple("brand_gold", srgb("#c9980a"), 0.35, 0.6)
    mat_simple("brand_green", srgb("#024c20"), 0.5)
    mat_simple("brand_text", srgb("#26261e"), 0.5)
    mat_emissive("lamp_light", srgb("#ffe2b8"), srgb("#f2f0ea"), 0.0, 40.0, 0.3)
    mat_simple("brake_light", srgb("#8a1a14"), 0.3)
    mat_simple("wood_bench", srgb("#9b6a3d"), 0.6)
    mat_simple("tyre", srgb("#151515"), 0.8)
    mat_simple("car_glass", srgb("#0c1014"), 0.05, 0.0, Specular_IOR_Level=0.8)
    # Zeitgemäße Lackfarben: Perlweiß, Silber, Graphit, Schwarz, Tiefblau, Rot, Zementgrau, Dunkelgrün,
    # Petrolblau, Sandbeige, Bronze, Hellblau
    for i, c in enumerate(["#eceeee", "#b6babd", "#4b5054", "#141618", "#1d3266", "#a3161a", "#8c9091",
                           "#25402f", "#1f5361", "#c8b89a", "#7a5a3c", "#6f93b4"]):
        mat_simple(f"car_{i}", srgb(c), 0.22, 0.55, Coat_Weight=1.0, Coat_Roughness=0.02)
    mat_simple("car_rim", srgb("#9aa0a6"), 0.3, 0.9)
    mat_simple("car_trim", srgb("#17181a"), 0.55, 0.1)
    mat_emissive("car_led", srgb("#f4f7ff"), srgb("#e8ecf2"), 0.8, 6.0, 0.2)

    # Logo (transparentes PNG) auf weißer Tafel
    logo = img(LOGO)
    m, t = material("logo", srgb("#ffffff"))
    uv = t.n("ShaderNodeUVMap")
    it = t.n("ShaderNodeTexImage", image=logo, extension="CLIP", interpolation="Cubic")
    t.link(uv.outputs[0], it.inputs[0])
    mix = t.n("ShaderNodeMix", data_type="RGBA")
    mix.inputs[6].default_value = srgb("#f8f7f3")
    t.link(it.outputs["Alpha"], mix.inputs[0])
    t.link(it.outputs["Color"], mix.inputs[7])
    b = t.bsdf(None, 0.35)
    t.link(mix.outputs[2], b.inputs["Base Color"])
    t.link(mix.outputs[2], b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = 0.0
    EMISSIVE.append((b, 0.0, 1.6))
    t.link(b.outputs[0], t.out.inputs[0])


M = MATS.__getitem__

# --------------------------------------------------------------------------------------
# Gelände und Umgebung
# --------------------------------------------------------------------------------------


def build_terrain(c):
    n = DEM.shape[0]
    xs = -EXT + (np.arange(n) + 0.5) * 4.0
    ys = EXT - (np.arange(n) + 0.5) * 4.0
    X, Y = np.meshgrid(xs, ys)
    Z = ground(X, Y)
    grid_mesh("Gelaende", X, Y, Z, M("terrain"), c)

    nf = DEM_FAR.shape[0]
    xs = -FAR + (np.arange(nf) + 0.5) * 25.0
    ys = FAR - (np.arange(nf) + 0.5) * 25.0
    X, Y = np.meshgrid(xs, ys)
    Z = DEM_FAR - Z0
    inner = (np.abs(X) < EXT - 12) & (np.abs(Y) < EXT - 12)
    Z = np.where(inner, Z - 2.5, Z)
    grid_mesh("Gelaende_Fern", X, Y, Z, M("terrain_far"), c)


def canopy_mask():
    im = bpy.data.images[(DATA / "ortho_outer.jpg").name]
    w, h = im.size
    px = np.empty(w * h * 4, np.float32)
    im.pixels.foreach_get(px)
    a = px.reshape(h, w, 4)[::-1, :, :3]  # Zeile 0 = Norden
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    br = a.mean(-1)
    exg = 2 * g - r - b
    sat = a.max(-1) - a.min(-1)
    m = (((exg > 0.02) & (br < 0.33) & (g >= b)) | ((br < 0.16) & (sat < 0.12) & (g >= r))).astype(float)
    k = 5
    cs = np.cumsum(np.cumsum(np.pad(m, ((k, k), (k, k)), mode="edge"), 0), 1)
    box = (cs[2 * k:, 2 * k:] - cs[:-2 * k, 2 * k:] - cs[2 * k:, :-2 * k] + cs[:-2 * k, :-2 * k]) / (4 * k * k)
    return box[:h, :w] > 0.5


def osm_features():
    return json.loads((DATA / "osm.json").read_text())["features"]


def convex_hull(pts):
    pts = sorted(set(map(tuple, pts)))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def min_rect(pts):
    hull = np.array(convex_hull(pts))
    best = None
    for i in range(len(hull)):
        e = hull[(i + 1) % len(hull)] - hull[i]
        ang = math.atan2(e[1], e[0])
        c, s = math.cos(ang), math.sin(ang)
        rot = hull @ np.array([[c, -s], [s, c]])
        mn, mx = rot.min(0), rot.max(0)
        area = (mx - mn).prod()
        if best is None or area < best[0]:
            ctr = ((mn + mx) / 2) @ np.array([[c, s], [-s, c]])
            best = (area, ctr, ang, (mx - mn) / 2)
    _, ctr, ang, half = best
    u = np.array([math.cos(ang), math.sin(ang)])
    v = np.array([-math.sin(ang), math.cos(ang)])
    if half[1] > half[0]:
        u, v, half = v, -u, half[::-1]
    return ctr, u, v, half[0], half[1]


FLAT_TYPES = {"industrial", "retail", "commercial", "warehouse", "supermarket", "school", "public",
              "civic", "office", "sports_hall", "hospital", "kindergarten", "parking"}
SMALL_TYPES = {"garage", "garages", "carport", "shed", "hut", "roof", "kiosk", "greenhouse"}
FARM_TYPES = {"barn", "farm_auxiliary", "stable", "cowshed"}


def build_context(c, feats):
    mb = MB()
    footprints = []
    site_buf = 6.0
    for f in feats:
        t = f["tags"]
        if "building" not in t or len(f["xy"]) < 4:
            continue
        P = np.array(f["xy"][:-1] if f["xy"][0] == f["xy"][-1] else f["xy"], float)
        if np.abs(P).max() > EXT - 40:
            continue
        pu, pv = world_to_plan(P[:, 0], P[:, 1])
        if (pip(pu, pv, SITE) | (dist_poly(pu, pv, SITE) < 1.0)).any() and pv.mean() > -site_buf:
            continue
        area = 0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])
        if area < 0:
            P = P[::-1]
            area = -area
        if area < 6:
            continue
        footprints.append(P)
        kind = t["building"]
        zg = ground(P[:, 0], P[:, 1])
        base = zg.min() - 0.6
        top0 = zg.max()
        ctr, u, v, a, b = min_rect(P)
        fill = area / (4 * a * b)
        levels = t.get("building:levels")
        try:
            levels = float(levels)
        except (TypeError, ValueError):
            levels = None
        flat = kind in FLAT_TYPES or area > 750 or fill < 0.78 or t.get("roof:shape") == "flat"
        if kind in SMALL_TYPES:
            eave, pitch = 2.6, 18
        elif kind in FARM_TYPES:
            eave, pitch = 5.0, 30
        elif kind == "church":
            eave, pitch, flat = 11.0, 48, False
        elif kind == "apartments":
            eave, pitch = 9.0, 30
        elif flat:
            eave, pitch = (levels * 3.6 if levels else 7.0), 0
        else:
            eave, pitch = 5.6, 35
        if levels and not flat:
            eave = levels * 2.9
        ze = top0 + eave
        n = len(P)
        for i in range(n):
            p, q = P[i], P[(i + 1) % n]
            mb.face([(p[0], p[1], base), (q[0], q[1], base), (q[0], q[1], ze), (p[0], p[1], ze)], 0)
        if flat:
            mb.face([(p[0], p[1], ze) for p in P], 1)
            continue
        rise = min(b * math.tan(math.radians(pitch)), 7.0)
        o = 0.55
        C = np.array(ctr)
        corner = lambda su, sv, aa, bb, z: (*(C + su * aa * u + sv * bb * v), z)  # noqa: E731
        r1 = (*(C - (a + o) * u), ze + rise)
        r2 = (*(C + (a + o) * u), ze + rise)
        zl_ = ze - o * math.tan(math.radians(pitch))
        mb.oriented([corner(-1, -1, a + o, b + o, zl_), corner(1, -1, a + o, b + o, zl_), r2, r1], 1,
                    (*(-v), 1))
        mb.oriented([corner(1, 1, a + o, b + o, zl_), corner(-1, 1, a + o, b + o, zl_), r1, r2], 1,
                    (*v, 1))
        g1 = (*(C - a * u), ze + rise - o * 0)
        g2 = (*(C + a * u), ze + rise)
        mb.oriented([corner(-1, -1, a, b, ze), corner(-1, 1, a, b, ze), g1], 0, (*(-u), 0))
        mb.oriented([corner(1, 1, a, b, ze), corner(1, -1, a, b, ze), g2], 0, (*u, 0))
        mb.face([corner(-1, -1, a, b, ze), corner(1, -1, a, b, ze), corner(1, 1, a, b, ze),
                 corner(-1, 1, a, b, ze)], 0)
    ob = mb.build("Umgebung_Gebaeude", [M("ctx_wall"), M("ctx_roof")], collection=c)
    return ob, footprints


ROAD_W = {"primary": 7.5, "secondary": 6.5, "tertiary": 6.0, "residential": 4.6, "unclassified": 4.6,
          "living_street": 4.2, "service": 3.4}


def resample(P, step):
    out = [P[0]]
    for a, b in zip(P[:-1], P[1:]):
        L = np.linalg.norm(b - a)
        k = max(1, int(L / step))
        for i in range(1, k + 1):
            out.append(a + (b - a) * i / k)
    return np.array(out)


def ribbon(mb, P, half, zoff, mat, offset=0.0, dash=None):
    P = resample(P, 2.0)
    if len(P) < 2:
        return
    T = np.gradient(P, axis=0)
    T /= np.linalg.norm(T, axis=1)[:, None] + 1e-9
    N = np.stack([-T[:, 1], T[:, 0]], 1)
    L = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    left = P + N * (offset + half)
    right = P + N * (offset - half)
    zL = ground(left[:, 0], left[:, 1]) + zoff
    zR = ground(right[:, 0], right[:, 1]) + zoff
    for i in range(len(P) - 1):
        if dash:
            on, off = dash
            mid = (L[i] + L[i + 1]) / 2
            if (mid % (on + off)) > on:
                continue
        mb.face([(right[i][0], right[i][1], zR[i]), (right[i + 1][0], right[i + 1][1], zR[i + 1]),
                 (left[i + 1][0], left[i + 1][1], zL[i + 1]), (left[i][0], left[i][1], zL[i])], mat,
                [(0, L[i]), (0, L[i + 1]), (1, L[i + 1]), (1, L[i])])


def build_roads(c, feats):
    mb, mk = MB(), MB()
    lines = []
    for f in feats:
        t = f["tags"]
        hw = t.get("highway")
        if hw not in ROAD_W or len(f["xy"]) < 2:
            continue
        P = np.array(f["xy"], float)
        if np.hypot(P[:, 0], P[:, 1]).min() > 700:
            continue
        w = ROAD_W[hw]
        if hw == "service" and t.get("service") in ("driveway", "parking_aisle"):
            w = 3.0
        prim = hw == "primary"
        ribbon(mb, P, w / 2, 0.16 if prim else 0.12, 1 if prim else 0)
        lines.append((P, w))
        if prim:
            ribbon(mk, P, 0.06, 0.18, 0, dash=(4.5, 9.0))
            ribbon(mk, P, 0.075, 0.18, 0, offset=w / 2 - 0.35)
            ribbon(mk, P, 0.075, 0.18, 0, offset=-(w / 2 - 0.35))
    # Geplanter Westarm des Knotens gegenüber der Zufahrt (Lageplan 22-029_001, rot skizziert):
    # Zufahrt Billa nach Süden in den Parkplatz, künftige Aufschließungsstraße nach Westen/Norden
    for P, w in west_access_lines():
        ribbon(mb, P, w / 2, 0.13, 1)
        ribbon(mk, P, 0.06, 0.15, 0, offset=w / 2 - 0.3)
        ribbon(mk, P, 0.06, 0.15, 0, offset=-(w / 2 - 0.3))
        lines.append((P, w))
    mb.build("Strassen", [M("asphalt"), M("asphalt_road")], collection=c)
    mk.build("Strassen_Markierung", [M("marking")], collection=c)
    return lines


def arc_plan(p0, heading, turn, radius, step=1.5):
    """Bogen im Planrahmen ab p0, Richtung heading (rad), Drehwinkel turn (rad, + = gegen Uhrzeiger)."""
    pts = []
    n = max(2, int(abs(turn) * radius / step))
    side = 1 if turn > 0 else -1
    cx = p0[0] - side * radius * math.sin(heading)
    cy = p0[1] + side * radius * math.cos(heading)
    a0 = heading - side * math.pi / 2
    for i in range(1, n + 1):
        a = a0 + turn * i / n
        pts.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
    return pts


def west_access_lines():
    """Mittellinien (Welt) der geplanten Straßen westlich der B54 am Knoten; Lage nach Planskizze."""
    uj = (ACCESS_PU[0] + ACCESS_PU[1]) / 2
    out = []
    # Trichter an der B54
    out.append(([(uj, -5.5), (uj, -13.0)], 13.0))
    # Aufschließungsstraße: ca. 30 m nach Westen, dann Bogen nach Norden (−pu)
    a = [(uj, -5.5), (uj, -34.0)]
    a += arc_plan(a[-1], -math.pi / 2, -math.pi / 2, 16.0)
    a += [(a[-1][0] - 45.0, a[-1][1])]
    out.append((a, 6.5))
    # Zufahrt Billa: zweigt nach Süden (+pu) in den Parkplatz ab
    b = [(uj + 2.5, -15.0)]
    b += arc_plan(b[-1], -math.pi / 2, math.pi / 2 * 0.85, 10.0)
    hx, hy = b[-1][0] - b[-2][0], b[-1][1] - b[-2][1]
    L = math.hypot(hx, hy)
    b += [(b[-1][0] + hx / L * 12.0, b[-1][1] + hy / L * 12.0)]
    out.append((b, 6.0))
    return [(np.array([plan_to_world(u, v) for u, v in pts]), w) for pts, w in out]


# --------------------------------------------------------------------------------------
# Bäume
# --------------------------------------------------------------------------------------


def make_tree(name, kind, coll_, seed):
    rnd = random.Random(seed)
    bm = bmesh.new()
    mats = []

    def add(geom_fn, mat):
        if mat not in mats:
            mats.append(mat)
        idx = mats.index(mat)
        before = set(bm.faces)
        geom_fn()
        for f in bm.faces:
            if f not in before:
                f.material_index = idx

    def cyl(p0, p1, r0, r1, seg=7):
        p0, p1 = Vector(p0), Vector(p1)
        d = p1 - p0
        rot = d.to_track_quat("Z", "Y").to_matrix().to_4x4()
        res = bmesh.ops.create_cone(bm, cap_ends=False, segments=seg, radius1=r0, radius2=r1,
                                    depth=d.length, matrix=Matrix.Translation((p0 + p1) / 2) @ rot)
        return res

    def blob(ctr, r, amp, sub=2, squash=1.0):
        res = bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=r, matrix=Matrix.Translation(ctr))
        off = Vector((rnd.random() * 50, rnd.random() * 50, rnd.random() * 50))
        fq = 2.2 / max(r, 0.3)
        for v in res["verts"]:
            p = v.co - Vector(ctr)
            p.z *= squash
            nv = p.normalized()
            k = 1 + amp * noise.noise(v.co * fq + off) + 0.45 * amp * noise.noise(v.co * fq * 2.7 + off)
            v.co = Vector(ctr) + nv * p.length * k

    if kind in ("laub", "obst", "strasse"):
        H, R, trunk = {"laub": (15.0, 4.6, 4.0), "obst": (4.6, 2.1, 1.5), "strasse": (8.0, 2.3, 3.1)}[kind]
        R *= rnd.uniform(0.92, 1.08)
        leaf = M("leaf_obst") if kind == "obst" else M("leaf")
        lean = Vector((rnd.uniform(-0.3, 0.3), rnd.uniform(-0.3, 0.3), 0)) * (R / 4)
        top = Vector((0, 0, trunk + R * 0.7)) + lean
        add(lambda: cyl((0, 0, 0), top, 0.06 * R + 0.06, 0.03 * R + 0.03), M("bark"))
        for k in range(4):
            ang = k * 1.6 + rnd.random()
            tip = top + Vector((math.cos(ang) * R * 0.6, math.sin(ang) * R * 0.6, R * rnd.uniform(0.1, 0.4)))
            add(lambda tip=tip: cyl(top - Vector((0, 0, R * 0.4)), tip, 0.03 * R + 0.02, 0.01 * R + 0.01, 5),
                M("bark"))
        ctr = Vector((0, 0, trunk + R * 0.95)) + lean
        nclump = {"laub": 70, "strasse": 52, "obst": 40}[kind]

        def crown():
            blob(ctr, R * 0.68, 0.12, 3, 1.1)
            for _ in range(nclump):
                d = Vector((rnd.gauss(0, 1), rnd.gauss(0, 1), rnd.gauss(0, 1))).normalized()
                d.z = d.z * 0.8 + 0.08
                rr = R * (0.5 + 0.38 * math.sqrt(rnd.random()))
                p = ctr + Vector((d.x * rr, d.y * rr, d.z * rr * 0.9))
                blob(p, R * rnd.uniform(0.15, 0.25), 0.42, 3)
        add(crown, leaf)
        if kind == "obst":
            def apples():
                for _ in range(14):
                    ang = rnd.random() * 6.283
                    el = rnd.uniform(-0.6, 0.5)
                    d = Vector((math.cos(ang) * math.cos(el), math.sin(ang) * math.cos(el), math.sin(el) * 0.8))
                    bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.07,
                                               matrix=Matrix.Translation(ctr + d * R * 0.98))
            add(apples, M("apple"))
    else:  # Nadelbaum
        H = 22.0
        add(lambda: cyl((0, 0, 0), (0, 0, H * 0.9), 0.32, 0.05), M("bark"))

        def cones():
            nlev = 8
            for k in range(nlev):
                z0 = H * (0.18 + 0.75 * k / nlev)
                r = 3.4 * (1 - k / nlev) + 0.4
                res = bmesh.ops.create_cone(bm, cap_ends=True, segments=9, radius1=r, radius2=0.05,
                                            depth=H * 0.22, matrix=Matrix.Translation((0, 0, z0 + H * 0.11)))
                off = Vector((rnd.random() * 9, rnd.random() * 9, k))
                for v in res["verts"]:
                    v.co.x *= 1 + 0.18 * noise.noise(v.co * 1.3 + off)
                    v.co.y *= 1 + 0.18 * noise.noise(v.co * 1.3 + off + Vector((3, 0, 0)))
        add(cones, M("leaf_conifer"))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    ob = bpy.data.objects.new(name, me)
    coll_.objects.link(ob)
    return ob


def scatter(name, coll_src, pts, rot, scale, var, collection):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(p) for p in pts], [], [])
    for attr, data, kind in (("rot", rot, "FLOAT"), ("scl", scale, "FLOAT"), ("var", var, "INT")):
        a = me.attributes.new(attr, kind, "POINT")
        a.data.foreach_set("value", list(map(int, data)) if kind == "INT" else list(map(float, data)))
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    ng = bpy.data.node_groups.new(name + "_GN", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nd = ng.nodes
    gi, go = nd.new("NodeGroupInput"), nd.new("NodeGroupOutput")
    iop = nd.new("GeometryNodeInstanceOnPoints")
    ci = nd.new("GeometryNodeCollectionInfo")
    ci.transform_space = "ORIGINAL"
    ci.inputs["Collection"].default_value = coll_src
    ci.inputs["Separate Children"].default_value = True
    ci.inputs["Reset Children"].default_value = True

    def named(n, dt):
        x = nd.new("GeometryNodeInputNamedAttribute")
        x.data_type = dt
        x.inputs["Name"].default_value = n
        return x

    nr, ns, nv = named("rot", "FLOAT"), named("scl", "FLOAT"), named("var", "INT")
    cx = nd.new("ShaderNodeCombineXYZ")
    lk = ng.links.new
    lk(gi.outputs[0], iop.inputs["Points"])
    lk(ci.outputs[0], iop.inputs["Instance"])
    iop.inputs["Pick Instance"].default_value = True
    lk(nv.outputs[0], iop.inputs["Instance Index"])
    lk(nr.outputs[0], cx.inputs["Z"])
    lk(cx.outputs[0], iop.inputs["Rotation"])
    lk(ns.outputs[0], iop.inputs["Scale"])
    lk(iop.outputs[0], go.inputs[0])
    ob.modifiers.new("Streuung", "NODES").node_group = ng
    return ob


def build_forest(c, feats, footprints, roads, tree_coll):
    mask = canopy_mask()
    h, w = mask.shape
    rng = np.random.default_rng(7)
    pts = []
    for spacing, lim in ((5.5, 420), (7.5, EXT - 25)):
        g = np.arange(-lim, lim, spacing)
        X, Y = np.meshgrid(g, g)
        X = X + rng.uniform(-spacing * 0.45, spacing * 0.45, X.shape)
        Y = Y + rng.uniform(-spacing * 0.45, spacing * 0.45, Y.shape)
        X, Y = X.ravel(), Y.ravel()
        if lim > 500:
            keep = (np.abs(X) > 420) | (np.abs(Y) > 420)
            X, Y = X[keep], Y[keep]
        pts.append(np.stack([X, Y], 1))
    P = np.concatenate(pts)
    col = np.clip(((P[:, 0] + EXT) / 1.0).astype(int), 0, w - 1)
    row = np.clip(((EXT - P[:, 1]) / 1.0).astype(int), 0, h - 1)
    P = P[mask[row, col]]
    # Nicht auf Gebäuden, Straßen und dem Projektgrundstück
    occ = np.zeros((h // 2 + 1, w // 2 + 1), bool)
    for F in footprints:
        mn, mx = F.min(0) - 2, F.max(0) + 2
        gx, gy = np.meshgrid(np.arange(mn[0], mx[0], 1.0), np.arange(mn[1], mx[1], 1.0))
        inside = pip(gx, gy, F) | (dist_poly(gx, gy, F) < 2.0)
        cc = ((gx[inside] + EXT) / 2).astype(int)
        rr = ((EXT - gy[inside]) / 2).astype(int)
        occ[np.clip(rr, 0, occ.shape[0] - 1), np.clip(cc, 0, occ.shape[1] - 1)] = True
    for R, wd in roads:
        S = resample(R, 1.0)
        rad = int(math.ceil((wd / 2 + 1.5) / 2))
        for dx in range(-rad, rad + 1):
            for dy in range(-rad, rad + 1):
                cc = ((S[:, 0] + EXT) / 2).astype(int) + dx
                rr = ((EXT - S[:, 1]) / 2).astype(int) + dy
                ok = (cc >= 0) & (cc < occ.shape[1]) & (rr >= 0) & (rr < occ.shape[0])
                occ[rr[ok], cc[ok]] = True
    cc = np.clip(((P[:, 0] + EXT) / 2).astype(int), 0, occ.shape[1] - 1)
    rr = np.clip(((EXT - P[:, 1]) / 2).astype(int), 0, occ.shape[0] - 1)
    P = P[~occ[rr, cc]]
    pu, pv = world_to_plan(P[:, 0], P[:, 1])
    P = P[~(pip(pu, pv, SITE) | (dist_poly(pu, pv, SITE) < 4))]
    # Obstgärten (OSM landuse=orchard) bekommen kleine Obstbäume
    orch = np.zeros(len(P), bool)
    forest = np.zeros(len(P), bool)
    for f in feats:
        lu = f["tags"].get("landuse") or f["tags"].get("natural")
        if lu in ("orchard", "forest", "wood") and len(f["xy"]) > 3:
            F = np.array(f["xy"])
            hit = pip(P[:, 0], P[:, 1], F)
            (orch if lu == "orchard" else forest)[hit] = True
    n = len(P)
    var = np.where(orch, rng.integers(0, 2, n),
                   np.where(forest & (rng.random(n) < 0.45), rng.integers(5, 7, n), rng.integers(2, 5, n)))
    scale = np.where(orch, rng.uniform(0.8, 1.1, n),
                     np.where(var >= 5, rng.uniform(0.75, 1.25, n), rng.uniform(0.6, 1.15, n)))
    Z = ground(P[:, 0], P[:, 1]) - 0.2
    pts3 = np.column_stack([P, Z])
    print(f"Umgebungsbäume: {n}")
    return scatter("Umgebung_Baeume", tree_coll, pts3, rng.uniform(0, 6.283, n), scale, var, c)


# --------------------------------------------------------------------------------------
# Bauteile (Gebäudetyp nach Entwurf 3)
# --------------------------------------------------------------------------------------
L_EG, L_OG, D_EG = 47.99, 49.99, 25.0
Y_OG0, Y_OG1 = -2.0, 18.2
Z_OGF, Z_ROOF, Z_PAR, Z_SOFF = 5.0, 9.0, 9.5, 4.55
CORE = (22.24, 25.54)  # Stiegenhaus inkl. Wände, ab Fuge zu Bauteil 2
EG_PIERS = [0.0, 5.7, 11.25, 16.8, 22.24, 25.54, 29.85, 34.025, 39.025, 43.2, L_EG]
OG_BAYS = [(0.15, 5.7), (5.7, 11.25), (11.25, 16.8), (16.8, 22.24), (25.54, 31.0), (31.0, 36.55),
           (36.55, 42.1), (42.1, 47.65), (47.65, L_OG - 0.35)]
LAGER_DOORS = [(3.9, 3.4), (18.6, 3.4), (29.7, 3.4), (36.5, 3.0), (43.3, 3.4)]
BUERO_DOORS = [9.4, 13.1]

BMATS = ["plaster", "cladding", "glass", "frame", "timber", "roof", "gravel", "coping", "soffit", "door",
         "concrete", "int_floor", "int_wall", "int_ceiling", "pv", "lamp_light", "sedum"]
BI = {n: i for i, n in enumerate(BMATS)}


def facade_windows(mb, y, outward, bays, z0, z1, reveal=0.18, gap=0.55):
    """Fensterbänder im OG: Verglasung zurückgesetzt, Laibungen, Rahmenteilung."""
    s = 1 if outward > 0 else -1
    yg = y - s * reveal
    for a, b in bays:
        x0, x1 = a + gap, b - gap
        mb.face([(x0, yg, z0), (x1, yg, z0), (x1, yg, z1), (x0, yg, z1)], BI["glass"])
        mb.box(x0, x1, min(y, yg), max(y, yg), z0 - 0.06, z0, BI["coping"])  # Sohlbank
        mb.box(x0, x1, min(y, yg), max(y, yg), z1, z1 + 0.02, BI["frame"])
        mb.box(x0 - 0.02, x0, min(y, yg), max(y, yg), z0, z1, BI["frame"])
        mb.box(x1, x1 + 0.02, min(y, yg), max(y, yg), z0, z1, BI["frame"])
        k = max(2, round((x1 - x0) / 1.25))
        for j in range(1, k):
            xm = x0 + (x1 - x0) * j / k
            mb.box(xm - 0.03, xm + 0.03, yg - 0.04 * s, yg + 0.02 * s, z0, z1, BI["frame"])
        mb.box(x0, x1, yg - 0.05 * s, yg, z0, z0 + 0.06, BI["frame"])
        mb.box(x0, x1, yg - 0.05 * s, yg, z1 - 0.06, z1, BI["frame"])


def cladding_with_openings(mb, y, bays, z_lo, z_hi, w_lo, w_hi, xa, xb, gap=0.55, outward=-1):
    """Fassadenfläche in Ebene y mit Öffnungen für Fensterbänder."""
    want = (0, outward, 0)
    mb.oriented([(xa, y, z_lo), (xb, y, z_lo), (xb, y, w_lo), (xa, y, w_lo)], BI["cladding"], want)
    mb.oriented([(xa, y, w_hi), (xb, y, w_hi), (xb, y, z_hi), (xa, y, z_hi)], BI["cladding"], want)
    edges = [xa]
    for a, b in bays:
        edges += [a + gap, b - gap]
    edges.append(xb)
    for i in range(0, len(edges), 2):
        x0, x1 = edges[i], edges[i + 1]
        if x1 - x0 > 0.01:
            mb.oriented([(x0, y, w_lo), (x1, y, w_lo), (x1, y, w_hi), (x0, y, w_hi)], BI["cladding"], want)
    # Laibungen
    for a, b in bays:
        x0, x1 = a + gap, b - gap
        yi = y - outward * 0.18
        mb.oriented([(x0, y, w_lo), (x0, yi, w_lo), (x0, yi, w_hi), (x0, y, w_hi)], BI["cladding"], (1, 0, 0))
        mb.oriented([(x1, yi, w_lo), (x1, y, w_lo), (x1, y, w_hi), (x1, yi, w_hi)], BI["cladding"], (-1, 0, 0))
        mb.oriented([(x0, y, w_hi), (x1, y, w_hi), (x1, yi, w_hi), (x0, yi, w_hi)], BI["cladding"], (0, 0, -1))


def pv_field(mb, x0, x1, y0, y1, z):
    """Ost-West-Aufständerung, flach geneigt (10°)."""
    mw, ml, tilt = 1.13, 1.72, math.radians(10)
    dy = mw * math.cos(tilt)
    dz = mw * math.sin(tilt)
    y = y0
    while y + 2 * dy <= y1:
        x = x0
        while x + ml <= x1:
            for side in (0, 1):
                ya, yb = (y, y + dy) if side == 0 else (y + 2 * dy, y + dy)
                za, zb = z + 0.18, z + 0.18 + dz
                pts = [(x, ya, za), (x + ml, ya, za), (x + ml, yb, zb), (x, yb, zb)]
                mb.oriented(pts, BI["pv"], (0, 0, 1), uv=[(0, 0), (1, 0), (1, 1), (0, 1)])
                mb.oriented([(x, ya, za - 0.04), (x + ml, ya, za - 0.04), (x + ml, ya, za), (x, ya, za)],
                            BI["frame"], (0, -1 if side == 0 else 1, 0))
            x += ml + 0.02
        mb.box(x0, x, y + dy - 0.05, y + dy + 0.05, z, z + 0.18 + dz, BI["frame"])
        y += 2 * dy + 0.45


def build_bauteil(name, parent, loc, rot=0.0, mirror=False, end0=False, end1=True, collection=None):
    root = empty(name, parent, loc, rot, (-1 if mirror else 1, 1, 1), collection)
    mb = MB()
    # --- Erdgeschoss: Schaufenster (Ostseite zur B54) ---
    zg0, zg1 = 0.02, 4.3
    for i in range(len(EG_PIERS) - 1):
        a, b = EG_PIERS[i], EG_PIERS[i + 1]
        if (a, b) == CORE:
            continue
        x0, x1 = a + 0.18, b - 0.18
        mb.face([(x0, 0.0, zg0), (x1, 0.0, zg0), (x1, 0.0, zg1), (x0, 0.0, zg1)], BI["glass"])
        k = max(2, round((x1 - x0) / 1.8))
        for j in range(1, k):
            xm = x0 + (x1 - x0) * j / k
            mb.box(xm - 0.03, xm + 0.03, -0.06, 0.02, zg0, zg1, BI["frame"])
        mb.box(x0, x1, -0.06, 0.02, 3.05, 3.11, BI["frame"])
        mb.box(x0, x1, -0.06, 0.02, zg0, zg0 + 0.08, BI["frame"])
        mb.box(x0, x1, -0.06, 0.02, zg1 - 0.06, zg1, BI["frame"])
        # Innenraum (Tiefe, Licht)
        mb.box(x0, x1, 0.05, 9.0, -0.02, 0.0, BI["int_floor"], skip=("bottom",))
        mb.face([(x1, 9.0, 0), (x0, 9.0, 0), (x0, 9.0, 4.3), (x1, 9.0, 4.3)], BI["int_wall"])
        for yy in (1.5, 4.0, 6.5):
            mb.face([(x0 + 0.6, yy, 4.28), (x0 + 0.6, yy + 0.25, 4.28), (x1 - 0.6, yy + 0.25, 4.28),
                     (x1 - 0.6, yy, 4.28)], BI["int_ceiling"])
        mb.face([(x0, 0.05, 4.3), (x0, 9.0, 4.3), (x1, 9.0, 4.3), (x1, 0.05, 4.3)], BI["int_wall"])
        if i > 0:
            mb.face([(x0, 9.0, 0), (x0, 0.05, 0), (x0, 0.05, 4.3), (x0, 9.0, 4.3)], BI["int_wall"])
    for x in EG_PIERS:
        if x in (CORE[0], CORE[1]):
            continue
        xa = max(0.0, x - 0.18) if x > 0 else 0.0
        xb = min(L_EG, x + 0.18)
        mb.box(xa, xb, -0.12, 0.3, 0.0, Z_SOFF, BI["plaster"])
    mb.box(0.0 if end0 else 0.0, L_EG, -0.1, 0.05, zg1, Z_SOFF, BI["frame"], skip=("top",))
    # --- Erdgeschoss: Stirnseiten ---
    for ex, on in ((0.0, end0), (L_EG, end1)):
        if not on:
            continue
        s = 1 if ex > 0 else -1
        x_out = ex
        x_in = ex - s * 0.3
        mb.box(min(x_out, x_in), max(x_out, x_in), 4.6, D_EG, 0.0, Z_OGF, BI["plaster"], top=BI["coping"])
        # Eckverglasung
        mb.oriented([(x_out - s * 0.05, 0.3, zg0), (x_out - s * 0.05, 4.6, zg0), (x_out - s * 0.05, 4.6, zg1),
                     (x_out - s * 0.05, 0.3, zg1)], BI["glass"], (s, 0, 0))
        mb.box(x_out - s * 0.12, x_out, 2.4, 2.46, zg0, zg1, BI["frame"])
        mb.box(min(x_out, x_in), max(x_out, x_in), 0.3, 4.6, zg1, Z_SOFF, BI["plaster"])
        # kleines Fenster im Lagerbereich
        for yy in (12.0, 20.5):
            mb.box(x_out - s * 0.02, x_out + s * 0.03, yy, yy + 2.4, 1.6, 2.8, BI["glass"])
            mb.box(x_out - s * 0.02, x_out + s * 0.05, yy - 0.05, yy + 2.45, 1.52, 1.6, BI["coping"])
    # --- Erdgeschoss: Rückseite (Anlieferung) ---
    mb.box(0.0, L_EG, D_EG - 0.3, D_EG, 0.0, Z_OGF, BI["plaster"], skip=("top",) if True else ())
    for xc, wd in LAGER_DOORS:
        mb.box(xc - wd / 2, xc + wd / 2, D_EG, D_EG + 0.04, 0.0, 3.6, BI["door"])
        mb.box(xc - wd / 2 - 0.08, xc + wd / 2 + 0.08, D_EG, D_EG + 0.06, 3.6, 3.7, BI["frame"])
        mb.box(xc + wd / 2 + 0.6, xc + wd / 2 + 1.6, D_EG, D_EG + 0.04, 0.0, 2.2, BI["door"])
    for xc in BUERO_DOORS:
        mb.box(xc - 0.55, xc + 0.55, D_EG, D_EG + 0.04, 0.0, 2.2, BI["door"])
        mb.box(xc - 1.4, xc - 0.7, D_EG, D_EG + 0.03, 1.1, 2.3, BI["glass"])
    # --- Lagerdach (eingeschossig, hinten) ---
    mb.box(0.0, L_EG, Y_OG1, D_EG - 0.3, Z_OGF - 0.25, Z_OGF, BI["gravel"], skip=("bottom",))
    mb.box(0.0, L_EG, D_EG - 0.3, D_EG, Z_OGF, Z_OGF + 0.6, BI["plaster"], top=BI["coping"])
    for ex, on in ((0.0, end0), (L_EG, end1)):
        if on:
            s = 1 if ex > 0 else -1
            mb.box(ex - s * 0.3, ex, Y_OG1, D_EG, Z_OGF, Z_OGF + 0.6, BI["plaster"], top=BI["coping"])
    # --- Obergeschoss ---
    x_og0 = -2.0 if end0 else 0.0
    x_og1 = L_OG
    bays_front = [b for b in OG_BAYS]
    if end0:
        bays_front = [(x_og0 + 0.35, 0.15 + 5.55 - 2.0 + 2.0)] + bays_front[1:]
    cladding_with_openings(mb, Y_OG0, [b for b in bays_front], Z_SOFF, Z_PAR, 6.0, 7.7, x_og0, x_og1, outward=-1)
    facade_windows(mb, Y_OG0, -1, bays_front, 6.0, 7.7)
    cladding_with_openings(mb, Y_OG1, bays_front, Z_OGF - 0.1, Z_PAR, 6.0, 7.7, x_og0, x_og1, outward=1)
    facade_windows(mb, Y_OG1, 1, bays_front, 6.0, 7.7)
    for ex, on in ((x_og0, end0 or True), (x_og1, True)):
        if ex == 0.0 and not end0:
            continue
        s = 1 if ex > 0 else -1
        bays_end = [(Y_OG0 + 0.6, Y_OG0 + 6.6), (Y_OG1 - 6.6, Y_OG1 - 0.6)]
        P = lambda yy, z: (ex, yy, z)  # noqa: E731
        want = (s, 0, 0)
        mb.oriented([P(Y_OG0, Z_SOFF), P(Y_OG1, Z_SOFF), P(Y_OG1, 6.0), P(Y_OG0, 6.0)], BI["cladding"], want,
                    uv=[(Y_OG0, Z_SOFF), (Y_OG1, Z_SOFF), (Y_OG1, 6.0), (Y_OG0, 6.0)])
        mb.oriented([P(Y_OG0, 7.7), P(Y_OG1, 7.7), P(Y_OG1, Z_PAR), P(Y_OG0, Z_PAR)], BI["cladding"], want,
                    uv=[(Y_OG0, 7.7), (Y_OG1, 7.7), (Y_OG1, Z_PAR), (Y_OG0, Z_PAR)])
        edges = [Y_OG0, bays_end[0][0], bays_end[0][1], bays_end[1][0], bays_end[1][1], Y_OG1]
        for i in range(0, 6, 2):
            mb.oriented([P(edges[i], 6.0), P(edges[i + 1], 6.0), P(edges[i + 1], 7.7), P(edges[i], 7.7)],
                        BI["cladding"], want,
                        uv=[(edges[i], 6.0), (edges[i + 1], 6.0), (edges[i + 1], 7.7), (edges[i], 7.7)])
        for a, b in bays_end:
            xg = ex - s * 0.18
            mb.oriented([(xg, a, 6.0), (xg, b, 6.0), (xg, b, 7.7), (xg, a, 7.7)], BI["glass"], want)
            mb.box(min(ex, xg), max(ex, xg), a, b, 5.94, 6.0, BI["coping"])
            for j in range(1, 4):
                ym = a + (b - a) * j / 4
                mb.box(xg - 0.03, xg + 0.03, ym - 0.03, ym + 0.03, 6.0, 7.7, BI["frame"])
    # Untersicht der Auskragung (vorne und an der verlängerten Stirnseite)
    mb.face([(x_og0, Y_OG0, Z_SOFF), (x_og0, 0.0, Z_SOFF), (x_og1, 0.0, Z_SOFF), (x_og1, Y_OG0, Z_SOFF)],
            BI["soffit"])
    mb.face([(L_EG, 0.0, Z_SOFF), (L_EG, Y_OG1, Z_SOFF), (x_og1, Y_OG1, Z_SOFF), (x_og1, 0.0, Z_SOFF)],
            BI["soffit"])
    if end0:
        mb.face([(x_og0, 0.0, Z_SOFF), (x_og0, Y_OG1, Z_SOFF), (0.0, Y_OG1, Z_SOFF), (0.0, 0.0, Z_SOFF)],
                BI["soffit"])
    # Downlights in der Untersicht (leuchten in der Abendansicht)
    xd = x_og0 + 1.4
    while xd < x_og1 - 1.0:
        if not (CORE[0] - 0.6 < xd < CORE[1] + 0.6):
            mb.face([(xd - 0.09, -1.09, Z_SOFF - 0.005), (xd - 0.09, -0.91, Z_SOFF - 0.005),
                     (xd + 0.09, -0.91, Z_SOFF - 0.005), (xd + 0.09, -1.09, Z_SOFF - 0.005)], BI["lamp_light"])
        xd += 2.775
    # OG-Innenräume hinter den Fenstern
    for yb, yw in ((Y_OG0, Y_OG0 + 4.2), (Y_OG1, Y_OG1 - 4.2)):
        mb.box(x_og0 + 0.3, x_og1 - 0.3, min(yb, yw), max(yb, yw), 8.48, 8.5, BI["int_ceiling"], skip=("top",))
        mb.face([(x_og0 + 0.3, yw, 5.0), (x_og1 - 0.3, yw, 5.0), (x_og1 - 0.3, yw, 8.5), (x_og0 + 0.3, yw, 8.5)],
                BI["int_wall"])
        mb.box(x_og0 + 0.3, x_og1 - 0.3, min(yb, yw), max(yb, yw), 5.0, 5.02, BI["int_floor"], skip=("bottom",))
    # Dach, Attika, Abdeckung
    t = 0.3
    # Gründach: gesamte Dachfläche mit Sedum, PV-Module darüber aufgeständert
    mb.box(x_og0 + t, x_og1 - t, Y_OG0 + t, Y_OG1 - t, Z_ROOF - 0.3, Z_ROOF, BI["roof"], top=BI["sedum"],
           skip=("bottom",))
    for (xa, xb, ya, yb) in ((x_og0, x_og1, Y_OG0, Y_OG0 + t), (x_og0, x_og1, Y_OG1 - t, Y_OG1),
                             (x_og0, x_og0 + t, Y_OG0, Y_OG1), (x_og1 - t, x_og1, Y_OG0, Y_OG1)):
        mb.box(xa, xb, ya, yb, Z_ROOF, Z_PAR, BI["cladding"], top=BI["coping"], skip=("bottom",))
    mb.box(x_og0 - 0.03, x_og1 + 0.03, Y_OG0 - 0.03, Y_OG0 + t, Z_PAR, Z_PAR + 0.04, BI["coping"])
    mb.box(x_og0 - 0.03, x_og1 + 0.03, Y_OG1 - t, Y_OG1 + 0.03, Z_PAR, Z_PAR + 0.04, BI["coping"])
    # Stiegenhaus: Holzlamellen über beide Geschosse, Eingang darunter
    cx0, cx1 = CORE[0] - 0.25, CORE[1] + 0.25
    yl = Y_OG0 - 0.3
    mb.box(cx0, cx1, yl + 0.12, Y_OG0, 3.0, Z_PAR + 0.04, BI["frame"])
    xs = cx0 + 0.04
    while xs < cx1 - 0.08:
        mb.box(xs, xs + 0.07, yl - 0.1, yl + 0.1, 3.0, Z_PAR + 0.25, BI["timber"])
        xs += 0.16
    mb.box(cx0 - 0.08, cx1 + 0.08, yl - 0.18, Y_OG0, 2.85, 3.0, BI["timber"])
    for xx in (cx0 - 0.08, cx1):
        mb.box(xx, xx + 0.08, yl - 0.18, Y_OG0, 0.0, 3.0, BI["timber"])
    mb.face([(cx0, -1.2, 0.02), (cx1, -1.2, 0.02), (cx1, -1.2, 2.85), (cx0, -1.2, 2.85)], BI["glass"])
    xm = (cx0 + cx1) / 2
    mb.box(xm - 0.03, xm + 0.03, -1.25, -1.15, 0.02, 2.85, BI["frame"])
    mb.box(cx0, cx1, -1.25, -1.15, 2.35, 2.42, BI["frame"])
    mb.face([(cx0, -1.15, 0.0), (cx0, D_EG * 0.3, 0.0), (cx0, D_EG * 0.3, 2.85), (cx0, -1.15, 2.85)],
            BI["int_wall"])
    mb.face([(cx1, D_EG * 0.3, 0.0), (cx1, -1.15, 0.0), (cx1, -1.15, 2.85), (cx1, D_EG * 0.3, 2.85)],
            BI["int_wall"])
    mb.face([(cx0, -1.15, 2.85), (cx1, -1.15, 2.85), (cx1, 6, 2.85), (cx0, 6, 2.85)], BI["int_ceiling"])
    mb.box(cx0, cx1, -1.15, 6, -0.02, 0.0, BI["int_floor"], skip=("bottom",))
    mb.box(cx0, cx1, 6, 6.2, 0.0, 2.85, BI["int_wall"])
    # Dachausstieg und Haustechnik
    mb.box(CORE[0] + 0.2, CORE[1] - 0.2, 6.5, 10.5, Z_ROOF, Z_ROOF + 1.1, BI["cladding"], top=BI["coping"])
    for hx in (8.0, 40.0):
        mb.box(hx, hx + 2.2, 13.8, 15.2, Z_ROOF, Z_ROOF + 1.3, BI["coping"])
    # PV-Felder (laut Renderings vorgesehen; Leistung nicht zugesichert)
    fields = [(x_og0 + 1.3, CORE[0] - 0.6), (CORE[1] + 0.6, x_og1 - 1.3)]
    for fx0, fx1 in fields:
        pv_field(mb, fx0, fx1, Y_OG0 + 1.0, Y_OG1 - 3.2, Z_ROOF)
    ob = mb.build(name + "_Gebaeude", [M(n) for n in BMATS], parent=root, collection=collection)
    for xa, xb in ((x_og0 + 0.5, CORE[0] - 0.4), (CORE[1] + 0.4, x_og1 - 0.5)):
        dusk_light(name + f"_Untersicht_{xa:.0f}", collection, root, ((xa + xb) / 2, -1.0, Z_SOFF - 0.05), "AREA",
                   55 * (xb - xa), size=xb - xa, size_y=1.2)
    dusk_light(name + "_Eingang", collection, root, ((CORE[0] + CORE[1]) / 2, -1.6, 2.7), "AREA", 120, 2.6, 1.0)
    for x in np.arange(3.0, L_EG - 1.0, 5.6):
        if not (CORE[0] - 1 < x < CORE[1] + 1):
            dusk_light(name + f"_Laden_{x:.0f}", collection, root, (x, 4.5, 4.1), "AREA", 260, 3.5, 3.5)
    return root, ob


# --------------------------------------------------------------------------------------
# Begrünung, Terrasse, Garagen (Feedback 18.11.2026, Plan 22-029_001)
# --------------------------------------------------------------------------------------
_ICO = None


def ico_unit():
    """Einheits-Ikosaeder (Subdiv 1) als (Vertices, Faces) für schnelle Kleinteile im MB."""
    global _ICO
    if _ICO is None:
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)
        _ICO = ([tuple(v.co) for v in bm.verts], [tuple(v.index for v in f.verts) for f in bm.faces])
        bm.free()
    return _ICO


def mb_blob(mb, ctr, r, mat, rnd, squash=(1.0, 1.0, 1.0), jitter=0.25):
    V, F = ico_unit()
    k = [1 + rnd.uniform(-jitter, jitter) for _ in V]
    P = [(ctr[0] + v[0] * r * squash[0] * k[i], ctr[1] + v[1] * r * squash[1] * k[i],
          ctr[2] + v[2] * r * squash[2] * k[i]) for i, v in enumerate(V)]
    for f in F:
        mb.face([P[i] for i in f], mat, uv=[(0, 0), (1, 0), (1, 1)])


def make_tufts(c):
    """Vorlagen für Dachbegrünung: Grasbüschel und Sedum-Polster (für Instanzierung)."""
    obs = []
    for k in range(3):
        rnd = random.Random(70 + k)
        mb = MB()
        if k < 2:
            for _ in range(14):
                a = rnd.uniform(0, 6.283)
                h = rnd.uniform(0.12, 0.28)
                lean = rnd.uniform(0.02, 0.09)
                x, y = math.cos(a) * 0.03, math.sin(a) * 0.03
                tx, ty = x + math.cos(a) * lean, y + math.sin(a) * lean
                w = 0.012
                mb.face([(x - w * math.sin(a), y + w * math.cos(a), 0), (x + w * math.sin(a), y - w * math.cos(a), 0),
                         (tx, ty, h)], 0, uv=[(0, 0), (1, 0), (0.5, 1)])
        else:
            for _ in range(5):
                mb_blob(mb, (rnd.uniform(-0.08, 0.08), rnd.uniform(-0.08, 0.08), 0.02), 0.07, 1, rnd,
                        squash=(1, 1, 0.45))
        ob = mb.build(f"Dachbewuchs_{k}", [M("grass_tuft"), M("sedum")], collection=c)
        obs.append(ob)
    return obs


def scatter_roof(name, parent, collection, tuft_coll, rects, z, density=2.2, seed=1):
    rng = np.random.default_rng(seed)
    pts = []
    for x0, x1, y0, y1 in rects:
        n = int(abs((x1 - x0) * (y1 - y0)) * density)
        X = rng.uniform(x0, x1, n)
        Y = rng.uniform(y0, y1, n)
        pts.append(np.column_stack([X, Y, np.full(n, z)]))
    P = np.concatenate(pts)
    n = len(P)
    ob = scatter(name, tuft_coll, P, rng.uniform(0, 6.283, n), rng.uniform(0.7, 1.4, n),
                 rng.choice([0, 1, 2], n, p=[0.35, 0.25, 0.4]), collection)
    ob.parent = parent
    return ob


TERR_MATS = ["timber", "planter", "glass", "coping", "leaf", "parasol", "anthracite", "wood_bench", "skin",
             "sedum", "leaf_obst", "bark"] + [f"cloth_{i}" for i in range(8)]
TI = {n: i for i, n in enumerate(TERR_MATS)}


def person(mb, x, y, z, rnd, seated=False, face=0.0):
    """Einfache Figur (sitzend oder stehend), Blickrichtung face (rad)."""
    c, s = math.cos(face), math.sin(face)
    rot = lambda dx, dy: (x + dx * c - dy * s, y + dx * s + dy * c)  # noqa: E731
    cloth = TI[f"cloth_{rnd.randrange(8)}"]
    legs = TI[f"cloth_{rnd.choice([0, 5, 3])}"]

    def obox(cx, cy, w, d, z0, z1, mat):
        pts = [rot(cx - w / 2, cy - d / 2), rot(cx + w / 2, cy - d / 2), rot(cx + w / 2, cy + d / 2),
               rot(cx - w / 2, cy + d / 2)]
        for i in range(4):
            a, b = pts[i], pts[(i + 1) % 4]
            mb.face([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)], mat)
        mb.face([(p[0], p[1], z1) for p in pts], mat)

    if seated:
        obox(0.0, 0.18, 0.34, 0.42, z + 0.45, z + 0.6, legs)       # Oberschenkel
        obox(0.0, 0.38, 0.30, 0.12, z, z + 0.48, legs)             # Unterschenkel
        obox(0.0, -0.02, 0.40, 0.24, z + 0.6, z + 1.15, cloth)     # Oberkörper
        hz = z + 1.28
    else:
        obox(0.0, 0.0, 0.32, 0.2, z, z + 0.86, legs)
        obox(0.0, 0.0, 0.42, 0.25, z + 0.86, z + 1.45, cloth)
        hz = z + 1.58
    mb_blob(mb, (x, y, hz), 0.11, TI["skin"], rnd, jitter=0.03)


def build_terrace(name, root, collection, end0, rnd):
    """Dachterrasse auf dem eingeschossigen Teil hinten (Richtung Wald): Deck, Beete, Geländer, Möbel, Personen."""
    mb = MB()
    z = Z_OGF
    y0, y1 = Y_OG1 + 0.05, D_EG - 0.3
    xa, xb = 0.35, L_EG - 0.35
    mb.box(xa, xb, y0, y1 - 1.0, z, z + 0.08, TI["timber"])
    # Pflanzbeet entlang der Brüstung mit Stauden und Gräsern
    mb.box(xa, xb, y1 - 1.0, y1, z, z + 0.5, TI["planter"], top=TI["sedum"])
    x = xa + 0.4
    while x < xb - 0.3:
        mb_blob(mb, (x, y1 - 0.5, z + 0.62), rnd.uniform(0.28, 0.42), TI["leaf"], rnd, squash=(1.2, 1.0, 0.8))
        x += rnd.uniform(0.5, 0.9)
    # Glasgeländer auf der Brüstung (Brüstung bis 0,6 m, Geländer bis 1,1 m über Deck)
    for gy in (D_EG - 0.12,):
        mb.box(0.0, L_EG, gy - 0.01, gy + 0.01, z + 0.6, z + 1.1, TI["glass"])
        mb.box(0.0, L_EG, gy - 0.03, gy + 0.03, z + 1.1, z + 1.14, TI["coping"])
    # Tischgruppen mit Schirmen und Personen; dazwischen Pflanzkübel mit kleinen Bäumen
    groups = [3.5, 10.5, 17.5, 29.0, 36.0, 43.5]
    for i, gx in enumerate(groups):
        ty = (y0 + y1 - 1.0) / 2 + rnd.uniform(-0.3, 0.3)
        mb.box(gx - 0.45, gx + 0.45, ty - 0.45, ty + 0.45, z + 0.72, z + 0.76, TI["wood_bench"])
        mb.box(gx - 0.04, gx + 0.04, ty - 0.04, ty + 0.04, z + 0.08, z + 0.72, TI["anthracite"])
        seats = [(gx - 0.85, ty, -math.pi / 2), (gx + 0.85, ty, math.pi / 2), (gx, ty - 0.85, 0.0),
                 (gx, ty + 0.85, math.pi)]
        for k, (cx, cy, f) in enumerate(seats):
            mb.box(cx - 0.22, cx + 0.22, cy - 0.22, cy + 0.22, z + 0.42, z + 0.46, TI["anthracite"])
            for dx in (-0.18, 0.18):
                for dy in (-0.18, 0.18):
                    mb.box(cx + dx - 0.015, cx + dx + 0.015, cy + dy - 0.015, cy + dy + 0.015, z + 0.08, z + 0.42,
                           TI["anthracite"])
            if rnd.random() < (0.6 if i % 2 == 0 else 0.4):
                # Figur sitzt mit Blick zum Tisch
                fx, fy = gx - cx, ty - cy
                person(mb, cx, cy, z + 0.08, rnd, seated=True, face=math.atan2(-fx, fy))
        if i % 2 == 0:
            mb.box(gx - 0.03, gx + 0.03, ty - 0.03, ty + 0.03, z + 0.76, z + 2.4, TI["coping"])
            mb_blob(mb, (gx, ty, z + 2.35), 1.4, TI["parasol"], rnd, squash=(1, 1, 0.18), jitter=0.0)
        # Pflanzkübel mit Bäumchen zwischen den Gruppen
        px = gx + 3.5
        if px < xb - 1.0 and not (CORE[0] - 1.0 < px < CORE[1] + 1.0):
            py = y0 + 0.7
            mb.box(px - 0.45, px + 0.45, py - 0.45, py + 0.45, z + 0.08, z + 0.75, TI["planter"], top=TI["sedum"])
            mb.box(px - 0.04, px + 0.04, py - 0.04, py + 0.04, z + 0.75, z + 1.7, TI["bark"])
            mb_blob(mb, (px, py, z + 2.15), 0.65, TI["leaf_obst"], rnd, jitter=0.3)
    # einige stehende Personen an der Brüstung
    for gx in (7.0, 24.0, 40.0):
        if rnd.random() < 0.8:
            person(mb, gx + rnd.uniform(-1, 1), y1 - 1.4, z + 0.08, rnd, face=rnd.uniform(-0.4, 0.4))
    return mb.build(name + "_Terrasse", [M(n) for n in TERR_MATS], parent=root, collection=collection)


def facade_pier_positions(end0):
    """x-Positionen der fensterfreien Fassadenfelder vorne (zwischen den OG-Fensterbändern)."""
    x_og0 = -2.0 if end0 else 0.0
    bays = list(OG_BAYS)
    if end0:
        bays = [(x_og0 + 0.35, 0.15 + 5.55)] + bays[1:]
    xs = []
    edges = [x_og0 + 0.4] + [v for a, b in bays for v in (a + 0.55, b - 0.55)] + [L_OG - 0.4]
    # Lücken zwischen Fensterbändern: Mitte, Holzlamellen am Stiegenhaus aussparen
    for i in range(0, len(edges) - 1, 2):
        g0, g1 = edges[i], edges[i + 1]
        if CORE[0] - 0.6 < (g0 + g1) / 2 < CORE[1] + 0.6:
            continue
        w = g1 - g0
        if w > 4.5:  # fensterfreie Wand: alle 3–4 m
            n = int(w // 3.5)
            xs += [g0 + w * (j + 0.5) / n for j in range(n)]
        elif w > 0.4:
            xs.append((g0 + g1) / 2)
    return xs


VINE_MATS = ["steel_cable", "planter", "leaf_vine", "akebia_bloom", "sedum"]


def build_vines(name, root, collection, end0, rnd):
    """Rankpflanzen (Akebie) an je 3 Seilen vor der Fassade, auf die Fensterachsen abgestimmt."""
    mb = MB()
    yc = Y_OG0 - 0.16
    for x in facade_pier_positions(end0):
        mb.box(x - 0.42, x + 0.42, yc - 0.3, yc + 0.22, 0.0, 0.45, 1, top=4)  # Pflanztrog
        for dx in (-0.22, 0.0, 0.22):
            cx = x + dx
            mb.box(cx - 0.006, cx + 0.006, yc - 0.006, yc + 0.006, 0.45, Z_PAR - 0.15, 0)
            top = rnd.uniform(0.55, 0.95) * (Z_PAR - 0.6)
            zz = 0.5
            while zz < top:
                r = rnd.uniform(0.09, 0.17) * (1.0 - 0.35 * zz / Z_PAR)
                mb_blob(mb, (cx + rnd.uniform(-0.1, 0.1), yc - rnd.uniform(0.0, 0.1), zz), r, 2, rnd,
                        squash=(1.2, 0.6, 1.0), jitter=0.35)
                if rnd.random() < 0.06:
                    mb_blob(mb, (cx + rnd.uniform(-0.12, 0.12), yc - 0.14, zz), 0.035, 3, rnd, jitter=0.1)
                zz += rnd.uniform(0.13, 0.2)
    return mb.build(name + "_Rankpflanzen", [M(n) for n in VINE_MATS], parent=root, collection=collection)


def build_bauteil_gruen(name, root, collection, end0, tuft_coll, seed):
    rnd = random.Random(seed)
    build_terrace(name, root, collection, end0, rnd)
    build_vines(name, root, collection, end0, rnd)
    x_og0 = -2.0 if end0 else 0.0
    scatter_roof(name + "_Dachbewuchs", root, collection, tuft_coll,
                 [(x_og0 + 0.4, L_OG - 0.4, Y_OG0 + 0.4, Y_OG1 - 0.4)], Z_ROOF, seed=seed)


# Garagen (Gebäude 1G / 6,0 m laut Plan 22-029_001): hinter Bauteil 1+2, 8 m Zufahrt, 8 m Tiefe
GAR_PU = (-108.6, -22.9)
GAR_ANNEX = (-118.9, -108.6)
GAR_PV = (PV_BACK + 8.0, PV_BACK + 16.0)
GAR_H = 6.0


def build_garagen(plan, c, tuft_coll):
    mb = MB()
    z0 = LEVEL_A + 0.15
    v0, v1 = GAR_PV
    for (u0, u1), depth in ((GAR_PU, v1 - v0), (GAR_ANNEX, 5.0)):
        mb.box(u0, u1, v0, v0 + depth, z0, z0 + GAR_H - 0.3, BI["plaster"], skip=("top",))
        mb.box(u0 + 0.3, u1 - 0.3, v0 + 0.3, v0 + depth - 0.3, z0 + GAR_H - 0.6, z0 + GAR_H - 0.3, BI["roof"],
               top=BI["sedum"], skip=("bottom",))
        for (a, b, ya, yb) in ((u0, u1, v0, v0 + 0.3), (u0, u1, v0 + depth - 0.3, v0 + depth),
                               (u0, u0 + 0.3, v0, v0 + depth), (u1 - 0.3, u1, v0, v0 + depth)):
            mb.box(a, b, ya, yb, z0 + GAR_H - 0.3, z0 + GAR_H, BI["cladding"], top=BI["coping"])
        # dunkles Band über den Toren
        mb.box(u0, u1, v0 - 0.05, v0, z0 + 4.6, z0 + GAR_H - 0.3, BI["cladding"])
        n = max(1, round((u1 - u0) / 5.05))
        pitch = (u1 - u0) / n
        for i in range(n):
            xc = u0 + pitch * (i + 0.5)
            mb.box(xc - 1.8, xc + 1.8, v0 - 0.06, v0, z0, z0 + 4.3, BI["door"])
            mb.box(xc - 1.88, xc + 1.88, v0 - 0.08, v0, z0 + 4.3, z0 + 4.38, BI["frame"])
        if depth > 6:
            pv_field(mb, u0 + 1.0, u1 - 1.0, v0 + 1.0, v0 + depth - 1.0, z0 + GAR_H - 0.3)
    ob = mb.build("Garagen_1G", [M(n) for n in BMATS], parent=plan, collection=c)
    scatter_roof("Garagen_Dachbewuchs", plan, c, tuft_coll,
                 [(GAR_PU[0] + 0.4, GAR_PU[1] - 0.4, v0 + 0.4, v1 - 0.4)], z0 + GAR_H - 0.3, seed=99)
    return ob


# --------------------------------------------------------------------------------------
# Außenanlagen
# --------------------------------------------------------------------------------------


def plate(name, poly, z_off, mat, parent, collection, height=0.0, side_mat=None):
    """Planfläche (pu, pv), folgt der Geländeebene zl(pu); optional mit Bordstein-Kante."""
    poly = [tuple(p) for p in poly]
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:] + poly[:1]))
    if area < 0:
        poly = poly[::-1]
    bm = bmesh.new()
    vs = [bm.verts.new((p[0], p[1], 0)) for p in poly]
    bm.faces.new(vs)
    for cx in RAMP_CUTS:
        if min(p[0] for p in poly) < cx < max(p[0] for p in poly):
            geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
            bmesh.ops.bisect_plane(bm, geom=geom, plane_co=(cx, 0, 0), plane_no=(1, 0, 0))
    for v in bm.verts:
        v.co.z = float(zl(v.co.x)) + z_off - (0.05 if height > 0 else 0.0)
    if height > 0:
        res = bmesh.ops.extrude_face_region(bm, geom=bm.faces[:])
        for v in [g for g in res["geom"] if isinstance(g, bmesh.types.BMVert)]:
            v.co.z = float(zl(v.co.x)) + z_off + height
        for f in bm.faces:
            f.normal_update()
            f.material_index = 0 if f.normal.z > 0.5 else 1
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4 or f.normal.z > 0.5])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    me.materials.append(side_mat or mat)
    uvl = me.uv_layers.new(name="UVMap")
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        uvl.data[loop.index].uv = (co.x, co.y)
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    ob.parent = parent
    return ob


def rect(u0, u1, v0, v1):
    return [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]


def fillet_access(u0, u1, v_road, v_aisle, r=6.0, seg=6):
    """Zufahrt von der Fahrgasse zur B54 mit ausgerundeten Ecken."""
    pts = [(u0 - r, v_road)]
    for i in range(seg + 1):
        a = math.pi / 2 * i / seg
        pts.append((u0 - r + r * math.sin(a), v_road + r - r * math.cos(a)))
    pts += [(u0, v_aisle), (u1, v_aisle)]
    for i in range(seg + 1):
        a = math.pi / 2 * (1 - i / seg)
        pts.append((u1 + r - r * math.sin(a), v_road + r - r * math.cos(a)))
    pts.append((u1 + r, v_road))
    return pts


def site_boundary_pv(pu):
    """pv der hinteren Grundstücksgrenze bei pu (oberer Polygonzug)."""
    best = None
    n = len(SITE)
    for i in range(n):
        (x1, y1), (x2, y2) = SITE[i], SITE[(i + 1) % n]
        if (x1 - pu) * (x2 - pu) <= 0 and x1 != x2:
            y = y1 + (y2 - y1) * (pu - x1) / (x2 - x1)
            if y > 20 and (best is None or y < best):
                best = y
    return best


def build_site(plan, c, tree_objs):
    S = []
    S.append(plate("Rasen_Grundstueck", [tuple(p) for p in SITE], 0.0, M("grass"), plan, c))
    u_s, u_n = FRONT_PU
    S.append(plate("Parken_Rasengitter", rect(u_s, PARK_END, PV_PARK, PV_AISLE), 0.03, M("grasspavers"), plan, c))
    aisle = rect(u_s - 7.0, u_n + 2.0, PV_AISLE, PV_WALK)
    S.append(plate("Fahrgasse", aisle, 0.04, M("asphalt"), plan, c))
    S.append(plate("Zufahrt_Sued", fillet_access(*ACCESS_PU, -2.4, PV_AISLE + 0.5, r=9.0), 0.045, M("asphalt"),
                   plan, c))
    S.append(plate("Gehweg", rect(u_s, u_n - 4.0, PV_WALK, PV_FRONT + 0.4), 0.0, M("pavers"), plan, c,
                   height=0.14, side_mat=M("kerb")))
    S.append(plate("Hof_hinten", rect(u_s, u_n - 4.0, PV_BACK, PV_YARD), 0.04, M("asphalt"), plan, c))
    # Zufahrt vor den Garagen (8 m)
    S.append(plate("Hof_Garagen", rect(GAR_ANNEX[0] - 0.6, u_n - 4.0, PV_YARD - 0.2, GAR_PV[0] + 0.05), 0.04,
                   M("asphalt"), plan, c))
    S.append(plate("Umfahrt_Sued", rect(-19.5, -12.5, PV_WALK, PV_YARD), 0.042, M("asphalt"), plan, c))
    S.append(plate("Durchfahrt_BT3_BT4", rect(-201.5, -194.0, PV_WALK, PV_YARD), 0.042, M("asphalt"), plan, c))
    # Platz zwischen Bauteil 2 und 3 (Treffpunkt, Vorschlag)
    S.append(plate("Platz", rect(-137.4, -121.3, PV_FRONT, PV_BACK), 0.0, M("pavers_plaza"), plan, c,
                   height=0.12, side_mat=M("kerb")))
    S.append(plate("Platz_Rasen", rect(-134.5, -124.2, 24.0, 40.0), 0.13, M("grass_dark"), plan, c,
                   height=0.06, side_mat=M("kerb")))

    mk = MB()
    trees = []
    lamps = []
    stall = 2.5
    u = u_s + 0.5
    k = 0
    while u + stall <= PARK_END:
        if k % 6 == 5:
            S.append(plate(f"Baumscheibe_{k}", rect(u + 0.1, u + stall - 0.1, PV_PARK + 0.1, PV_AISLE - 0.3), 0.0,
                           M("grass_dark"), plan, c, height=0.15, side_mat=M("kerb")))
            trees.append(("strasse", u + stall / 2, (PV_PARK + PV_AISLE) / 2 - 0.2))
            if k % 12 == 11:
                lamps.append((u + stall / 2, PV_AISLE - 0.6))
        else:
            z = float(zl(u)) + 0.04
            mk.box(u - 0.06, u + 0.06, PV_PARK + 0.3, PV_AISLE - 0.1, z, z + 0.01, 0)
        u += stall
        k += 1
    mk.build("Stellplatz_Markierung", [M("marking")], parent=plan, collection=c)

    # Baumreihe im Grünstreifen an der B54 und Bäume hinten an der Grundstücksgrenze
    u = u_s + 4.0
    while u < u_n:
        if -244.0 < u < PARK_END - 1.0:
            trees.append(("strasse", u + random.uniform(-0.6, 0.6), 1.0 + random.uniform(-0.2, 0.2)))
        u += 12.5
    for pu in np.arange(-252, -12, 9.5):
        b = site_boundary_pv(pu)
        if b and b - 3.2 > PV_YARD + 1.0 and not (GAR_ANNEX[0] - 3 < pu < GAR_PU[1] + 3):
            trees.append(("laub" if random.random() < 0.55 else "strasse", pu + random.uniform(-1, 1), b - 3.2))
    for du, dv in ((-131.5, 27.0), (-127.0, 31.5), (-131.5, 36.5), (-127.0, 22.0)):
        trees.append(("obst", du, dv))
    for du, dv in ((-6.0, 20.0), (-2.0, 30.0), (-8.0, 40.0), (-232.0, 32.0)):
        trees.append(("obst", du, dv))

    tcoll = c
    for i, (kind, pu, pv) in enumerate(trees):
        src = random.choice(tree_objs[kind])
        ob = bpy.data.objects.new(f"Baum_{kind}_{i:03d}", src.data)
        tcoll.objects.link(ob)
        ob.parent = plan
        ob.location = (pu, pv, float(zl(pu)) + (0.15 if pv < PV_AISLE and pv > PV_PARK else 0.0))
        ob.rotation_euler = (0, 0, random.uniform(0, 6.283))
        s = random.uniform(0.85, 1.1)
        ob.scale = (s, s, s)

    # Hecke entlang der hinteren Grenze
    hb = MB()
    for pu in np.arange(-250, -14, 4.0):
        b0, b1 = site_boundary_pv(pu), site_boundary_pv(pu + 4.0)
        if b0 and b1 and min(b0, b1) - 1.2 > PV_YARD and not (GAR_ANNEX[0] - 4 < pu < GAR_PU[1] + 1):
            z = float(zl(pu))
            hb.box(pu, pu + 4.02, min(b0, b1) - 1.6, min(b0, b1) - 0.6, z, z + 1.5, 0)
    ob = hb.build("Hecke", [M("leaf")], parent=plan, collection=c)
    ob.modifiers.new("Bevel", "BEVEL").width = 0.3

    # Leuchten, Bänke, Fahrradständer
    fx = MB()
    for pu, pv in lamps + [(-129.4, PV_FRONT + 1.0), (-200.0, PV_WALK + 0.6)]:
        z = float(zl(pu)) + 0.15
        fx.box(pu - 0.07, pu + 0.07, pv - 0.07, pv + 0.07, z, z + 6.0, 0)
        fx.box(pu - 0.15, pu + 0.15, pv - 0.9, pv + 0.15, z + 6.0, z + 6.12, 0)
        fx.box(pu - 0.12, pu + 0.12, pv - 0.85, pv - 0.1, z + 5.98, z + 6.0, 2)
        dusk_light(f"Leuchte_{pu:.0f}", c, plan, (pu, pv - 0.5, z + 5.9), "SPOT", 700, size=math.radians(130))
    for pu, pv in ((-133.5, 25.0), (-133.5, 33.0), (-125.0, 29.0), (-125.0, 37.0)):
        z = float(zl(pu)) + 0.12
        fx.box(pu - 0.9, pu + 0.9, pv - 0.25, pv + 0.25, z + 0.42, z + 0.47, 1)
        for d in (-0.75, 0.75):
            fx.box(pu + d - 0.04, pu + d + 0.04, pv - 0.22, pv + 0.22, z, z + 0.42, 0)
    fx.build("Ausstattung", [M("anthracite"), M("wood_bench"), M("lamp_light")], parent=plan, collection=c)
    return S


def dusk_light(name, c, parent, loc, kind, energy, size=1.0, size_y=None, color=(1.0, 0.8, 0.58)):
    """Warmes Kunstlicht für die Abendansicht (strahlt nach unten)."""
    li = bpy.data.lights.new(name, kind)
    li.energy = energy
    li.color = color
    if kind == "AREA":
        li.shape = "RECTANGLE"
        li.size = size
        li.size_y = size_y or size
    elif kind == "SPOT":
        li.spot_size = size
        li.spot_blend = 0.6
        li.shadow_soft_size = 0.15
    ob = bpy.data.objects.new(name, li)
    c.objects.link(ob)
    ob.parent = parent
    ob.location = loc
    DUSK_LIGHTS.append(ob)
    return ob


def build_pylon(name, plan, c, pu, pv, rot):
    root = empty(name, plan, (pu, pv, float(zl(pu))), rot, collection=c)
    mb = MB()
    W, D, H = 2.0, 0.45, 7.2
    mb.box(-W / 2, W / 2, -D / 2, D / 2, 0.0, H, 0, top=1)
    mb.box(-W / 2 - 0.05, W / 2 + 0.05, -D / 2 - 0.05, D / 2 + 0.05, -0.2, 0.25, 2)
    lw, lh = 1.76, 1.76 / 2.993
    for s in (-1, 1):
        y = s * (D / 2 + 0.006)
        pts = [(-lw / 2, y, 5.9), (lw / 2, y, 5.9), (lw / 2, y, 5.9 + lh), (-lw / 2, y, 5.9 + lh)]
        uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
        if s > 0:
            pts = [pts[1], pts[0], pts[3], pts[2]]
        mb.face(pts, 3, uv)
        mb.box(-lw / 2, lw / 2, y - 0.004 * s, y + 0.004 * s, 5.55, 5.58, 4)
    mb.build(name + "_Stele", [M("pylon"), M("coping"), M("concrete"), M("logo"), M("brand_gold")],
             parent=root, collection=c)
    font = bpy.data.fonts.load(str(FONT), check_existing=True)
    for s in (-1, 1):
        for txt, z, size in (("GEWERBEPARK", 5.2, 0.2), ("PISCHELSDORF AM KULM", 4.88, 0.13)):
            cu = bpy.data.curves.new(f"{name}_{txt}_{s}", "FONT")
            cu.body = txt
            cu.font = font
            cu.size = size
            cu.align_x = "CENTER"
            cu.extrude = 0.004
            cu.space_character = 1.08
            ob = bpy.data.objects.new(cu.name, cu)
            c.objects.link(ob)
            ob.parent = root
            ob.data.materials.append(M("brand_text"))
            ob.location = (0, s * (D / 2 + 0.006), z)
            ob.rotation_euler = (math.pi / 2, 0, 0 if s < 0 else math.pi)
    return root


def build_logo_panel(name, parent, c, x, y, z, w, out_dir):
    """Logotafel auf der Fassade (Stirnseite Bauteil 1 Richtung Süden, zum Ort)."""
    mb = MB()
    h = w / 2.993
    pad = 0.35
    mb.box(-0.06, 0.0, -w / 2 - pad, w / 2 + pad, -h / 2 - pad, h / 2 + pad, 0)
    mb.face([(0.002, -w / 2, -h / 2), (0.002, w / 2, -h / 2), (0.002, w / 2, h / 2), (0.002, -w / 2, h / 2)], 1,
            [(0, 0), (1, 0), (1, 1), (0, 1)])
    root = empty(name, parent, (x, y, z), out_dir, collection=c)
    mb.build(name + "_Tafel", [M("pylon"), M("logo")], parent=root, collection=c)
    return root


# Moderne Fahrzeugtypen: Länge, Breite, Bodenfreiheit, Radradius, Gürtellinie hinten/vorn,
# Dachhöhe, Haubenhöhe an der Front, Fensterfläche (Anteil von hinten → vorn), Dachende hinten
CAR_TYPES = {
    "suv": dict(L=4.62, W=1.88, zb=0.40, r=0.37, belt=(1.08, 0.98), roof=1.68, nose=0.80, gh=(0.07, 0.62), rr=0.05),
    "kompakt": dict(L=4.15, W=1.80, zb=0.33, r=0.33, belt=(1.00, 0.90), roof=1.47, nose=0.70, gh=(0.08, 0.63), rr=0.06),
    "limousine": dict(L=4.85, W=1.86, zb=0.32, r=0.34, belt=(0.98, 0.88), roof=1.44, nose=0.68, gh=(0.20, 0.62), rr=0.0),
    "kombi": dict(L=4.75, W=1.84, zb=0.33, r=0.34, belt=(1.00, 0.90), roof=1.50, nose=0.69, gh=(0.05, 0.63), rr=0.03),
    "transporter": dict(L=5.30, W=2.02, zb=0.36, r=0.36, belt=(1.20, 1.15), roof=2.30, nose=1.00, gh=(0.03, 0.80),
                        rr=0.02),
}


def make_car(name, c, paint, kind="suv", roof_black=False):
    """Zeitgemäßer Pkw/Transporter als geglätteter Loft: Karosserie, Glashaus, große Räder, LED-Leisten."""
    T = CAR_TYPES[kind]
    L, W = T["L"], T["W"]
    bm = bmesh.new()
    mats = [paint, M("car_glass"), M("tyre"), M("car_rim"), M("car_led"), M("brake_light"), M("car_trim"),
            M("car_trim") if roof_black else paint]
    NS, NR = 34, 28  # Stationen entlang x, Punkte je Querschnitt

    def loft(fx, zb, zt, wb, wt, p, mat_fn):
        """fx: Stationen (Meter); zb/zt/wb/wt: Funktionen von x; p: Superellipsen-Exponent."""
        rings = []
        for x in fx:
            ring = []
            for j in range(NR):
                a = 2 * math.pi * j / NR
                cs, sn = math.cos(a), math.sin(a)
                yy = math.copysign(abs(cs) ** (2 / p), cs)
                uu = math.copysign(abs(sn) ** (2 / p), sn)
                t = (uu + 1) / 2
                w = wb(x) + (wt(x) - wb(x)) * t
                z = zb(x) + (zt(x) - zb(x)) * t
                ring.append(bm.verts.new((x, yy * w / 2, z)))
            rings.append(ring)
        for i in range(len(rings) - 1):
            for j in range(NR):
                q = (rings[i][j], rings[i][(j + 1) % NR], rings[i + 1][(j + 1) % NR], rings[i + 1][j])
                f = bm.faces.new(q)
                f.material_index = mat_fn(f)
        for ring, rev in ((rings[0], True), (rings[-1], False)):
            ctr = bm.verts.new(sum((v.co for v in ring), Vector()) / NR)
            for j in range(NR):
                tri = (ring[j], ring[(j + 1) % NR], ctr)
                f = bm.faces.new(tri[::-1] if rev else tri)
                f.material_index = mat_fn(f)

    def smooth_interp(_xs, ks, vs):
        return lambda x: float(np.interp(x, ks, vs))

    x0, x1 = -L / 2, L / 2
    fr = lambda f: x0 + f * L  # noqa: E731
    van = kind == "transporter"
    # Unterbau: Seitenlinie mit abgerundeten Enden, Haube fällt zur Front ab
    ks = [fr(0), fr(0.025), fr(0.08), fr(0.70), fr(0.86), fr(0.975), fr(1)]
    bt, bf = T["belt"]
    top = smooth_interp(None, ks, [bt - 0.22, bt - 0.04, bt, bf + 0.02, bf - 0.04, T["nose"], T["nose"] - 0.12])
    bot = smooth_interp(None, ks, [T["zb"] + 0.18, T["zb"] + 0.06, T["zb"], T["zb"], T["zb"], T["zb"] + 0.05,
                                  T["zb"] + 0.16])
    wid = smooth_interp(None, ks, [W * 0.82, W * 0.96, W, W, W * 0.99, W * 0.94, W * 0.80])
    xs = [x0 + (x1 - x0) * (0.5 - 0.5 * math.cos(math.pi * i / (NS - 1))) for i in range(NS)]

    def body_mat(f):
        cz = f.calc_center_median().z
        return 6 if cz < T["zb"] + 0.14 else 0  # dunkle Schwellerverkleidung unten

    loft(xs, bot, top, wid, lambda x: wid(x) * 0.96, 3.2, body_mat)

    # Glashaus: von der Gürtellinie bis zum Dach, schmaler (Tumblehome), Dach in Wagen- oder Kontrastfarbe
    g0, g1 = fr(T["gh"][0]), fr(T["gh"][1])
    roof = T["roof"]
    if van:
        rk = [g0, g0 + 0.15, g1 - 0.35, g1]
        rv = [roof - 0.15, roof, roof, top(g1) + 0.02]
    else:
        rk = [g0, fr(T["gh"][0] + 0.07 + T["rr"]), fr(0.30), fr(0.50), g1]
        rv = [top(g0) + 0.02, roof - 0.04, roof, roof - 0.01, top(g1) + 0.02]
    gtop = smooth_interp(None, rk, rv)
    gbot = lambda x: top(x) - 0.04  # noqa: E731
    gx = [g0 + (g1 - g0) * i / (NS - 1) for i in range(NS)]

    def glass_mat(f):
        cz = f.calc_center_median().z
        x = f.calc_center_median().x
        return 7 if cz > gtop(x) - (0.07 if not van else 0.12) else 1

    loft(gx, gbot, gtop, lambda x: wid(x) * 0.92, lambda x: wid(x) * (0.74 if not van else 0.88), 4.0, glass_mat)

    # Räder mit Felgen und dunklen Radläufen
    r = T["r"]
    for sx, fx_ in ((-1, fr(0.19 if not van else 0.17)), (1, fr(0.80 if not van else 0.83))):
        for sy in (-1, 1):
            m = Matrix.Translation((fx_, sy * (W / 2 - 0.13), r)) @ Matrix.Rotation(math.pi / 2, 4, "X")
            res = bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=r, radius2=r, depth=0.26, matrix=m)
            for f in {f for v in res["verts"] for f in v.link_faces}:
                f.material_index = 2
            m2 = Matrix.Translation((fx_, sy * (W / 2 + 0.002), r)) @ Matrix.Rotation(math.pi / 2, 4, "X")
            res = bmesh.ops.create_cone(bm, cap_ends=True, segments=20, radius1=r * 0.66, radius2=r * 0.62,
                                        depth=0.02, matrix=m2)
            for f in {f for v in res["verts"] for f in v.link_faces}:
                f.material_index = 3
            # Radlauf: dunkler Halbring knapp außerhalb der Karosserie
            res = bmesh.ops.create_circle(bm, cap_ends=True, segments=20, radius=r + 0.035,
                                          matrix=Matrix.Translation((fx_, sy * (W / 2 + 0.001), r))
                                          @ Matrix.Rotation(math.pi / 2, 4, "X"))
            for f in {f for v in res["verts"] for f in v.link_faces}:
                f.material_index = 6
    # LED-Leisten: vorn weiß, hinten durchgehend rot
    zf, zr = T["nose"] - 0.02, bt - 0.12
    for x, z, mat, w in ((x1 - 0.03, zf, 4, W * 0.70), (x0 + 0.02, zr, 5, W * 0.76)):
        res = bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Translation((x, 0, z)) @ Matrix.Diagonal((0.05, w, 0.05, 1)))
        for f in {f for v in res["verts"] for f in v.link_faces}:
            f.material_index = mat
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
    if hasattr(me, "set_sharp_from_angle"):
        me.set_sharp_from_angle(angle=math.radians(40))
    ob = bpy.data.objects.new(name, me)
    c.objects.link(ob)
    return ob


# Index in der Fahrzeugliste: Rot, Weiß, Tiefblau, Petrol, Schwarz, Bronze, Dunkelgrün, Silber, Hellblau, Sand
FRONT_CARS = [5, 0, 4, 8, 3, 10, 7, 1, 11, 9, 6, 2]


def build_cars(plan, c, src_coll):
    kinds = ["suv", "kompakt", "kombi", "suv", "limousine", "kompakt"]
    cars = [make_car(f"PKW_{i}", src_coll, M(f"car_{i % 12}"), kinds[i % len(kinds)], roof_black=i % 5 == 2)
            for i in range(18)]
    van = make_car("Transporter", src_coll, M("car_0"), "transporter")
    rng = random.Random(3)
    u = FRONT_PU[0] + 0.5
    k = 0
    while u + 2.5 <= PARK_END:
        # vorderste Stellplätze (im Blick der Hero-/Zufahrtsansicht) fest belegt, gut unterscheidbare Farben
        j = int((PARK_END - u) / 2.5)
        front = j < 12
        if k % 6 != 5 and (front or rng.random() < (0.55 if u > -130 else 0.35)):
            src = cars[FRONT_CARS[j % len(FRONT_CARS)]] if front else rng.choice(cars)
            ob = bpy.data.objects.new(f"Auto_{k:03d}", src.data)
            c.objects.link(ob)
            ob.parent = plan
            ob.location = (u + 1.25, (PV_PARK + PV_AISLE) / 2 + rng.uniform(-0.15, 0.25) + 0.2, float(zl(u)) + 0.04)
            ob.rotation_euler = (0, 0, math.pi / 2 + (math.pi if rng.random() < 0.3 else 0) + rng.uniform(-0.03, 0.03))
        u += 2.5
        k += 1
    # Fahrende Autos im Vordergrund der Hero-Ansicht: einer biegt von der B54 ein, einer fährt auf der Fahrgasse
    for i, (idx, pu, pv, rot) in enumerate(((5, -37.0, 10.4, math.pi), (2, -50.0, 9.4, 0.0))):
        ob = bpy.data.objects.new(f"Auto_fahrend_{i}", cars[idx].data)
        c.objects.link(ob)
        ob.parent = plan
        ob.location = (pu, pv, float(zl(pu)) + 0.05)
        ob.rotation_euler = (0, 0, rot)
    for i, (pu, pv) in enumerate(((-33.0, 47.6), (-163.0, 47.8))):
        ob = bpy.data.objects.new(f"Transporter_{i}", van.data)
        c.objects.link(ob)
        ob.parent = plan
        ob.location = (pu, pv, float(zl(pu)) + 0.04)


# --------------------------------------------------------------------------------------
# Licht, Kameras, Rendern
# --------------------------------------------------------------------------------------
SUN_AZ, SUN_EL = 232.0, 36.0  # Spätsommer, Nachmittag; Schaufront zur B54 (WNW) im Licht


def setup_world(mood="day"):
    sc = bpy.context.scene
    w = sc.world or bpy.data.worlds.new("Welt")
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    sky = nt.nodes.new("ShaderNodeTexSky")
    for st in ("MULTIPLE_SCATTERING", "NISHITA", "HOSEK_WILKIE"):
        try:
            sky.sky_type = st
            break
        except TypeError:
            continue
    el = SUN_EL if mood != "dusk" else -4.5
    sky.sun_disc = False
    sky.sun_elevation = math.radians(el)
    sky.sun_rotation = math.radians(180 - SUN_AZ) % (2 * math.pi)
    sky.altitude = 400
    try:
        sky.aerosol_density = 0.25 if mood == "hero" else 1.6
        sky.air_density = 1.0
        sky.ozone_density = 2.5 if mood == "hero" else 1.0
    except AttributeError:
        pass
    # Leichte Schleierwolken über Richtungsprojektion
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Generated"], sep.inputs[0])
    den = nt.nodes.new("ShaderNodeMath")
    den.operation = "ADD"
    den.inputs[1].default_value = 0.06
    nt.links.new(sep.outputs[2], den.inputs[0])
    vec = nt.nodes.new("ShaderNodeVectorMath")
    vec.operation = "DIVIDE"
    nt.links.new(tc.outputs["Generated"], vec.inputs[0])
    cmb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(den.outputs[0], cmb.inputs[0])
    nt.links.new(den.outputs[0], cmb.inputs[1])
    nt.links.new(den.outputs[0], cmb.inputs[2])
    nt.links.new(cmb.outputs[0], vec.inputs[1])
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 0.9
    nz.inputs["Detail"].default_value = 8.0
    nz.inputs["Roughness"].default_value = 0.62
    nt.links.new(vec.outputs[0], nz.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.56 if mood == "hero" else 0.5
    ramp.color_ramp.elements[1].position = 0.74 if mood == "hero" else 0.78
    nt.links.new(nz.outputs["Fac"], ramp.inputs[0])
    hz = nt.nodes.new("ShaderNodeMapRange")
    hz.inputs["From Min"].default_value = 0.0
    hz.inputs["From Max"].default_value = 0.25
    nt.links.new(sep.outputs[2], hz.inputs["Value"])
    fac = nt.nodes.new("ShaderNodeMath")
    fac.operation = "MULTIPLY"
    nt.links.new(ramp.outputs[0], fac.inputs[0])
    nt.links.new(hz.outputs[0], fac.inputs[1])
    fac2 = nt.nodes.new("ShaderNodeMath")
    fac2.operation = "MULTIPLY"
    fac2.inputs[1].default_value = {"day": 0.75, "hero": 0.95}.get(mood, 0.35)
    nt.links.new(fac.outputs[0], fac2.inputs[0])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    nt.links.new(fac2.outputs[0], mix.inputs[0])
    nt.links.new(sky.outputs[0], mix.inputs[6])
    mix.inputs[7].default_value = (1.0, 1.0, 1.0, 1) if mood != "dusk" else (0.25, 0.2, 0.28, 1)
    cloud_bright = nt.nodes.new("ShaderNodeMix")
    cloud_bright.data_type = "RGBA"
    cloud_bright.blend_type = "MULTIPLY"
    cloud_bright.inputs[0].default_value = 1.0
    nt.links.new(sky.outputs[0], cloud_bright.inputs[6])
    cloud_bright.inputs[7].default_value = (3.0, 3.0, 3.0, 1)
    if mood != "dusk":
        nt.links.new(cloud_bright.outputs[2], mix.inputs[7])
    nt.links.new(mix.outputs[2], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = {"day": 0.32, "hero": 0.36}.get(mood, 2.2)
    nt.links.new(bg.outputs[0], out.inputs[0])

    sun = bpy.data.objects.get("Sonne")
    if sun is None:
        sun = bpy.data.objects.new("Sonne", bpy.data.lights.new("Sonne", "SUN"))
        sc.collection.objects.link(sun)
    az, elr = math.radians(SUN_AZ), math.radians(SUN_EL)
    d = Vector((math.sin(az) * math.cos(elr), math.cos(az) * math.cos(elr), math.sin(elr)))
    sun.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
    sun.data.energy = 0.0 if mood == "dusk" else 4.2
    sun.data.angle = math.radians(0.6)
    sun.data.color = (1.0, 0.96, 0.9)
    for node, day, dusk in EMISSIVE:
        node.inputs["Emission Strength"].default_value = dusk if mood == "dusk" else day
    for ob in DUSK_LIGHTS:
        ob.hide_render = mood != "dusk"
        ob.hide_viewport = mood != "dusk"


def look_at(ob, target):
    d = Vector(target) - ob.location
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def camera(name, loc, target, lens):
    cam = bpy.data.objects.get(name)
    if cam is None:
        cam = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        bpy.context.scene.collection.objects.link(cam)
    cam.location = loc
    look_at(cam, target)
    cam.data.lens = lens
    cam.data.sensor_width = 36
    cam.data.clip_start = 0.5
    cam.data.clip_end = 20000
    return cam


def P3(pu, pv, z):
    x, y = plan_to_world(pu, pv)
    return (x, y, z)


SHOT_DEFS = {
    # Name: (Kamera, Ziel, Brennweite, Breite, Höhe, Stimmung)
    # Blick von SW über Billa nach NNO: Bauteil 1+2 vorne beim Ort, B54 links, Bauteil 3+4 dahinter
    "uebersicht": (P3(190, -150, 120), P3(-125, 35, 0), 30, 2400, 1350, "day"),
    # Von Westen über das Feld (Gst. 107) auf die Schaufronten aller Bauteile an der B54
    "panorama": (P3(-122, -195, 62), P3(-125, 30, 0), 28, 2400, 1000, "day"),
    "b54": (P3(-12, -13, 8.0), P3(-56, 20, 4.2), 30, 2400, 1350, "day"),
    # Von Billa über die Zufahrt (Knoten B54) nach NO auf Bauteil 1 mit Logotafel
    "einfahrt-sued": (P3(55, -32, 30), P3(-95, 30, -2), 30, 2400, 1350, "day"),
    "eingang": (P3(-36, 10.2, 2.2), P3(-47.0, 18.0, 4.6), 24, 1800, 1350, "day"),
    "abend": (P3(-12, -13, 8.0), P3(-56, 20, 4.2), 30, 2400, 1350, "dusk"),
    # Hero: Ecke Bauteil 1 mit Logotafel von der Südeinfahrt, viel Himmel für die Headline
    "hero": (P3(-3, 0.5, 3.0), P3(-42, 20, 15.0), 22, 2560, 1440, "hero"),
    # Hof hinter Bauteil 1: Lagertore an der Rückseite
    "lager": (P3(-19.0, 49.5, 1.9), P3(-52.0, 45.2, 2.6), 24, 1800, 1350, "day"),
    # Dachterrasse hinten (Richtung Wald) von der Garagenzufahrt aus, leicht erhöht
    "terrasse": (P3(-36.0, 51.0, 9.5), P3(-60.0, 40.0, 5.6), 24, 2000, 1250, "day"),
    # Gründach mit PV und Sedum, flacher Blick über Bauteil 1+2
    "dach": (P3(-12.0, 4.0, 24.0), P3(-62.0, 32.0, 8.5), 28, 2000, 1250, "day"),
    # Lagekontrolle: senkrecht von oben, Norden oben (Gebäude östlich = rechts der B54)
    "draufsicht": ((24.0, -46.0, 620.0), (24.0, -40.0, 0.0), 50, 1600, 1600, "day"),
}


def setup_render():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("METAL", "OPTIX", "CUDA", "HIP"):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            devs = [d for d in prefs.devices if d.type == kind]
            if not devs:
                continue
            for d in prefs.devices:
                d.use = d.type == kind
            sc.cycles.device = "GPU"
            print("GPU:", kind, [d.name for d in devs])
            break
        except Exception as exc:  # noqa: BLE001
            print("GPU", kind, "nicht verfügbar:", exc)
    sc.cycles.samples = 24 if QUICK else 320
    sc.cycles.adaptive_threshold = 0.05 if QUICK else 0.015
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 8
    sc.cycles.transmission_bounces = 8
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.cycles.blur_glossy = 1.0
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX"
    for look in ("AgX - Medium High Contrast", "Medium High Contrast", "AgX - Base Contrast"):
        try:
            sc.view_settings.look = look
            break
        except TypeError:
            continue
    sc.view_settings.exposure = 0.0
    sc.render.image_settings.file_format = "JPEG"
    sc.render.image_settings.quality = 90


def render_shots():
    sc = bpy.context.scene
    IMG_OUT.mkdir(parents=True, exist_ok=True)
    for name, (loc, tgt, lens, w, h, mood) in SHOT_DEFS.items():
        cam = camera("Kamera_" + name, loc, tgt, lens)
        if SHOTS and name not in SHOTS:
            continue
        setup_world(mood)
        sc.view_settings.exposure = 1.1 if mood == "dusk" else -0.55
        sc.camera = cam
        sc.render.resolution_x = w // (3 if QUICK else 1)
        sc.render.resolution_y = h // (3 if QUICK else 1)
        out = IMG_OUT / f"modell-{name}{TAG}.jpg" if not QUICK else DATA / f"preview-{name}{TAG}.jpg"
        sc.render.filepath = str(out)
        print("Rendere", name, "→", out)
        bpy.ops.render.render(write_still=True)
    setup_world("day")


# --------------------------------------------------------------------------------------
# Web-Export (GLB)
# --------------------------------------------------------------------------------------


def export_glb(plan, site_coll, tree_objs):
    """Kompaktes Modell für die Website: Grundstück, Bauteile, nahe Umgebung mit Orthofoto."""
    sc = bpy.context.scene
    web = coll("Web_Export")
    # Gelände-Ausschnitt mit UVs auf das hochaufgelöste Orthofoto
    half, res = INNER - 20, 6.0
    g = np.arange(-half, half + 0.1, res)
    X, Y = np.meshgrid(g, g[::-1])
    Z = ground(X, Y)
    m_web_t = bpy.data.materials.new("web_terrain")
    m_web_t.use_nodes = True
    b = m_web_t.node_tree.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.95
    it = m_web_t.node_tree.nodes.new("ShaderNodeTexImage")
    src = bpy.data.images[(DATA / "ortho_inner.jpg").name]
    web_img = src.copy()
    web_img.name = "web_ortho"
    web_img.scale(2048, 2048)
    it.image = web_img
    m_web_t.node_tree.links.new(it.outputs["Color"], b.inputs["Base Color"])
    ob = grid_mesh("Web_Gelaende", X, Y, Z - 0.05, m_web_t, web)
    uvl = ob.data.uv_layers.new(name="UVMap")
    for loop in ob.data.loops:
        co = ob.data.vertices[loop.vertex_index].co
        uvl.data[loop.index].uv = ((co.x + INNER) / (2 * INNER), (co.y + INNER) / (2 * INNER))

    simple = {}

    def web_mat(m):
        if m is None or m.name in ("web_terrain",):
            return m
        if m.name not in simple:
            col = WEB_COLOR.get(m.name, (0.7, 0.7, 0.7, 1))
            wm = bpy.data.materials.new("web_" + m.name)
            wm.use_nodes = True
            bb = wm.node_tree.nodes["Principled BSDF"]
            bb.inputs["Base Color"].default_value = col
            bb.inputs["Roughness"].default_value = 0.6
            if m.name == "glass":
                bb.inputs["Base Color"].default_value = srgb("#22313a")
                bb.inputs["Roughness"].default_value = 0.05
                bb.inputs["Metallic"].default_value = 0.6
            if m.name == "logo":
                lt = wm.node_tree.nodes.new("ShaderNodeTexImage")
                lt.image = bpy.data.images[LOGO.name]
                wm.node_tree.links.new(lt.outputs["Color"], bb.inputs["Base Color"])
            simple[m.name] = wm
        return simple[m.name]

    keep = []
    for ob in list(site_coll.all_objects):
        if ob.type in ("MESH", "FONT"):
            keep.append(ob)
    bpy.ops.object.select_all(action="DESELECT")
    depsgraph = bpy.context.evaluated_depsgraph_get()
    web_trees = {}

    def web_tree(src_me):
        """Vereinfachter Baum (gemeinsames Mesh) statt der hochaufgelösten Krone."""
        key = src_me.name
        if key not in web_trees:
            zs = [v.co.z for v in src_me.vertices]
            xs = [abs(v.co.x) for v in src_me.vertices]
            h, r = max(zs), max(xs) * 0.82
            bm = bmesh.new()
            bmesh.ops.create_cone(bm, cap_ends=False, segments=6, radius1=r * 0.07, radius2=r * 0.04,
                                  depth=h * 0.5, matrix=Matrix.Translation((0, 0, h * 0.25)))
            for f in bm.faces:
                f.material_index = 0
            res = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=r,
                                             matrix=Matrix.Translation((0, 0, h - r)) @ Matrix.Diagonal((1, 1, 0.9, 1)))
            for f in {f for v in res["verts"] for f in v.link_faces}:
                f.material_index = 1
            me = bpy.data.meshes.new("web_tree_" + key)
            bm.to_mesh(me)
            bm.free()
            me.materials.append(web_mat(MATS["bark"]))
            me.materials.append(web_mat(MATS["leaf_obst" if "obst" in key else "leaf"]))
            me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
            web_trees[key] = me
        return web_trees[key]

    for ob in keep:
        if ob.name.startswith("Baum_"):
            me = web_tree(ob.data)
        else:
            ev = ob.evaluated_get(depsgraph)
            me = bpy.data.meshes.new_from_object(ev)
            for i, m in enumerate(me.materials):
                me.materials[i] = web_mat(m)
        cp = bpy.data.objects.new("Web_" + ob.name, me)
        web.objects.link(cp)
        cp.matrix_world = ob.matrix_world.copy()
        cp.select_set(True)
    bpy.data.objects["Web_Gelaende"].select_set(True)
    # Umgebungsgebäude im Ausschnitt
    ctx = bpy.data.objects["Umgebung_Gebaeude"]
    me = ctx.data.copy()
    bm = bmesh.new()
    bm.from_mesh(me)
    far = [f for f in bm.faces if max(abs(f.calc_center_median().x), abs(f.calc_center_median().y)) > half]
    bmesh.ops.delete(bm, geom=far, context="FACES")
    bm.to_mesh(me)
    bm.free()
    me.materials[0] = web_mat(MATS["plaster"])
    me.materials[1] = m_web_t
    uvl = me.uv_layers.get("UVMap") or me.uv_layers.new(name="UVMap")
    for loop in me.loops:
        co = me.vertices[loop.vertex_index].co
        uvl.data[loop.index].uv = ((co.x + INNER) / (2 * INNER), (co.y + INNER) / (2 * INNER))
    cp = bpy.data.objects.new("Web_Umgebung", me)
    web.objects.link(cp)
    cp.select_set(True)
    glb = GLB_OUT.with_name(f"teichwiese{TAG}.glb")
    glb.parent.mkdir(parents=True, exist_ok=True)
    kw = dict(filepath=str(glb), export_format="GLB", use_selection=True, export_apply=True,
              export_yup=True, export_draco_mesh_compression_enable=True,
              export_draco_mesh_compression_level=7, export_image_format="JPEG", export_jpeg_quality=80)
    try:
        bpy.ops.export_scene.gltf(**kw)
    except TypeError:
        kw.pop("export_jpeg_quality")
        bpy.ops.export_scene.gltf(**kw)
    print("GLB:", glb, glb.stat().st_size // 1024, "KB")
    for o in list(web.objects):
        bpy.data.objects.remove(o)
    bpy.data.collections.remove(web)


# --------------------------------------------------------------------------------------
# Hauptablauf
# --------------------------------------------------------------------------------------


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    build_materials()
    feats = osm_features()

    c_env = coll("Umgebung")
    c_site = coll("Teichwiese")
    c_src = coll("Vorlagen")
    build_terrain(c_env)
    ctx, footprints = build_context(c_env, feats)
    roads = build_roads(c_env, feats)

    tree_coll = coll("Baumvarianten", c_src)
    variants = [("obst", 1), ("obst", 2), ("laub", 3), ("laub", 4), ("strasse", 5), ("nadel", 6), ("nadel", 7),
                ("strasse", 8), ("strasse", 9)]
    tree_objs: dict[str, list] = {}
    for i, (kind, seed) in enumerate(variants):
        ob = make_tree(f"T{i}_{kind}_{seed}", kind, tree_coll, seed)
        tree_objs.setdefault(kind, []).append(ob)
    build_forest(c_env, feats, footprints, roads, tree_coll)

    plan = empty("Planrahmen_Entwurf3", None, (*PLAN_T, 0), PLAN_ROT, collection=c_site)
    ffb_a, ffb_b = LEVEL_A + 0.15, LEVEL_B + 0.15
    tufts = coll("Dachbewuchs", c_src)
    make_tufts(tufts)
    for i, (nm, loc, kw) in enumerate((("Bauteil_1", (-70.9, PV_FRONT, ffb_a), {}),
                                       ("Bauteil_2", (-70.9, PV_FRONT, ffb_a), {"mirror": True}),
                                       ("Bauteil_3", (-189.8, PV_FRONT, ffb_b), {"end0": True}),
                                       ("Bauteil_4", (-254.7, 15.7, ffb_b), {"end0": True, "rot": math.radians(3.03)}))):
        root, _ = build_bauteil(nm, plan, loc, collection=c_site, **kw)
        build_bauteil_gruen(nm, root, c_site, kw.get("end0", False), tufts, seed=200 + i)
    build_garagen(plan, c_site, tufts)
    build_site(plan, c_site, tree_objs)
    build_cars(plan, c_site, c_src)
    build_pylon("Stele_Sued", plan, c_site, -30.5, 1.0, math.pi / 2)  # nördlich neben der Zufahrt, quer zur B54
    bt1 = bpy.data.objects["Bauteil_1"]
    build_logo_panel("Logo_Sued", bt1, c_site, L_OG + 0.02, 8.1, 7.0, 6.0, 0.0)

    # Vorlagen nicht direkt rendern (nur als Instanzen)
    lc = bpy.context.view_layer.layer_collection.children["Vorlagen"]
    lc.exclude = True

    setup_render()
    setup_world("day")
    for name, (loc, tgt, lens, *_r) in SHOT_DEFS.items():
        camera("Kamera_" + name, loc, tgt, lens)
    sc.camera = bpy.data.objects["Kamera_uebersicht"]
    sc.frame_set(1)

    blend = DATA / "teichwiese.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    print("Gespeichert:", blend)
    if DO_GLB:
        lc.exclude = False
        export_glb(plan, c_site, tree_objs)
        lc.exclude = True
    if not NO_RENDER:
        render_shots()


main()
