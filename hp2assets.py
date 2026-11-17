#!/usr/bin/env python3
"""The port's asset tool: car models and textures out of an installed game and back into it.

The game is the folder speed.exe installed (or its data\\ folder). Every file is changed in place; the first change of a file
keeps the disc's version beside it as <file>.orig, and `restore` puts that back.

    python hp2assets.py cars GAME                          the cars and their parts
    python hp2assets.py export-car GAME CAR OUT            OUT/CAR/CAR.obj (parts), CAR_whole.obj (put together), .mtl,
                                                           textures/*.png; --bare, --skins 1,3|all, --lod A..D
    python hp2assets.py import-car GAME CAR FILE.obj       rebuild the parts the OBJ has (objects named as in the export)
    python hp2assets.py export-textures GAME FILE OUT      every texture of a file as PNG (FILE e.g. CARS/TEXTURES.tex)
    python hp2assets.py import-textures GAME FILE PNG...   PNGs (or folders of them) back by name, same size
    python hp2assets.py restore GAME FILE|CAR              the disc's version back
    python hp2assets.py verify GAME                        decode and re-encode every car: the tool against the disc

Models: any topology, see hp2model.py. Textures keep their size and format (4 or 8 bits with a palette, or 32): a picture with
more colours than the palette gets a new one. Needs Python 3.10+, numpy and Pillow.
"""

import argparse
import glob
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402

import hp2car as carinfo  # noqa: E402
import hp2core as core  # noqa: E402
import hp2model as model  # noqa: E402
import hp2tex as tex  # noqa: E402

CAR_TEXTURES = "CARS/TEXTURES.tex"
CAR_TEXTURE_FILES = (CAR_TEXTURES, "GLOBAL/GLOBALB.BUN")


def data_dir(game):
    for d in (os.path.join(game, "data"), game):
        if os.path.isfile(os.path.join(d, "index.txt")) and os.path.isdir(os.path.join(d, "CARS")):
            return d
    raise SystemExit("%s: not an installed game (no data\\index.txt with CARS\\ beside it)" % game)


def resolve(data, rel):
    p = rel if os.path.isabs(rel) else os.path.join(data, rel)
    if not os.path.isfile(p):
        raise SystemExit("%s: no such file" % p)
    return p


def car_file(data, car):
    p = os.path.join(data, "CARS", car.upper(), "GEOMETRY.geo")
    if not os.path.isfile(p):
        raise SystemExit("no car %s (looked for %s)" % (car, p))
    return p


def backup(path):
    orig = path + ".orig"
    if not os.path.exists(orig):
        shutil.copy2(path, orig)
    return orig


def write_atomic(path, data):
    tmp = path + ".new"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def car_texture_packs(data):
    """[(file, bytes, [Texture])] of the packs a car draws from: its own, and GLOBALB's shared ones (WINDOW, TIRE, ...)."""
    out = []
    for rel in CAR_TEXTURE_FILES:
        p = os.path.join(data, rel)
        if os.path.isfile(p):
            buf = open(p, "rb").read()
            out.append((rel, buf, tex.read_textures(buf)))
    return out


def texture_names(data):
    """hash -> name, and NAME -> hash, of the car textures; and the packs."""
    packs = car_texture_packs(data)
    by_hash, by_name = {}, {}
    for _, _, ts in packs:
        for t in ts:
            by_hash.setdefault(t.hash, t.name)
            by_name.setdefault(t.name.upper(), t.hash)
    cars = [os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(data, "CARS", "*", "GEOMETRY.geo"))]
    for h, n in slot_names(cars).items():
        if h not in by_hash or (n.startswith(by_hash[h]) and len(n) > len(by_hash[h])):
            by_hash[h] = n          # also the whole name of a pack entry cut at 23 characters
    return by_hash, by_name, packs


# The geometry's texture tables also name slots that are in no pack: the game fills them at run time with the car's own
# picture (TIRE, WINDOW_FRONT, CARBOTTOM, <CAR>_HEADLIGHT_LEFT, ...). Their names are only hashes on the disc; these words
# give 132 of the 140 the cars use. An import resolves a name by its hash either way.
_SLOT_WORDS = ("WINDOW", "HEADLIGHT", "BRAKELIGHT", "LEFT", "RIGHT", "FRONT", "REAR", "TIRE", "TIREBACK", "LICENSE", "PLATE",
               "CARBOTTOM", "WIPER01", "SKIN1", "SKIN1B", "SCUFFS", "SHADOW", "DAMAGE")


