"""A donor game's car made into an HP2 car, in the place of one of HP2's (the game has exactly 64 car types and
no free one). Experimental.

What is made:
- the target's bodies A..D from the donor's stock parts at the same level of detail (or the nearest it has);
- its mirrors from the donor's, its tyres from the donor's wheel (turned into a right wheel, as HP2's are);
- its skin pictures SKIN1..9 (and the small SKINnB): an atlas of the donor's own pictures (badges, grilles, lamps) and
  swatches of colour; the paint is a swatch, so a skin is a colour (HP2 has no paint, its skins are pictures);
- the target's lamp pictures (HEADLIGHT, _ON, _DAMAGE; BRAKELIGHT, _ON, _DAMAGE) from the donor's, so the HP2 lamp slots
  light up and break as they did;
- the windows on HP2's six window slots by where they face, the underside on CARBOTTOM;
- the position markers (light flares, exhausts, the plate) moved to the donor's body;
- in "real size" the car type's wheels (position, radius) moved to the donor's arches; in "fit" the donor's body is
  scaled to the target's wheels and the physics stays as it was.

What stays the target's: collision volume, engine sound, damage keys (taken from the nearest old vertex), wipers, scuffs,
brakes, the menus' name and numbers (the Stats part of the tab changes those).
"""

import math
import os
import struct
import tempfile

import numpy as np

import hp2car as carinfo
import hp2core as core
import hp2model as model
import hp2tex as tex

PAINTS = [(0.62, 0.05, 0.05), (0.08, 0.16, 0.55), (0.85, 0.85, 0.82), (0.07, 0.07, 0.08), (0.75, 0.62, 0.05),
          (0.55, 0.57, 0.6), (0.08, 0.38, 0.12), (0.85, 0.35, 0.03), (0.35, 0.05, 0.4)]
TRIM_LEVELS = (0.06, 0.25, 0.5, 0.75, 1.0)


# ---- where the donor's wheels are ---------------------------------------------------------------------------------------

