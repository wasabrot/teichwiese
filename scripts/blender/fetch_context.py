#!/usr/bin/env python3
"""Lädt Umgebungsdaten für das 3D-Modell der Teichwiese nach build/3d/.

Quellen (offen lizenziert, Namensnennung in Renderings/Website angeben):
- OpenStreetMap via Overpass API (ODbL): Gebäude, Straßen, Flächen, Gewässer
- Mapzen/AWS Terrain Tiles "terrarium" (u. a. Land Österreich DGM): Gelände
- basemap.at Orthofoto (CC BY 4.0): Bodentextur

Alle Daten werden auf ein lokales Metersystem (x = Ost, y = Nord) um ORIGIN
umgerechnet. Aufruf: python3 scripts/blender/fetch_context.py
"""
from __future__ import annotations

import io
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "3d"
CACHE = OUT / "tiles"

# Mitte der Gewerbefläche nördlich von BILLA, westlich der B54 (OSM way 854510837)
ORIGIN = (47.17882, 15.80987)
EXTENT = 900.0  # Halbe Kantenlänge des Umgebungsquadrats in Metern
INNER = 320.0  # Halbe Kantenlänge des hochaufgelösten Orthofotos
FAR = 7000.0  # Fernumfeld (Hügelland, Kulm) für Übersichtsansichten
UA = "teichwiese-3d-model/1.0 (+https://github.com/wasabrot/teichwiese)"

M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0 * math.cos(math.radians(ORIGIN[0]))


def to_latlon(x, y):
    return ORIGIN[0] + y / M_PER_DEG_LAT, ORIGIN[1] + x / M_PER_DEG_LON


def merc_px(lat, lon, z):
    n = 256 * 2**z
    px = (lon + 180.0) / 360.0 * n
    lr = np.radians(lat)
    py = (1.0 - np.log(np.tan(lr) + 1.0 / np.cos(lr)) / math.pi) / 2.0 * n
    return px, py


def get(url: str, dest: Path) -> bytes:
    if dest.exists() and dest.stat().st_size > 0:
        return dest.read_bytes()
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return data
        except Exception as exc:  # noqa: BLE001
            if attempt == 3:
                raise RuntimeError(f"{url}: {exc}") from exc
            time.sleep(2 * (attempt + 1))
    raise AssertionError