def _slot_pictures(label, car):
    """Names to try for the picture of a material: the label, then what the game fills that slot with."""
    base = label
    for end in ("_LEFT", "_RIGHT", "_FRONT", "_REAR"):
        if base.endswith(end):
            base = base[:-len(end)]
    if base.startswith("WINDOW"):
        base = "WINDOW"
    return [label, base, car + "_" + base, car + "HP_" + base, car + "_" + label]


def slot_names(cars):
    words = _SLOT_WORDS
    out = {}
    names = set(words)
    for a in words:
        for b in words:
            names.add(a + "_" + b)
            for c in words:
                names.add(a + "_" + b + "_" + c)
    for n in names:
        out.setdefault(core.bhash(n), n)
    for car in cars:
        for a in words:
            for b in words:
                n = "%s_%s_%s" % (car, a, b)
                out.setdefault(core.bhash(n), n)
    return out


# ---- commands ----------------------------------------------------------------------------------------------------------------

def cmd_cars(a):
    data = data_dir(a.game)
    for p in sorted(glob.glob(os.path.join(data, "CARS", "*", "GEOMETRY.geo"))):
        car = os.path.basename(os.path.dirname(p))
        geo = core.read_geometry(open(p, "rb").read())
        parts = ", ".join("%s %d" % (s.full_name[len(car) + 1:] if s.full_name.startswith(car + "_") else s.full_name,
                                     s.counts()[3]) for s in geo.solids())
        mark = " (changed)" if os.path.exists(p + ".orig") else ""
        print("%-12s%s %s" % (car, mark, parts))


def car_type_of(data, car):
    """The car's CarTypeInfo record from GLOBALB, or None."""
    p = os.path.join(data, "GLOBAL", "GLOBALB.BUN")
    if not os.path.isfile(p):
        return None
    return carinfo.car_type(carinfo.car_type_records(open(p, "rb").read()), car)


def car_skins(data, car):
    names, _, _ = texture_names(data)
    return carinfo.skins(car, names.values())


def export_car(data, car, out_root, only=None, bare=False, skins=None, lod="A", log=print):
    """OUT/<CAR>/: <CAR>.obj (every part, the file to edit and import back), <CAR>_whole.obj (the car put together as it
    stands: body at `lod`, mirrors, plates, four tyres and brakes), their .mtl, and textures/*.png.
    bare: no pictures (UV, normals and material names stay). skins: None for the car's default skin, a list of numbers,
    or "all"; more than one skin gives a folder skin<n>/ for each, with the pictures shared in textures/."""
    path = car_file(data, car)
    car = car.upper()
    geo = core.read_geometry(open(path, "rb").read())
    names, _, packs = texture_names(data)
    ctype = car_type_of(data, car)
    out = os.path.join(out_root, car)
    os.makedirs(out, exist_ok=True)
    by_hash = {}
    for _, buf, ts in packs:
        for t in ts:
            by_hash.setdefault(t.hash, (t, buf))
    have = carinfo.skins(car, names.values())
    if skins == "all":
        skins = have or [1]
    elif not skins:
        d = ctype.default_skin if ctype else 1
        skins = [d if d in have else (have[0] if have else 1)]
    skins = [k for k in skins if k in have] or [1]
    if bare:
        skins = [skins[0]]

    def pixels(t, buf):
        """A texture's picture; one that borrows its pixels shows its parent's."""
        if t.parent and t.parent in by_hash:
            t, buf = by_hash[t.parent]
        return tex.decode(t, buf)

    shown = {}

    def picture_for(skin):
        def picture(label):
            """The pack's picture for a material: its own, or for a slot the one the game puts there."""
            label = carinfo.skin_label(label, car, skin)
            for cand in _slot_pictures(label, car):
                hit = by_hash.get(core.bhash(cand))
                if hit is not None:
                    shown[hit[0].hash] = hit
                    return names.get(hit[0].hash, hit[0].name)
            return None
        return picture

    placed = carinfo.assemble(geo, car, ctype, lod)
    if ctype is None:
        log("note: %s has no car type record in GLOBALB; the whole car has no wheels" % car)
    many = len(skins) > 1
    for skin in skins:
        d = os.path.join(out, "skin%d" % skin) if many else out
        os.makedirs(d, exist_ok=True)
        tdir = "../textures" if many else "textures"
        pic = None if bare else picture_for(skin)
        _, mats = model.export_obj(geo, names, os.path.join(d, car + ".obj"), only, texture_dir=tdir, picture=pic,
                                   bare=bare)
        _, mats2 = model.export_obj(geo, names, os.path.join(d, car + "_whole.obj"), texture_dir=tdir, placed=placed,
                                    mtl_path=os.path.join(d, car + ".mtl"), write_mtl=False)
        mats.update(mats2)
        model.write_mtl_file(os.path.join(d, car + ".mtl"), mats, pic, tdir)
    n = 0
    if not bare:
        os.makedirs(os.path.join(out, "textures"), exist_ok=True)
        # the textures the parts draw with, and the car's others (skins, the damaged lights and windows)
        for h, (t, buf) in by_hash.items():
            if h in shown or t.name.upper().startswith(car + "_") or t.name.upper().startswith(car + "HP_"):
                rgba = pixels(t, buf)
                if rgba is not None:
                    tex.write_png(os.path.join(out, "textures", names.get(t.hash, t.name) + ".png"), rgba)
                    n += 1
    nparts = len([s for s in geo.solids() if not only or s.name in only or s.full_name in only])
    log("%s: %d parts, whole car of %d pieces, %s -> %s" % (
        car, nparts, len(placed), "no pictures" if bare else "%d textures, skin %s" % (n, ", ".join(map(str, skins))),
        out))
    return out