def estimate_wheels(parts, wheel):
    """(x front, x rear, half track, centre z, radius, width) from the body's arches and the wheel's size. The arches are
    where the lowest edge of the body's sides is high: each 2 cm slice across x is cut through the side triangles."""
    r = float((wheel.pos[:, 2].max() - wheel.pos[:, 2].min()) / 2) if wheel is not None else 0.32
    width = float(wheel.pos[:, 1].max() - wheel.pos[:, 1].min()) if wheel is not None else 0.22
    tris = []
    for p in parts:
        for m in p.materials:
            idx = m.indices[:len(m.indices) // 3 * 3].reshape(-1, 3)
            tris.append(p.pos[idx])
    tris = np.concatenate(tris).astype(np.float64)              # (n, 3 corners, 3)
    half_w = float(np.abs(tris[..., 1]).max())
    side = tris[(np.abs(tris[..., 1]) > half_w * 0.75).all(1)]
    x0, x1 = float(tris[..., 0].min()), float(tris[..., 0].max())
    bins = np.arange(x0 + 0.01, x1, 0.02)
    lowest = np.full(len(bins), np.nan)
    for k, xc in enumerate(bins):
        zs = []
        for a_, b_ in ((0, 1), (1, 2), (2, 0)):
            pa, pb = side[:, a_], side[:, b_]
            cross = (pa[:, 0] - xc) * (pb[:, 0] - xc) <= 0
            d = pb[cross, 0] - pa[cross, 0]
            t = np.where(np.abs(d) > 1e-9, (xc - pa[cross, 0]) / np.where(np.abs(d) > 1e-9, d, 1), 0)
            zs.append(pa[cross, 2] + t * (pb[cross, 2] - pa[cross, 2]))
        z = np.concatenate(zs)
        if len(z):
            lowest[k] = z.min()
    mid = (x0 + x1) / 2
    sill = np.nanmedian(lowest[np.abs(bins - mid) < (x1 - x0) * 0.12])
    high = np.nan_to_num(lowest, nan=-1e9) > sill + 0.12

    def run(lo, hi):
        best, cur = None, None
        for i in range(len(bins)):
            if not (lo <= bins[i] <= hi):
                continue
            if high[i]:
                cur = [i, i] if cur is None else [cur[0], i]
                if best is None or cur[1] - cur[0] > best[1] - best[0]:
                    best = list(cur)
            else:
                cur = None
        return best
    front, rear = run(mid, x1), run(x0, mid)
    if front is None or rear is None:
        raise ValueError("the wheel arches were not found")
    xf = float(bins[front[0]] + bins[front[1]]) / 2
    xr = float(bins[rear[0]] + bins[rear[1]]) / 2
    top = float(np.nanmax(np.concatenate([lowest[front[0]:front[1] + 1], lowest[rear[0]:rear[1] + 1]])))
    zc = top - r - 0.05
    half_track = half_w - width / 2 - 0.03
    return xf, xr, half_track, zc, r, width


# ---- the skin atlas -----------------------------------------------------------------------------------------------------

class Atlas:
    """Regions of the skin picture: swatches (flat colours) and the donor's pictures, packed in shelves."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.swatches = {}          # key -> (x, y, size), colour set per skin
        self.regions = {}           # texture hash -> (x, y, w, h, rgba)

    def layout(self, pictures, swatch_keys):
        """pictures {hash: rgba}; swatch keys: 'paint', ('trim', level)... The swatches take a row of 16 px cells."""
        cell = 16
        y = self.h - cell
        x = 0
        for k in swatch_keys:
            self.swatches[k] = (x, y, cell)
            x += cell
        room_h = self.h - cell - 2
        items = sorted(pictures.items(), key=lambda kv: -kv[1].shape[0])
        lo, hi = 0.01, 4.0
        best = None
        for _ in range(30):
            f = (lo + hi) / 2
            placed = self._shelves(items, f, room_h)
            if placed is None:
                hi = f
            else:
                lo, best = f, placed
        if best is None:
            best = self._shelves(items, 0.01, room_h) or {}
        self.regions = best

    def _shelves(self, items, f, room_h):
        out, x, y, shelf = {}, 0, 0, 0
        for hsh, img in items:
            w = max(8, int(img.shape[1] * f))
            h = max(8, int(img.shape[0] * f))
            w, h = min(w, self.w), min(h, room_h)
            if x + w > self.w:
                x, y, shelf = 0, y + shelf + 2, 0
            if y + h > room_h:
                return None
            out[hsh] = (x, y, w, h, img)
            x += w + 2
            shelf = max(shelf, h)
        return out

    def uv(self, key, uv):
        """New UVs (n, 2) for a material: a swatch's centre, or the picture's region (UVs clamped to it)."""
        if key in self.swatches:
            x, y, s = self.swatches[key]
            return np.tile([(x + s / 2) / self.w, (y + s / 2) / self.h], (len(uv), 1))
        x, y, w, h, _ = self.regions[key]
        u = np.clip(uv[:, 0], 0, 1)
        v = np.clip(uv[:, 1], 0, 1)
        return np.stack([(x + 0.5 + u * (w - 1)) / self.w, (y + 0.5 + v * (h - 1)) / self.h], 1)

    def picture(self, paint):
        from PIL import Image
        img = np.zeros((self.h, self.w, 4), np.uint8)
        img[..., :3] = 96
        img[..., 3] = 255
        for k, (x, y, s) in self.swatches.items():
            c = paint if k == "paint" else (k[1],) * 3
            img[y:y + s, x:x + s, :3] = (np.array(c) * 255).astype(np.uint8)
        for hsh, (x, y, w, h, pic) in self.regions.items():
            p = np.asarray(Image.fromarray(pic, "RGBA").resize((w, h), Image.LANCZOS))
            img[y:y + h, x:x + w] = p
            img[y:y + h, x:x + w, 3] = 255          # the body is solid; HP2 draws its skins opaque
        return img


# ---- the conversion -----------------------------------------------------------------------------------------------------

class Options:
    def __init__(self, fit="real", donor_wheels=True, paints=None, lights=True):
        self.fit = fit                      # "real": the donor's size, the wheels follow; "fit": scaled to the target
        self.donor_wheels = donor_wheels
        self.paints = paints              # None: the donor game's own paints
        self.lights = lights


class Result:
    def __init__(self):
        self.geo_before = self.geo_after = None
        self.geo_bytes = self.tex_bytes = self.globalb_bytes = None
        self.lines = []


def _window_slot(n, c, xmid):
    # a windscreen leans back and faces up more than forward: whatever faces forward or back more than sideways is the
    # windscreen or the rear window, the rest the side windows
    if abs(n[0]) > abs(n[1]):
        return "WINDOW_FRONT" if n[0] > 0 else "WINDOW_REAR"
    side = "LEFT" if c[1] > 0 else "RIGHT"
    return "WINDOW_%s_%s" % (side, "FRONT" if c[0] > xmid else "REAR")


def convert(data, target, donor, opts=None, log=print):
    """Answers a Result with the new GEOMETRY.geo, CARS/TEXTURES.tex and (in "real" fit) GLOBALB.BUN bytes."""
    import hp2assets as cli
    import hp2physics as ph
    opts = opts or Options()
    res = Result()
    T = target.upper()
    gpath = cli.car_file(data, T)
    gbuf = _source(gpath)
    geo = core.read_geometry(gbuf)
    res.geo_before = core.read_geometry(gbuf)
    names, by_name, packs = cli.texture_names(data)
    ctype = cli.car_type_of(data, T)
    if ctype is None:
        raise SystemExit("%s has no car type record" % T)
    tpath = os.path.join(data, cli.CAR_TEXTURES)
    tbuf = bytearray(_source(tpath))
    textures = {t.name.upper(): t for t in tex.read_textures(tbuf)}

    lods = donor.lods() or ["A"]
    parts_a = donor.stock_parts(lods[0])
    wheel_a = donor.wheel(lods[0])
    import hp2donor as dn
    own = dn.car_wheels(donor.root, donor.car)
    if own:
        # the game's own record of the car: exact
        xf, xr = own[0][0], own[2][0]
        half_track, zc, radius, width = abs(own[0][1]), (own[0][2] + own[2][2]) / 2, own[0][3], own[0][4]
        log("donor %s: wheels from its car record: x %.3f and %.3f, half track %.3f, z %.3f, radius %.3f" % (
            donor.car, xf, xr, half_track, zc, radius))
    else:
        xf, xr, half_track, zc, radius, width = estimate_wheels(parts_a, wheel_a)
        log("donor %s: wheels from the arches: x %.2f and %.2f, half track %.2f, z %.2f, radius %.2f" % (
            donor.car, xf, xr, half_track, zc, radius))
    if opts.paints is None:
        # the donor game's own paints, the first nine (its stock gloss colours): a colour a skin
        ps = [c for n, c in dn.paints(donor.root)]
        opts.paints = ps[:9] if len(ps) >= 9 else PAINTS
        log("skins: the donor's first %d paints" % min(9, len(ps)))
    wheels = ctype.wheels()
    txf, txr, tz = wheels[0][0], wheels[2][0], (wheels[0][2] + wheels[2][2]) / 2
    if opts.fit == "fit":
        s = (txf - txr) / (xf - xr)
        off = np.array([txf - xf * s, 0.0, tz - zc * s])
        log("fit: the donor scaled %.3f to the target's wheelbase %.2f m" % (s, txf - txr))
    else:
        s, off = 1.0, np.zeros(3)

    def place(p):
        return p * s + off

    # pictures for the atlas: the donor's own textures that the body parts show
    pictures, swatch_keys = {}, ["paint"] + [("trim", l) for l in TRIM_LEVELS]
    lamp = {}
    for lod in lods:
        for part in donor.stock_parts(lod):
            for m in part.materials:
                rgba, kind = donor.picture(m.texture)
                name = (donor.texture_name(m.texture) or "").upper()
                if kind == "texture" and rgba is not None and not _special(name):
                    pictures[m.texture] = rgba
    brake = donor.brake("A") if opts.donor_wheels else None
    if opts.donor_wheels:
        # the stock wheel (tyre, rim and hub in one part, all on <CAR>_TIRE): its picture goes into the skin. HP2's
        # <CAR>_TIRE pictures are shared between cars (VANQUISH_TIRE shows DIABLO_TIRE's pixels, as do the Elise's,
        # the Holden's and the TS50's), so changing one would change the others' wheels too
        for lod in lods:
            w = donor.wheel(lod)
            for m in (w.materials if w is not None else ()):
                rgba, kind = donor.picture(m.texture)
                if rgba is not None:
                    pictures[m.texture] = rgba
    if brake is not None:
        # the stock brake (disc and caliper) shows through the rim's spokes: its pictures go into the skin too
        for m in brake.materials:
            rgba, kind = donor.picture(m.texture)
            if rgba is not None:
                pictures[m.texture] = rgba
    skin = textures.get(T + "_SKIN1")
    if skin is None:
        raise SystemExit("%s has no %s_SKIN1 picture" % (T, T))
    atlas = Atlas(skin.width, skin.height)
    atlas.layout(pictures, swatch_keys)
    log("skin atlas %dx%d: %d pictures, %d swatches" % (skin.width, skin.height, len(atlas.regions),
                                                         len(atlas.swatches)))

    # the OBJ the import reads
    lines = ["mtllib none.mtl"]
    vcount = [0]

    def emit(obj_name, tris):
        """tris: [(label, (p, n, uv[, shade]) x3)]. HP2 keeps the light baked into its vertex colours (RGB555: 15 of 31
        shows the picture as it is, 31 twice as bright). A corner with a shade (U1's own darkening, 0 none .. 1 black)
        is lit the way the stock cars' paint is (brighter facing up, 14 + 9 * the normal's up) and darkened by it;
        the others (glass, lamps, trim, wheels) get the plain 15 the stock glass has."""
        lines.append("o %s" % obj_name)
        by_mat = {}
        for label, corners in tris:
            by_mat.setdefault(label, []).append(corners)
        plain = 15 / 31
        for label, cs in by_mat.items():
            lines.append("usemtl %s" % label)
            for c in cs:
                idx = []
                for corner in c:
                    p, n, uv = corner[:3]
                    vcount[0] += 1
                    k = plain
                    if len(corner) > 3 and corner[3] is not None:
                        k = (14 + 9 * float(n[2])) * (1 - 0.6 * float(corner[3])) / 31
                        k = min(1.0, max(3 / 31, k))
                    lines.append("v %.6f %.6f %.6f %.4f %.4f %.4f" % (p[0], p[1], p[2], k, k, k))
                    lines.append("vt %.6f %.6f" % (uv[0], 1 - uv[1]))
                    lines.append("vn %.5f %.5f %.5f" % tuple(n))
                    idx.append(vcount[0])
                lines.append("f %d/%d/%d %d/%d/%d %d/%d/%d" % tuple(i for i in idx for _ in range(3)))

    def body_tris(parts, part_filter=None):
        tris = []
        wins = []
        for part in parts:
            pos = place(part.pos.astype(np.float64))
            nrm = part.normal if part.normal is not None else np.zeros_like(part.pos)
            uv = part.uv if part.uv is not None else np.zeros((len(part.pos), 2))
            col = part.colour if part.colour is not None else np.ones((len(part.pos), 4))
            pname = part.name.upper()
            lamp_part = "HEADLIGHT" in pname or "BRAKELIGHT" in pname
            for m in part.materials:
                rgba, kind = donor.picture(m.texture)
                name = (donor.texture_name(m.texture) or "").upper()
                idx = m.indices[:len(m.indices) // 3 * 3].reshape(-1, 3)
                if not len(idx):
                    continue
                if name.startswith("DRIVER") or "ENGINE" in name:
                    continue
                if kind == "paint":
                    area = np.ptp(uv[m.indices], axis=0)
                    # U1's vertex colour darkens (0 none, 1 black: the bonnet ~0, the sills ~0.3); on a trim
                    # (a paint material with no picture: the seats, the dash, the seals) it is the trim's darkness
                    if area.max() < 1e-3:
                        lvl = 1.0 - float(col[m.indices, :3].mean())
                        key = ("trim", min(TRIM_LEVELS, key=lambda l: abs(l - lvl)))
                        tris += _tris(idx, pos, nrm, atlas.uv(key, uv), T + "_SKIN1")
                    else:
                        tris += _tris(idx, pos, nrm, atlas.uv("paint", uv), T + "_SKIN1", col[:, :3].mean(1))
                elif kind == "texture" and m.texture in atlas.regions:
                    tris += _tris(idx, pos, nrm, atlas.uv(m.texture, uv), T + "_SKIN1")
                elif name == "CARBOTTOM":
                    tris += _tris(idx, pos, nrm, uv, "CARBOTTOM")
                elif kind == "slot" and opts.lights:
                    what = donor.slot_of(m.texture)          # ("HEADLIGHT"|"BRAKELIGHT", "LEFT"|"RIGHT")
                    tris += _tris(idx, pos, nrm, uv, "%s_%s_%s" % (T, what[0], what[1]))
                    lamp[what[0]] = True
                elif name.startswith("WINDOW") or (kind == "unknown" and not lamp_part):
                    wins.append((idx, pos, nrm, uv))
                elif kind == "unknown" and lamp_part:
                    continue                                 # the lamps' clear glass
                else:
                    tris += _tris(idx, pos, nrm, uv if rgba is None else atlas.uv("paint", uv), T + "_SKIN1")
        if wins:
            allc = np.concatenate([p[i].mean(1) for i, p, _, _ in wins])
            xmid = float((allc[:, 0].min() + allc[:, 0].max()) / 2)
            for idx, pos, nrm, uv in wins:
                for t in idx:
                    a, b, c = pos[t]
                    n = np.cross(b - a, c - a)
                    slot = _window_slot(n, (a + b + c) / 3, xmid)
                    tris += _tris(t[None], pos, nrm, uv, slot)
        return tris

    mirror_names = [s.full_name for s in geo.solids() if "SIDE_MIRROR" in s.full_name]
    for i, lod in enumerate("ABCD"):
        dl = lod if lod in lods else lods[min(i, len(lods) - 1)]
        parts = [p for p in donor.stock_parts(dl) if "SIDE_MIRRO" not in p.name.upper() or not mirror_names]
        if geo.solid("%s_%s" % (T, lod)) is None:
            continue
        emit("%s_%s" % (T, lod), body_tris(parts))
    for side in ("LEFT", "RIGHT"):
        tname = "%s_SIDE_MIRROR_%s" % (T, side)
        if tname in mirror_names:
            mp = [p for p in donor.stock_parts(lods[0]) if p.name.upper().startswith(
                "%s_KIT00_%s_SIDE_MIRRO" % (donor.car, side))]
            if mp:
                emit(tname, body_tris(mp))

    # tyres: the donor's wheel, centred, turned round into a right wheel
    tire_tex = None
    if opts.donor_wheels:
        for i, lod in enumerate("ABC"):
            for end in ("FRONT", "REAR"):
                tname = "%s_TIRE_%s_%s" % (T, end, lod)
                if geo.solid(tname) is None:
                    continue
                w = donor.wheel(lod) or donor.wheel(lods[0])
                if w is None:
                    continue
                wp, wn, wuv, wmats = _wheel_arrays(w, donor)
                p = wp.copy()
                c = (p.max(0) + p.min(0)) / 2
                p -= c
                k = len(w.pos)                  # the wheel's own vertices (the circles come after them)
                outer_plus = wn[:k][p[:k, 1] > np.percentile(p[:k, 1], 90), 1].mean() > 0 \
                    if w.normal is not None else True
                n = wn.copy()
                if outer_plus:
                    p[:, :2] *= -1
                    n[:, :2] *= -1
                p *= s
                tris = []
                for texture, idx, disc in wmats:
                    if texture in atlas.regions:
                        tris += _tris(idx, p, n, atlas.uv(texture, wuv), T + "_SKIN1")
                        tire_tex = tire_tex or disc
                emit(tname, tris)
        # the stock brake behind the rim, where the wheel's centre is; HP2 draws the right one and mirrors it for the
        # left, and the donor's is a left one: mirrored in y here
        wa = donor.wheel(lods[0])
        if brake is not None and wa is not None:
            c = (wa.pos.max(0) + wa.pos.min(0)) / 2
            for end in ("FRONT", "REAR"):
                bname = "%s_BRAKE_%s" % (T, end)
                if geo.solid(bname) is None:
                    continue
                p = (brake.pos.astype(np.float64) - c) * np.array([1.0, -1.0, 1.0]) * s
                n = (brake.normal.astype(np.float64) if brake.normal is not None else np.zeros_like(p)) * \
                    np.array([1.0, -1.0, 1.0])
                tris = []
                for m in brake.materials:
                    idx = m.indices[:len(m.indices) // 3 * 3].reshape(-1, 3)[:, [0, 2, 1]]
                    if m.texture in atlas.regions:
                        tris += _tris(idx, p, n, atlas.uv(m.texture, brake.uv), T + "_SKIN1")
                emit(bname, tris)

    # the plate where the donor's is
    plate = donor.marker("REAR_LICENSE_PLATE")
    plate_solid = geo.solid("%s_LICENSE_PLATE_REAR" % T) or next(
        (x for x in geo.solids() if x.full_name == "%s_LICENSE_PLATE_REAR" % T), None)
    if plate is not None and plate_solid is not None:
        pp = np.array([v.pos for st in plate_solid.strips for v in st.verts], float)
        delta = place(np.array(plate)) - (pp.max(0) + pp.min(0)) / 2
        tris = []
        names_ = names
        for e, st in zip(plate_solid.entries, plate_solid.strips):
            label = model.texture_label(plate_solid.textures[e.texture], names_)
            for a, b, c in st.triangles():
                tris.append((label, [(np.array(st.verts[k].pos) + delta,
                                      np.array(st.verts[k].normal or (0, 0, 0)) / 127.0, st.verts[k].st)
                                     for k in (a, b, c)]))
        emit(plate_solid.full_name, tris)

    tmp = tempfile.NamedTemporaryFile("w", suffix=".obj", delete=False, newline="\n")
    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    try:
        for line in model.import_obj(geo, tmp.name, by_name):
            if "skipped" in line or "light material" in line:
                log(line)
    finally:
        os.unlink(tmp.name)

    # markers: the donor's lamps, exhausts and plate; the others moved with the body's box
    _move_markers(geo, res_geo_box(res.geo_before, T), np.array(_box(parts_a, place)), donor, place, log)
    res.geo_bytes = core.write_geometry(geo)
    res.geo_after = core.read_geometry(res.geo_bytes)

    # pictures
    changed = []
    for k in range(1, 10):
        paint = opts.paints[(k - 1) % len(opts.paints)]
        big = atlas.picture(paint)
        for name, img in (("%s_SKIN%d" % (T, k), big), ("%s_SKIN%dB" % (T, k), big)):
            t = textures.get(name)
            if t is None or t.parent:
                continue
            tex.encode_into(tbuf, t, _resize(img, t.width, t.height))
            changed.append(name)
    if opts.lights:
        for kind in ("HEADLIGHT", "BRAKELIGHT"):
            for state in ("OF", "ON", "DA"):
                src = donor.lamp_picture(kind, state)
                if src is None:
                    continue
                for t in textures.values():
                    n = t.name.upper()
                    if not n.startswith("%s_%s" % (T, kind)) or t.parent:
                        continue
                    rest = n[len(T) + len(kind) + 1:]
                    if (state == "OF" and rest == "") or (state == "ON" and rest.startswith("_ON")) or \
                            (state == "DA" and rest.startswith("_DA")):
                        tex.encode_into(tbuf, t, _resize(src, t.width, t.height))
                        changed.append(t.name)
    if tire_tex:
        log("wheels: the donor's stock wheel in the skin; its see-through inner disc drawn as a solid circle")
    log("pictures changed: %s" % ", ".join(changed))
    res.tex_bytes = bytes(tbuf)

    # physics: in real size the wheels go where the donor's are
    if opts.fit != "fit":
        gb_path = os.path.join(data, "GLOBAL", "GLOBALB.BUN")
        gb = _source(gb_path)
        vals = {}
        for i, w in enumerate(("FL", "FR", "RR", "RL")):
            if own:
                x, y, z, rad, wid = own[i]
                vals.update({"Wheel%s.X" % w: x, "Wheel%s.Y" % w: y, "Wheel%s.Z" % w: z, "Wheel%s.Radius" % w: rad,
                             "Wheel%s.Width" % w: wid})
                continue
            x = xf if i in (0, 1) else xr
            y = half_track if i in (0, 3) else -half_track
            vals.update({"Wheel%s.X" % w: x, "Wheel%s.Y" % w: y, "Wheel%s.Z" % w: zc, "Wheel%s.Radius" % w: radius})
        res.globalb_bytes, plines = ph.apply(gb, {ctype.name: vals})
        res.lines += plines
        log("%s: the wheels moved to the donor's (%d values)" % (ctype.name, len(plines)))
    return res


def _source(path):
    """The disc's copy of a game file (<file>.orig, kept the first time it was changed) or the file: a car converted
    again starts from the game's own files, not from the last conversion."""
    orig = path + ".orig"
    return open(orig if os.path.exists(orig) else path, "rb").read()


def _wheel_arrays(w, donor, segments=24):
    """(pos, normal, uv, [(texture, triangles (k, 3), disc)]) of a donor wheel. A flat quad whose picture is see-through
    at its corners (U1's dark disc behind the rim, cut round by its alpha) becomes a real circle: HP2 draws the skin
    opaque, and the quad's corners would stand out of the tyre."""
    pos = w.pos.astype(np.float64)
    nrm = w.normal.astype(np.float64) if w.normal is not None else np.zeros_like(pos)
    uv = w.uv.astype(np.float64) if w.uv is not None else np.zeros((len(pos), 2))
    P, N, U, mats = [pos], [nrm], [uv], []
    count = len(pos)
    for m in w.materials:
        idx = m.indices[:len(m.indices) // 3 * 3].reshape(-1, 3)
        if not len(idx):
            continue
        rgba = donor.picture(m.texture)[0]
        vs = np.unique(idx)
        flat = np.ptp(pos[vs], 0)
        disc = False
        if rgba is not None and len(idx) <= 4 and rgba.shape[2] == 4:
            h, wd = rgba.shape[:2]
            px = np.clip((uv[vs] % 1.0) * [wd, h], 0, [wd - 1, h - 1]).astype(int)
            axis = int(np.argmin(flat))
            disc = flat[axis] < 1e-4 and (rgba[px[:, 1], px[:, 0], 3] == 0).all()
        if not disc:
            mats.append((m.texture, idx, False))
            continue
        # the circle in the quad's plane, its UVs by the quad's own affine mapping
        a, b = [k for k in range(3) if k != axis]
        q = pos[vs]
        centre = (q.max(0) + q.min(0)) / 2
        r = min(np.ptp(q[:, a]), np.ptp(q[:, b])) / 2
        M = np.c_[q[:, a], q[:, b], np.ones(len(q))]
        A = np.linalg.lstsq(M, uv[vs], rcond=None)[0]
        t = np.linspace(0, 2 * np.pi, segments, endpoint=False)
        ring = np.repeat(centre[None], segments + 1, 0)
        ring[1:, a] += r * np.cos(t)
        ring[1:, b] += r * np.sin(t)
        ring_uv = np.c_[ring[:, a], ring[:, b], np.ones(len(ring))] @ A
        n0 = nrm[vs].mean(0)
        e1, e2 = pos[idx[0, 1]] - pos[idx[0, 0]], pos[idx[0, 2]] - pos[idx[0, 0]]
        face = np.cross(e1, e2)                        # the quad's own winding, kept
        fan = np.array([[0, 1 + k, 1 + (k + 1) % segments] for k in range(segments)])
        f1 = np.cross(ring[fan[0, 1]] - ring[0], ring[fan[0, 2]] - ring[0])
        if np.dot(f1, face) < 0:
            fan = fan[:, [0, 2, 1]]
        P.append(ring)
        N.append(np.repeat(n0[None], len(ring), 0))
        U.append(ring_uv)
        mats.append((m.texture, fan + count, True))
        count += len(ring)
    return np.concatenate(P), np.concatenate(N), np.concatenate(U), mats


def _special(name):
    return name.startswith("WINDOW") or name in ("CARBOTTOM", "DRIVER") or "ENGINE" in name or name.endswith("_TIRE")


def _tris(idx, pos, nrm, uv, label, shade=None):
    out = []
    for a, b, c in idx:
        if shade is None:
            out.append((label, [(pos[k], nrm[k], uv[k]) for k in (a, b, c)]))
        else:
            out.append((label, [(pos[k], nrm[k], uv[k], shade[k]) for k in (a, b, c)]))
    return out


def _resize(img, w, h):
    from PIL import Image
    if img.shape[1] == w and img.shape[0] == h:
        return img
    return np.asarray(Image.fromarray(img, "RGBA").resize((w, h), Image.LANCZOS)).copy()


def _box(parts, place):
    p = place(np.concatenate([x.pos for x in parts]).astype(np.float64))
    return p.min(0), p.max(0)


def res_geo_box(geo, T):
    s = geo.solid("%s_A" % T)
    p = np.array([v.pos for st in s.strips for v in st.verts], float)
    return p.min(0), p.max(0)


MARKER_NAMES = {"HEADLIGHT_LEFT": "LEFT_HEADLIGHT", "HEADLIGHT_RIGHT": "RIGHT_HEADLIGHT",
                "BRAKELIGHT_LEFT": "LEFT_BRAKELIGHT", "BRAKELIGHT_RIGHT": "RIGHT_BRAKELIGHT"}


def _move_markers(geo, old_box, new_box, donor, place, log):
    """HP2's position markers (0x34013, 32 bytes: +8 name hash, +16 position) moved from the old body's box to the new
    one's; the lamps and exhausts to the donor's own markers."""
    (o0, o1), (n0, n1) = old_box, new_box
    scale = (n1 - n0) / np.maximum(o1 - o0, 1e-6)
    want = {core.bhash(k): v for k, v in MARKER_NAMES.items()}
    exh = [place(np.array(p)) for p in donor.markers("LEFT_EXHAUST") + donor.markers("RIGHT_EXHAUST")]
    exhaust = core.bhash("EXHAUST")
    for i, it in enumerate(geo.items):
        if it[0] != "raw":
            continue
        raw = bytearray(it[1])
        cid, size = struct.unpack_from("<II", raw, 0)
        if cid != 0x34013:
            continue
        p = 8
        while p < len(raw) and raw[p] == core.FILLER and (p % 16):
            p += 1
        moved = 0
        for r in range(p, len(raw) - 31, 32):
            h = struct.unpack_from("<I", raw, r + 8)[0]
            pos = np.array(struct.unpack_from("<3f", raw, r + 16))
            new = n0 + (pos - o0) * scale
            if h in want:
                ms = donor.markers(want[h])
                if ms:
                    new = place(np.array(ms[0]))
            elif h == exhaust and exh:
                new = min(exh, key=lambda e: abs(e[1] - pos[1]))
            struct.pack_into("<3f", raw, r + 16, *new)
            moved += 1
        geo.items[i] = ("raw", bytes(raw))
        log("%d position markers moved" % moved)
