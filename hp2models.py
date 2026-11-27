"""The models outside the cars and the tracks: the cars' dashboards (CARS\\<CAR>\\DASHGEOM.geo), the menus' (FRONTEND\\FRONTB:
the platform, the car cover, the track select's small tracks), the race's (GLOBAL\\INGAMEB: the spike belt, the smoke
bomb, the rocket, the roadblock barrel, the shaking bushes, the ticket book, the markers, the drivers and cops) and the
cut-scenes' people (GLOBAL\\CHARACTERSA).

Each of these files holds its solid lists at its top, as a track does, so hp2track.Track reads and rebuilds them (every
one rebuilds byte for byte) and an OBJ goes in as it does for a car or a track: hp2model.import_obj. The pictures come
from the packs the game has loaded when it draws them: the file's own, the cars', the global ones and the drivers'."""

import glob
import os

import hp2model as model
import hp2tex as tex
import hp2track as trk

FIXED = ("FRONTEND/FRONTB.BUN", "GLOBAL/INGAMEB.BUN", "GLOBAL/CHARACTERSA.geo")
PICTURES = ("CARS/TEXTURES.tex", "GLOBAL/GLOBALB.BUN", "GLOBAL/INGAMEB.BUN", "GLOBAL/DRIVTEX.tex", "FRONTEND/FRONTB.BUN",
            "GLOBAL/HUDTEX.tex", "GLOBAL/DYNTEX.tex",
            # the shaking bushes draw the loaded track's own leaves (BRANCH01, ST_LEAVES6T): shown here with track 11's
            "TRACKS/TEX11LOCATION.tex")
WHAT = {"FRONTEND/FRONTB.BUN": "the menus: platform, car cover, the track select's tracks",
        "GLOBAL/INGAMEB.BUN": "the race: spikes, smoke bomb, rocket, barrel, bushes, ticket book, markers, drivers",
        "GLOBAL/CHARACTERSA.geo": "the cut-scenes' drivers and cops"}


def files(data):
    """[(relative path, what it is)] of the files with models this tab shows."""
    out = []
    for p in sorted(glob.glob(os.path.join(data, "CARS", "*", "DASHGEOM.geo"))):
        car = os.path.basename(os.path.dirname(p))
        out.append((os.path.relpath(p, data).replace("\\", "/"), "the %s's dashboard in the cockpit view" % car))
    for rel in FIXED:
        if os.path.isfile(os.path.join(data, rel)):
            out.append((rel, WHAT[rel]))
    return out


def load(data, rel):
    return trk.Track(open(os.path.join(data, rel), "rb").read())


def pictures(data, rel):
    """(names {hash: name}, {hash: (Texture, buf)}): the file's own packs first, then the ones the game has loaded."""
    names, packs = {}, {}
    for r in (rel,) + tuple(p for p in PICTURES if p != rel):
        p = os.path.join(data, r)
        if not os.path.isfile(p):
            continue
        buf = open(p, "rb").read()
        for t in tex.read_textures(buf):
            names.setdefault(t.hash, t.name)
            packs.setdefault(t.hash, (t, buf))
    return names, packs


def rgba_lookup(packs):
    cache = {}

    def rgba_of(h):
        if h not in cache:
            img = None
            hit = packs.get(h)
            if hit is not None:
                t, buf = hit
                if t.parent and t.parent in packs:
                    t, buf = packs[t.parent]
                img = tex.decode(t, buf)
            cache[h] = img
        return cache[h]

    def bits_of(h):
        hit = packs.get(h)
        return hit[1][hit[0].rec_at + 0x76] if hit is not None else None
    return rgba_of, bits_of


def stem(rel):
    """A name for the export's folder: BARCHETTA_DASHGEOM, FRONTB, INGAMEB, CHARACTERSA."""
    parts = rel.replace("\\", "/").split("/")
    base = os.path.splitext(parts[-1])[0]
    return "%s_%s" % (parts[1], base) if parts[0].upper() == "CARS" else base


def export(data, rel, out_root, only=None, bare=False, log=print):
    """OUT/<stem>/<stem>.obj (the models, or those named in only), .mtl and textures/*.png."""
    t = load(data, rel)
    names, packs = pictures(data, rel)
    by_name = {n.upper(): h for h, n in names.items()}
    used = {}

    def picture(label):
        h = by_name.get(label.upper())
        if h is None:
            return None
        used[h] = packs[h]
        return names[h]
    out = os.path.join(out_root, stem(rel))
    os.makedirs(out, exist_ok=True)
    obj = os.path.join(out, stem(rel) + ".obj")
    model.export_obj(t, names, obj, only=only, picture=None if bare else picture, bare=bare)
    n = 0
    if not bare:
        d = os.path.join(out, "textures")
        os.makedirs(d, exist_ok=True)
        for h, (tt, buf) in used.items():
            if tt.parent and tt.parent in packs:
                tt, buf = packs[tt.parent]
            rgba = tex.decode(tt, buf)
            if rgba is not None:
                tex.write_png(os.path.join(d, names[h] + ".png"), rgba)
                n += 1
    log("%s: %d models, %d pictures -> %s" % (rel, len(only) if only else len(t.solids()), n, obj))
    return obj


def rebuild(data, rel, obj, log=print):
    """(path, old bytes, new bytes, [names changed]): the models the OBJ names rebuilt. Nothing written."""
    path = os.path.join(data, rel)
    buf = open(path, "rb").read()
    t = trk.Track(buf)
    names, _ = pictures(data, rel)
    by_name = {n.upper(): h for h, n in names.items()}
    before = {s.name_hash: list(s.packets) for s in t.solids()}
    for line in model.import_obj(t, obj, by_name):
        if "no solid of that name" not in line:
            log(line)
    changed = [s.full_name for s in t.solids() if list(s.packets) != before[s.name_hash]]
    out = t.build()
    trk.Track(out)                                   # it has to read back
    log("%s: %d models changed, %d -> %d bytes" % (rel, len(changed), len(buf), len(out)))
    return path, buf, out, changed