def cmd_export_car(a):
    data = data_dir(a.game)
    only = set(a.solids.split(",")) if a.solids else None
    skins = None
    if a.skins:
        skins = "all" if a.skins == "all" else [int(x) for x in a.skins.split(",")]
    export_car(data, a.car, a.out, only, bare=a.bare, skins=skins, lod=a.lod.upper())


def rebuild_car(data, car, obj, only=None):
    """The car rebuilt from an OBJ, nothing written: (path, the file's bytes, the new bytes, the new geometry as the
    game will read it). The report goes to print."""
    path = car_file(data, car)
    buf = open(path, "rb").read()
    geo = core.read_geometry(buf)
    _, by_name, _ = texture_names(data)
    for line in model.import_obj(geo, obj, by_name, only):
        print(line)
    out = core.write_geometry(geo)
    after = core.read_geometry(out)                      # it has to read back; this is what the game decodes
    print("GEOMETRY: %d -> %d bytes" % (len(buf), len(out)))
    if len(out) > len(buf) + 512 * 1024:
        print("note: the car is %.1f MB larger; a race keeps about 5 MB of the game's memory free for everything"
              % ((len(out) - len(buf)) / 1048576))
    return path, buf, out, after


def write_car(path, out):
    backup(path)
    write_atomic(path, out)
    print("written %s (the disc's is %s.orig)" % (path, path))


def cmd_import_car(a):
    data = data_dir(a.game)
    only = set(a.solids.split(",")) if a.solids else None
    path, _, out, _ = rebuild_car(data, a.car, a.obj, only)
    if a.dry_run:
        print("dry run: nothing written")
        return
    write_car(path, out)


def car_pictures(data, car, override=None):
    """(names {hash: label}, rgba_of(label)): the picture the game shows for a material label of the car, with the slots
    it fills at run time and the textures that borrow another's pixels resolved; None for none. override {file: bytes}
    shows a pack as it would be after a change."""
    names, _, packs = texture_names(data)
    if override:
        packs = [(rel, override[rel], tex.read_textures(override[rel])) if rel in override else (rel, b, ts)
                 for rel, b, ts in packs]
    car = car.upper()
    by_hash = {}
    for _, buf, ts in packs:
        for t in ts:
            by_hash.setdefault(t.hash, (t, buf))
    cache = {}

    def rgba_of(label):
        if label in cache:
            return cache[label]
        img = None
        for cand in _slot_pictures(label, car):
            hit = by_hash.get(core.bhash(cand))
            if hit is not None:
                t, buf = hit
                if t.parent and t.parent in by_hash:
                    t, buf = by_hash[t.parent]
                img = tex.decode(t, buf)
                break
        cache[label] = img
        return img
    return names, rgba_of


def cmd_export_textures(a):
    data = data_dir(a.game)
    path = resolve(data, a.file)
    buf = open(path, "rb").read()
    os.makedirs(a.out, exist_ok=True)
    n = 0
    seen = {}
    for t in tex.read_textures(buf):
        rgba = tex.decode(t, buf)
        if rgba is None:
            continue
        name = t.name
        if name in seen and not np.array_equal(seen[name], rgba):
            name = "%s@%08x" % (t.name, t.hash)
        seen.setdefault(t.name, rgba)
        tex.write_png(os.path.join(a.out, name + ".png"), rgba)
        n += 1
    print("%d textures -> %s" % (n, a.out))