def mosaic(z: int, half: float, res: float, url_tpl: str, name: str, mode: str) -> np.ndarray:
    """Resampelt Web-Mercator-Kacheln auf ein lokales Raster (Zeile 0 = Norden)."""
    n = int(round(2 * half / res))
    xs = -half + (np.arange(n) + 0.5) * res
    ys = half - (np.arange(n) + 0.5) * res
    gx, gy = np.meshgrid(xs, ys)
    lat, lon = to_latlon(gx, gy)
    px, py = merc_px(lat, lon, z)
    tx0, tx1 = int(px.min() // 256), int(px.max() // 256)
    ty0, ty1 = int(py.min() // 256), int(py.max() // 256)
    tiles = [(tx, ty) for tx in range(tx0, tx1 + 1) for ty in range(ty0, ty1 + 1)]
    print(f"{name}: z{z}, {len(tiles)} Kacheln, Raster {n}x{n} @ {res} m")

    def load(t):
        tx, ty = t
        data = get(url_tpl.format(z=z, x=tx, y=ty), CACHE / name / f"{z}_{tx}_{ty}")
        return t, np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))

    big = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 3), np.uint8)
    with ThreadPoolExecutor(8) as ex:
        for (tx, ty), arr in ex.map(load, tiles):
            big[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = arr

    fx = px - tx0 * 256 - 0.5
    fy = py - ty0 * 256 - 0.5
    x0 = np.clip(np.floor(fx).astype(int), 0, big.shape[1] - 2)
    y0 = np.clip(np.floor(fy).astype(int), 0, big.shape[0] - 2)
    wx = (fx - x0)[..., None]
    wy = (fy - y0)[..., None]
    src = big.astype(np.float64)
    if mode == "terrarium":
        src = (src[..., 0] * 256 + src[..., 1] + src[..., 2] / 256 - 32768)[..., None]
    return (src[y0, x0] * (1 - wx) * (1 - wy) + src[y0, x0 + 1] * wx * (1 - wy)
            + src[y0 + 1, x0] * (1 - wx) * wy + src[y0 + 1, x0 + 1] * wx * wy)


def fetch_osm() -> None:
    dest = OUT / "osm.json"
    if dest.exists():
        print("OSM: vorhanden")
        return
    lat, lon = ORIGIN
    r = EXTENT * 1.45
    sel = ["way[building]", "relation[building]", "way[highway]", "way[landuse]", "way[natural]",
           "node[natural=tree]", "way[waterway]", "way[amenity=parking]", "way[leisure]",
           "way[barrier=hedge]"]
    body = "".join(s.replace("[", f"(around:{r},{lat},{lon})[", 1) + ";" for s in sel)
    q = f"[out:json][timeout:120];({body});out geom tags;"
    data = urllib.parse.urlencode({"data": q}).encode()
    req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=data,
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = json.load(resp)
    feats = []
    for e in raw["elements"]:
        if e["type"] == "node":
            pts = [(e["lon"], e["lat"])]
        elif "geometry" in e:
            pts = [(p["lon"], p["lat"]) for p in e["geometry"] if p]
        elif e["type"] == "relation":
            outer = [m for m in e.get("members", []) if m.get("role") == "outer" and "geometry" in m]
            if not outer:
                continue
            pts = [(p["lon"], p["lat"]) for p in outer[0]["geometry"]]
        else:
            continue
        xy = [((lo - ORIGIN[1]) * M_PER_DEG_LON, (la - ORIGIN[0]) * M_PER_DEG_LAT) for lo, la in pts]
        feats.append({"id": f"{e['type']}/{e['id']}", "tags": e.get("tags", {}),
                      "xy": [(round(x, 2), round(y, 2)) for x, y in xy]})
    dest.write_text(json.dumps({"origin": ORIGIN, "features": feats}))
    print(f"OSM: {len(feats)} Objekte")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    fetch_osm()

    dem = mosaic(15, EXTENT, 4.0,
                 "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
                 "dem", "terrarium")[..., 0]
    np.save(OUT / "dem.npy", dem.astype(np.float32))
    print(f"DEM: {dem.min():.1f} – {dem.max():.1f} m ü. A.")

    ortho = "https://mapsneu.wien.gv.at/basemap/bmaporthofoto30cm/normal/google3857/{z}/{y}/{x}.jpeg"
    outer = mosaic(17, EXTENT, 1.0, ortho, "ortho17", "rgb")
    Image.fromarray(np.clip(outer, 0, 255).astype(np.uint8)).save(OUT / "ortho_outer.jpg", quality=90)
    inner = mosaic(19, INNER, 0.25, ortho, "ortho19", "rgb")
    Image.fromarray(np.clip(inner, 0, 255).astype(np.uint8)).save(OUT / "ortho_inner.jpg", quality=92)

    far_dem = mosaic(12, FAR, 25.0,
                     "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
                     "dem12", "terrarium")[..., 0]
    np.save(OUT / "dem_far.npy", far_dem.astype(np.float32))
    far = mosaic(14, FAR, 5.0, ortho, "ortho14", "rgb")
    Image.fromarray(np.clip(far, 0, 255).astype(np.uint8)).save(OUT / "ortho_far.jpg", quality=88)

    (OUT / "meta.json").write_text(json.dumps({"origin": ORIGIN, "extent": EXTENT, "inner": INNER,
                                               "far": FAR, "dem_res": 4.0, "far_res": 25.0}))
    print("fertig:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