def cmd_import_textures(a):
    data = data_dir(a.game)
    path = resolve(data, a.file)
    buf = bytearray(open(path, "rb").read())
    textures = tex.read_textures(buf)
    pngs = []
    for p in a.png:
        if os.path.isdir(p):
            pngs += sorted(glob.glob(os.path.join(p, "**", "*.png"), recursive=True))
        else:
            pngs.append(p)
    changed = 0
    for p in pngs:
        stem = os.path.splitext(os.path.basename(p))[0]
        name, _, h = stem.partition("@")
        hits = [t for t in textures if (t.name.upper() == name.upper() or t.hash == core.bhash(name))
                and (not h or "%08x" % t.hash == h.lower())]
        if not hits:
            print("%s: no texture %s in %s" % (os.path.basename(p), stem, a.file))
            continue
        rgba = tex.read_png(p)
        for t in hits:
            if t.parent:
                continue
            try:
                how = tex.encode_into(buf, t, rgba)
            except ValueError as e:
                print("%s: %s" % (os.path.basename(p), e))
                continue
            if how != "unchanged":
                changed += 1
                print("%s: %s" % (t.name, how))
    if not changed:
        print("nothing changed")
        return
    if a.dry_run:
        print("dry run: nothing written")
        return
    backup(path)
    write_atomic(path, bytes(buf))
    print("%d textures written into %s" % (changed, path))


def replace_file(path, data):
    """A game file changed: the disc's kept as <file>.orig the first time, the new one written whole and renamed over
    (the install's files may be hard links: writing into one would change the other too)."""
    backup(path)
    write_atomic(path, data)


def restore_file(path):
    orig = path + ".orig"
    if not os.path.exists(orig):
        print("%s: never changed" % path)
        return False
    os.replace(orig, path)
    print("%s: the disc's version is back" % path)
    return True


# ---- tracks ------------------------------------------------------------------------------------------------------------

def track_pictures(data, track):
    """(names {hash: name}, {hash: (Texture, buf)}) of the packs a track draws from."""
    import hp2track as trk
    names, packs = {}, {}
    for rel in trk.texture_files(data, track):
        buf = open(os.path.join(data, rel), "rb").read()
        for t in tex.read_textures(buf):
            names.setdefault(t.hash, t.name)
            packs.setdefault(t.hash, (t, buf))
    return names, packs


def export_track(data, track, out_root, bare=False, log=print):
    import hp2track as trk
    names, packs = track_pictures(data, track)
    by_name = {n.upper(): h for h, n in names.items()}
    used = {}

    def picture(label):
        h = by_name.get(label.upper())
        if h is None:
            return None
        used[h] = packs[h]
        return names[h]
    t, mats = trk.export_track(data, track, out_root, names, picture, bare, log)
    if not bare:
        d = os.path.join(out_root, track, "textures")
        os.makedirs(d, exist_ok=True)
        n = 0
        for h, (tt, buf) in used.items():
            if tt.parent and tt.parent in packs:
                tt, buf = packs[tt.parent]
            rgba = tex.decode(tt, buf)
            if rgba is not None:
                tex.write_png(os.path.join(d, names[h] + ".png"), rgba)
                n += 1
        log("%d textures" % n)


def rebuild_track(data, track, obj, log=print):
    """(path, old bytes, new bytes): the solids the OBJ names rebuilt, the culling made to follow. Nothing written."""
    import re
    import hp2track as trk
    path = dict(trk.track_files(data))[track]
    buf = open(path, "rb").read()
    t = trk.Track(buf)
    names, _ = track_pictures(data, track)
    by_name = {n.upper(): h for h, n in names.items()}
    mesh_objects = [l.split(None, 1)[1].strip() for l in open(obj, encoding="utf-8", errors="replace")
                    if l.startswith("o ")]
    if mesh_objects and sum(bool(re.match(r"S-?\d+_I\d+_", o)) for o in mesh_objects) > len(mesh_objects) / 2:
        raise SystemExit("%s is the whole track put together (export only); import %s.obj, the parts" % (obj, track))
    before = {s.name_hash: list(s.packets) for s in t.solids()}
    for line in model.import_obj(t, obj, by_name):
        if "no solid of that name" not in line:
            log(line)
    changed = {s.name_hash for s in t.solids() if list(s.packets) != before[s.name_hash]}
    for line in trk.update_culling(t, changed):
        log(line)
    out = t.build()
    trk.Track(out)                               # it has to read back
    log("%s: %d solids changed, %d -> %d bytes" % (track, len(changed), len(buf), len(out)))
    if changed:
        log("note: the collision, the AI's routes and the cameras stay as they were: cars drive on the old ground")
    return path, buf, out


def cmd_restore(a):
    data = data_dir(a.game)
    p = a.what
    if not os.path.isfile(p) and not os.path.isfile(os.path.join(data, p)):
        p = car_file(data, p)
    elif not os.path.isabs(p):
        p = os.path.join(data, p)
    orig = p + ".orig"
    if not os.path.exists(orig):
        print("%s: never changed" % p)
        return
    os.replace(orig, p)
    print("%s: the disc's version is back" % p)


def cmd_verify(a):
    """Every car: the file written back as read, every packet encoded again, and each car through OBJ and back."""
    import tempfile
    data = data_dir(a.game)
    names, by_name, _ = texture_names(data)
    bad = 0
    for p in sorted(glob.glob(os.path.join(data, "CARS", "*", "GEOMETRY.geo"))):
        car = os.path.basename(os.path.dirname(p))
        src = p + ".orig" if os.path.exists(p + ".orig") else p
        buf = open(src, "rb").read()
        geo = core.read_geometry(buf)
        same = core.write_geometry(geo) == buf
        pk_bad = 0
        for s in geo.solids():
            for st, pk in zip(s.strips, s.packets):
                if core.encode_strip(st, st.raw_adc) != pk:
                    pk_bad += 1
                st2 = core.decode_strip(core.encode_strip(st))
                if st2.dead != st.dead:
                    pk_bad += 1
        # through OBJ: the same triangles, with the same vertices, come back
        with tempfile.TemporaryDirectory() as tmp:
            obj = os.path.join(tmp, car + ".obj")
            model.export_obj(geo, names, obj)
            before = {s.full_name: _tri_set(s) for s in geo.solids()}
            geo2 = core.read_geometry(buf)
            model.import_obj(geo2, obj, by_name)
            out = core.write_geometry(geo2)
            geo3 = core.read_geometry(out)
            tri_bad = sum(1 for s in geo3.solids() if _tri_set(s) != before[s.full_name])
        ok = same and not pk_bad and not tri_bad
        bad += not ok
        print("%-12s %s  file %s, packets %s, OBJ round trip %s (%d -> %d bytes)"
              % (car, "ok  " if ok else "FAIL", "same" if same else "DIFFERS", pk_bad or "same",
                 "same" if not tri_bad else "%d parts differ" % tri_bad, len(buf), len(out)))
    print("all cars ok" if not bad else "%d cars FAIL" % bad)
    return 1 if bad else 0


def _tri_set(s):
    """A solid's triangles as sets of vertices with their material, winding kept (rotated to start at the least)."""
    out = []
    for e, st in zip(s.entries, s.strips):
        h = s.textures[e.texture] if 0 <= e.texture < len(s.textures) else None
        mat = (h, e.flags, st.light_material)
        for t in st.triangles():
            ks = [st.verts[i].key() for i in t]
            if len(set(ks)) < 3:
                continue                    # a degenerate triangle draws nothing, and the import drops it
            r = ks.index(min(ks))
            out.append((mat, tuple(ks[r:] + ks[:r])))
    return sorted(out, key=repr)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("cars")
    p.add_argument("game")
    p.set_defaults(fn=cmd_cars)
    p = sub.add_parser("export-car")
    p.add_argument("game")
    p.add_argument("car")
    p.add_argument("out")
    p.add_argument("--solids", help="only these parts, comma separated (MCLAREN_A,MCLAREN_B)")
    p.add_argument("--bare", action="store_true", help="no pictures: UV, normals and material names only")
    p.add_argument("--skins", help="skin numbers, comma separated, or all (default: the car's default skin)")
    p.add_argument("--lod", default="A", help="level of detail of the whole car's body, A to D")
    p.set_defaults(fn=cmd_export_car)
    p = sub.add_parser("import-car")
    p.add_argument("game")
    p.add_argument("car")
    p.add_argument("obj")
    p.add_argument("--solids", help="only these parts of the OBJ")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_import_car)
    p = sub.add_parser("export-textures")
    p.add_argument("game")
    p.add_argument("file")
    p.add_argument("out")
    p.set_defaults(fn=cmd_export_textures)
    p = sub.add_parser("import-textures")
    p.add_argument("game")
    p.add_argument("file")
    p.add_argument("png", nargs="+")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_import_textures)
    p = sub.add_parser("restore")
    p.add_argument("game")
    p.add_argument("what")
    p.set_defaults(fn=cmd_restore)
    p = sub.add_parser("verify")
    p.add_argument("game")
    p.set_defaults(fn=cmd_verify)
    a = ap.parse_args()
    sys.exit(a.fn(a) or 0)


if __name__ == "__main__":
    main()
