"""A car's GEOMETRY as Wavefront OBJ and back.

Export: one object per solid (MCLAREN_A, MCLAREN_TIRE_FRONT_A, ...), vertices welded, vertex colours as `v x y z r g b`,
normals where the strips have them, UV with V = 1 - T. The material name carries what a strip needs besides its texture:
`<texture>__f<strip flags hex>__l<light material>__n<1 with normals>`.

Import: any topology. An object named after a solid of the file replaces that solid: its triangles are grouped by material,
turned into triangle strips and packed into strip packets of at most 30 vertices, as the disc's packer lays them out. What OBJ
cannot carry (the vertex alpha bit, colours when the OBJ has none, the body damage keys) comes from the nearest vertex of the
solid being replaced. Solids not in the OBJ stay as they are, byte for byte.
"""

import math
import os
import struct
from collections import Counter, defaultdict

import numpy as np

import hp2core as core

ENTRY_SCALE = 0x8000


# ---- materials ---------------------------------------------------------------------------------------------------------------

def material_name(tex_name, flags, lm, has_normals):
    return "%s__f%04X__l%d__n%d" % (tex_name, flags, lm, 1 if has_normals else 0)


def parse_material(name):
    """(texture part, flags or None, light material or None, normals or None)."""
    parts = name.split("__")
    tex, flags, lm, nrm = parts[0], None, None, None
    for p in parts[1:]:
        try:
            if p[:1] == "f":
                flags = int(p[1:], 16)
            elif p[:1] == "l":
                lm = int(p[1:])
            elif p[:1] == "n":
                nrm = p[1:] == "1"
        except ValueError:
            pass
    return tex, flags, lm, nrm


def texture_label(h, names):
    if h is None:
        return "NONE"
    return names.get(h) or "H%08X" % h


# ---- export ------------------------------------------------------------------------------------------------------------------

def export_obj(geo, names, obj_path, only=None, texture_dir="textures", picture=None, placed=None, mtl_path=None,
               write_mtl=True, bare=False):
    """Write geo's solids (or those named in `only`) to obj_path and its .mtl. Answers {texture name: hash} used.
    picture(label) names the PNG an editor shows for a material (a slot the game fills at run time has none of its own).
    placed: [hp2car.Placed] to write instead, each solid moved by its matrix (the whole car); mtl_path: the .mtl to name
    (and write unless write_mtl is False); bare: no pictures in the .mtl."""
    base = os.path.splitext(obj_path)[0]
    mtl_path = mtl_path or base + ".mtl"
    used_tex, materials = {}, {}
    lines = ["# NFS Hot Pursuit 2 car geometry, hp2assets", "# x forward, y left, z up; V = 1 - T",
             "mtllib %s" % os.path.relpath(mtl_path, os.path.dirname(obj_path) or ".").replace(os.sep, "/")]
    if placed is None:
        placed = [(s.full_name, s, None, False) for s in geo.solids()
                  if not only or s.name in only or s.full_name in only]
    else:
        placed = [(p.label, p.solid, p.matrix, p.mirrored) for p in placed]
    vcount = tcount = ncount = 0
    for oname, s, m, mirrored in placed:
        lines.append("o %s" % oname)
        vidx, tidx, nidx = {}, {}, {}
        faces = defaultdict(list)
        for e, st in zip(s.entries, s.strips):
            texnum = e.texture
            h = s.textures[texnum] if 0 <= texnum < len(s.textures) else None
            label = texture_label(h, names)
            if h is not None:
                used_tex[label] = h
            has_n = st.verts[0].normal is not None
            mat = material_name(label, e.flags, st.light_material, has_n)
            materials[mat] = label
            corner = []
            for v in st.verts:
                pk = struct.pack("<3f", *v.pos) + struct.pack("<H", v.rgba)
                if pk not in vidx:
                    vidx[pk] = vcount = vcount + 1
                    r, g, b = v.rgba & 31, v.rgba >> 5 & 31, v.rgba >> 10 & 31
                    pos = v.pos if m is None else _place(m, v.pos)
                    lines.append("v %.9g %.9g %.9g %.9g %.9g %.9g" % (*pos, r / 31, g / 31, b / 31))
                tk = struct.pack("<2f", *v.st)
                if tk not in tidx:
                    tidx[tk] = tcount = tcount + 1
                    lines.append("vt %.9g %.17g" % (v.st[0], 1 - v.st[1]))
                ni = None
                if has_n:
                    nk = v.normal
                    if nk not in nidx:
                        nidx[nk] = ncount = ncount + 1
                        if m is None:
                            # the stored bytes over 127, not normalised: they come back exactly
                            lines.append("vn %.9g %.9g %.9g" % tuple(c / 127 for c in nk))
                        else:
                            lines.append("vn %.9g %.9g %.9g" % _turn(m, tuple(c / 127 for c in nk)))
                    ni = nidx[nk]
                corner.append((vidx[pk], tidx[tk], ni))
            for a, b, c in st.triangles():
                faces[mat].append((corner[a], corner[c], corner[b]) if mirrored else (corner[a], corner[b], corner[c]))
        for mat, fl in faces.items():
            lines.append("usemtl %s" % mat)
            for tri in fl:
                lines.append("f " + " ".join("%d/%d/%d" % c if c[2] else "%d/%d" % c[:2] for c in tri))
    with open(obj_path, "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    if write_mtl:
        write_mtl_file(mtl_path, materials, None if bare else picture, texture_dir, used_tex)
    return used_tex, materials


def write_mtl_file(mtl_path, materials, picture, texture_dir, used_tex=None):
    """materials {material: texture label}; picture(label) gives the PNG's name, or None: no pictures (a grey model)."""
    with open(mtl_path, "w", newline="\n") as f:
        for mat, label in sorted(materials.items()):
            if picture is None:
                f.write("newmtl %s\nKd 0.7 0.7 0.7\n\n" % mat)
                continue
            f.write("newmtl %s\nKd 1 1 1\n" % mat)
            png = picture(label)
            if png:
                f.write("map_Kd %s/%s.png\n" % (texture_dir, png))
            f.write("\n")


def _place(m, p):
    r0, r1, r2, t = m
    x, y, z = p
    return (r0[0] * x + r0[1] * y + r0[2] * z + t[0], r1[0] * x + r1[1] * y + r1[2] * z + t[1],
            r2[0] * x + r2[1] * y + r2[2] * z + t[2])


def _turn(m, n):
    r0, r1, r2, _ = m
    x, y, z = n
    return (r0[0] * x + r0[1] * y + r0[2] * z, r1[0] * x + r1[1] * y + r1[2] * z, r2[0] * x + r2[1] * y + r2[2] * z)


# ---- OBJ reader --------------------------------------------------------------------------------------------------------------

class ObjMesh:
    def __init__(self):
        self.v, self.vc, self.vt, self.vn = [], [], [], []
        self.objects = {}           # name -> list of (material, [(vi, ti, ni)] * 3)


def read_obj(path):
    m = ObjMesh()
    cur, mat = None, "NONE"
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            p = line.split()
            if not p or p[0].startswith("#"):
                continue
            k = p[0]
            if k == "v":
                m.v.append(tuple(float(x) for x in p[1:4]))
                m.vc.append(tuple(float(x) for x in p[4:7]) if len(p) >= 7 else None)
            elif k == "vt":
                m.vt.append((float(p[1]), float(p[2]) if len(p) > 2 else 0.0))
            elif k == "vn":
                m.vn.append(tuple(float(x) for x in p[1:4]))
            elif k in ("o", "g"):
                name = " ".join(p[1:]) if len(p) > 1 else "default"
                if k == "g" and cur is not None and name.startswith(cur):
                    continue            # Blender's "g object_material" groups stay in their object
                cur = name
                m.objects.setdefault(cur, [])
            elif k == "usemtl":
                mat = " ".join(p[1:])
            elif k == "f":
                if cur is None:
                    cur = "default"
                    m.objects.setdefault(cur, [])
                poly = []
                for c in p[1:]:
                    q = c.split("/")
                    vi = _ix(q[0], len(m.v))
                    ti = _ix(q[1], len(m.vt)) if len(q) > 1 and q[1] else None
                    ni = _ix(q[2], len(m.vn)) if len(q) > 2 and q[2] else None
                    poly.append((vi, ti, ni))
                for i in range(1, len(poly) - 1):
                    m.objects[cur].append((mat, (poly[0], poly[i], poly[i + 1])))
    return m


def _ix(s, n):
    i = int(s)
    return i - 1 if i > 0 else n + i


# ---- strips ------------------------------------------------------------------------------------------------------------------
#
# In a sub-strip starting at local vertex 0 (0 and 1 suppressed), the triangle completed by local vertex v is (v-2, v-1, v)
# for an even v and (v-2, v, v-1) for an odd one (Strip.triangles). A strip is built so that each of its triangles comes out
# with the winding the OBJ face has.

def stripify(tris):
    """Triangle strips (lists of vertex ids) covering `tris`, each listed in the order above."""
    edge = defaultdict(list)
    for i, (a, b, c) in enumerate(tris):
        for x, y, z in ((a, b, c), (b, c, a), (c, a, b)):
            edge[(x, y)].append((i, z))
    used = [False] * len(tris)

    def neighbours(i):
        a, b, c = tris[i]
        return sum(1 for x, y in ((a, b), (b, c), (c, a)) for j, _ in edge[(y, x)] if not used[j])

    def grow(strip, mark):
        while True:
            v = len(strip)
            if v & 1:       # the next triangle is (s[v-2], s[v], s[v-1]): it holds the edge s[v-1] -> s[v-2]
                key = (strip[v - 1], strip[v - 2])
            else:           # (s[v-2], s[v-1], s[v])
                key = (strip[v - 2], strip[v - 1])
            nxt = None
            for j, z in edge.get(key, ()):
                if not used[j] and j not in mark:
                    nxt = (j, z)
                    break
            if nxt is None:
                return strip
            mark.add(nxt[0])
            strip.append(nxt[1])

    order = sorted(range(len(tris)), key=neighbours)
    strips = []
    for i in order:
        if used[i]:
            continue
        a, b, c = tris[i]
        best = None
        for x, y, z in ((a, b, c), (b, c, a), (c, a, b)):
            mark = {i}
            # first triangle (s0, s1, s2) = (x, y, z)
            s = grow([x, y, z], mark)
            if best is None or len(s) > len(best[0]):
                best = (s, mark)
        for j in best[1]:
            used[j] = True
        strips.append(best[0])
    return strips


def pack_strips(strips, limit=core.MAX_STRIP_VERTS):
    """Packets of at most `limit` vertices: each a list of vertex ids and the restart flags. A strip longer than a packet is
    cut at an even vertex, so its triangles keep their winding."""
    packets, cur, dead = [], [], []

    def flush():
        if cur:
            packets.append((list(cur), list(dead)))
            cur.clear()
            dead.clear()

    for s in strips:
        rem = list(s)
        while rem:
            room = limit - len(cur)
            if len(rem) <= room:
                cur.extend(rem)
                dead.extend([True, True] + [False] * (len(rem) - 2))
                rem = []
            elif room >= 4:
                take = room if room % 2 == 0 else room - 1
                cur.extend(rem[:take])
                dead.extend([True, True] + [False] * (take - 2))
                rem = rem[take - 2:]
                flush()
            else:
                flush()
    flush()
    return packets


# ---- import ------------------------------------------------------------------------------------------------------------------

def _nearest_index(points, ref):
    out = np.empty(len(points), np.int64)
    for i in range(0, len(points), 2048):
        d = ((points[i:i + 2048, None, :] - ref[None, :, :]) ** 2).sum(-1)
        out[i:i + 2048] = d.argmin(1)
    return out


def _strip_numbers(verts, tris):
    """Nx, Ny, Nz, Nt and MaterialDensity of a strip entry: the mean face normal turned round (16384 = 1; on the disc it
    points against the faces), the widest face from it (65536 to the turn) and the texels' density, ST area over world area."""
    P = np.array([v.pos for v in verts], float)
    T = np.array([v.st for v in verts], float)
    fn, area, st_area = [], 0.0, 0.0
    for a, b, c in tris:
        n = np.cross(P[b] - P[a], P[c] - P[a])
        ln = np.linalg.norm(n)
        if ln > 0:
            fn.append(n / ln)
            area += ln / 2
        u1, u2 = T[b] - T[a], T[c] - T[a]
        st_area += abs(u1[0] * u2[1] - u1[1] * u2[0]) / 2
    if not fn:
        return (0, 0, 16384, 0), 0.0
    avg = np.sum(fn, 0)
    ln = np.linalg.norm(avg)
    avg = avg / ln if ln > 0 else np.array([0.0, 0.0, 1.0])
    cone = max(math.acos(max(-1.0, min(1.0, float(np.dot(n, avg))))) for n in fn)
    nt = min(32767, int(round(cone * 65536 / (2 * math.pi))))
    q = tuple(int(round(-c * 16384)) for c in avg) + (nt,)
    return q, (st_area / area if area > 0 else 0.0)


def _entry(texnum, offset, qwords, flags, verts, tris, group, lm):
    P = np.array([v.pos for v in verts], np.float32)
    mn, mx = P.min(0) - np.float32(0.01), P.max(0) + np.float32(0.01)
    (nx, ny, nz, nt), dens = _strip_numbers(verts, tris)
    raw = bytearray(64)
    struct.pack_into("<b3x", raw, 0, texnum)
    struct.pack_into("<HHIHH", raw, 4, ENTRY_SCALE, ENTRY_SCALE, offset, qwords, flags)
    struct.pack_into("<3f", raw, 0x10, *mn)
    struct.pack_into("<BBBb", raw, 0x1C, group, len(verts), len(tris), lm)
    struct.pack_into("<3f", raw, 0x20, *mx)
    struct.pack_into("<HH", raw, 0x2C, flags, 0)
    struct.pack_into("<4h", raw, 0x30, nx, ny, nz, nt)
    struct.pack_into("<f", raw, 0x38, dens)
    return core.StripEntry(bytes(raw))


class ImportReport:
    def __init__(self):
        self.lines = []

    def __call__(self, msg):
        self.lines.append(msg)


def rebuild_solid(geo, s, faces, mesh, name_to_hash, report):
    """Replace solid s by the OBJ faces [(material, ((vi, ti, ni),) * 3)]."""
    # what the old solid says: per texture, the flags / light material / normals it was drawn with
    old_verts = [v for st in s.strips for v in st.verts]
    old_pos = np.array([v.pos for v in old_verts], float) if old_verts else np.zeros((1, 3))
    by_tex, overall = defaultdict(Counter), Counter()
    for e, st in zip(s.entries, s.strips):
        h = s.textures[e.texture] if 0 <= e.texture < len(s.textures) else None
        k = (e.flags, st.light_material, st.verts[0].normal is not None)
        by_tex[h][k] += len(st.verts)
        overall[k] += len(st.verts)
    default = overall.most_common(1)[0][0] if overall else (0x4080, -1, False)

    textures = list(s.textures)

    def texture_index(label):
        if label.upper() == "NONE":
            return None
        if label[:1] == "H" and len(label) == 9:
            try:
                h = int(label[1:], 16)
            except ValueError:
                h = None
            if h is not None:
                return h
        return name_to_hash.get(label.upper(), core.bhash(label))

    groups = {}                                    # material key -> list of triangles of vertex ids
    keys = []                                      # vertex id -> (vi, ti, ni, normals?)
    key_ix = {}
    for mat, tri in faces:
        label, flags, lm, nrm = parse_material(mat)
        h = texture_index(label)
        f0, l0, n0 = (by_tex[h].most_common(1)[0][0] if by_tex.get(h) else default)
        flags = f0 if flags is None else flags
        lm = l0 if lm is None else lm
        nrm = n0 if nrm is None else nrm
        if lm >= len(s.light_materials):
            report("  %s: light material %d past its table of %d, none used" % (s.name, lm, len(s.light_materials)))
            lm = -1
        mk = (h, flags, lm, nrm)
        ids = []
        for c in tri:
            k = (c[0], c[1], c[2], nrm)
            if k not in key_ix:
                key_ix[k] = len(keys)
                keys.append(k)
            ids.append(key_ix[k])
        if ids[0] != ids[1] and ids[1] != ids[2] and ids[0] != ids[2]:
            groups.setdefault(mk, []).append(tuple(ids))

    # vertices
    pos = np.array([mesh.v[k[0]] for k in keys], float)
    near = _nearest_index(pos, old_pos) if old_verts else np.zeros(len(keys), np.int64)
    smooth = defaultdict(lambda: np.zeros(3))
    for tris in groups.values():
        for t in tris:
            a, b, c = (pos[i] for i in t)
            n = np.cross(b - a, c - a)
            for i in t:
                smooth[mesh.v[keys[i][0]]] += n
    verts = []
    for i, (vi, ti, ni, nrm) in enumerate(keys):
        ref = old_verts[near[i]] if old_verts else None
        alpha = (ref.rgba & 0x8000) if ref else 0x8000
        col = mesh.vc[vi]
        if col is not None:
            r, g, b = (max(0, min(31, int(round(c * 31)))) for c in col)
            rgba = r | g << 5 | b << 10 | alpha
        else:
            rgba = ref.rgba if ref else 0xFFFF
        u, vv = mesh.vt[ti] if ti is not None else (0.0, 0.0)
        normal = None
        if nrm:
            if ni is not None:
                n = np.array(mesh.vn[ni], float)
            else:
                n = smooth[mesh.v[vi]]          # the faces' own, area-weighted
            ln = np.linalg.norm(n)
            if ln == 0:
                n = np.zeros(3)                 # the disc has 53 of these; they stay
            elif ln > 1.0001 or ln < 0.9:
                n = n / ln
            normal = tuple(int(max(-127, min(127, round(c * 127)))) for c in n)
        verts.append(core.Vertex(tuple(float(np.float32(x)) for x in mesh.v[vi]), (float(np.float32(u)), float(np.float32(1 - vv))),
                                 rgba, normal))

    # strips, in material groups
    entries, strips, packets, out_verts = [], [], [], []
    offset, flags_or, group = 0, 0, 0
    polys = 0
    # the order the game draws them in: the solid's own groups where they were, new opaque ones before the first
    # see-through one, new see-through ones (flag 0x8000: the glass) last. The game draws the glass blended without
    # writing depth, so whatever comes after it (the seats, the body) is drawn over it and the glass is gone
    old_rank, first_blend = {}, None
    for i, e in enumerate(s.entries):
        h0 = s.textures[e.texture] if 0 <= e.texture < len(s.textures) else None
        old_rank.setdefault((h0, e.flags), i)
        if e.flags & 0x8000 and first_blend is None:
            first_blend = i
    first_blend = len(s.entries) if first_blend is None else first_blend

    def draw_order(k):
        r = old_rank.get((k[0], k[1]))
        if r is None:
            r = 1 << 30 if k[1] & 0x8000 else first_blend - 0.5
        return (r, str(k[0]), k[1], k[2], k[3])

    for mk in sorted(groups, key=draw_order):
        h, flags, lm, nrm = mk
        if h is None:
            texnum = None
        else:
            if h not in textures:
                textures.append(h)
                report("  %s: texture %08x added to its table" % (s.name, h))
            texnum = textures.index(h)
        for ids, dead in pack_strips(stripify(groups[mk])):
            st = core.Strip([verts[i] for i in ids], dead, lm)
            pk = core.encode_strip(st)
            tris = st.triangles()
            entries.append((texnum, offset, len(pk) // 16, flags, st.verts, tris, group, lm))
            strips.append(st)
            packets.append(pk)
            out_verts.extend(ids)
            offset += len(pk)
            flags_or |= flags
            polys += len(tris)
        group = min(255, group + 1)
    if len(strips) > 32767:
        raise ValueError("%s: %d strips, more than a solid holds" % (s.name, len(strips)))
    sentinel = len(textures)
    s.entries = [_entry(sentinel if t is None else t, *rest) for t, *rest in entries]
    s.strips, s.packets = strips, packets
    s.textures = textures
    s.raw_tex_table = None

    # the header
    allp = np.array([v.pos for st in strips for v in st.verts], np.float32)
    h = bytearray(s.header)
    nverts = sum(len(st.verts) for st in strips)
    struct.pack_into("<HhhhhI", h, 0x32, flags_or, len(strips), min(32767, polys), min(32767, nverts),
                     min(32767, len(keys)), 0)
    if len(allp):
        struct.pack_into("<4f", h, 0x40, *(allp.min(0) - np.float32(0.01)), 0.0)
        struct.pack_into("<4f", h, 0x50, *(allp.max(0) + np.float32(0.01)), 0.0)
    s.header = bytes(h)
    if nverts > 32767:
        raise ValueError("%s: %d vertices, more than a solid's count holds" % (s.name, nverts))

    # body damage: each new vertex takes the key of the nearest old one, in the order the damage walk goes
    for d in geo.damage():
        if d.name == s.name:
            if d.num_vertices != len(old_verts) or len(d.keys) != len(old_verts):
                report("  %s: its damage info does not match its old vertices, left as it was (dents off)" % s.name)
                break
            npos = np.array([verts[i].pos for i in out_verts], float)
            nn = _nearest_index(npos, old_pos)
            d.keys = [d.keys[j] & ~7 for j in nn]
            d.num_vertices_new = len(out_verts)
            report("  %s: damage keys moved over to %d vertices" % (s.name, len(out_verts)))
    report("%s: %d triangles in %d strips, %d strip vertices (was %d)" % (s.full_name, polys, len(strips), nverts,
                                                                           len(old_verts)))


def import_obj(geo, obj_path, name_to_hash, only=None):
    """Rebuild the solids the OBJ names. Answers the report lines; geo is changed in place."""
    mesh = read_obj(obj_path)
    report = ImportReport()
    by_name = {s.full_name.upper(): s for s in geo.solids()}
    for s in geo.solids():
        by_name.setdefault(s.name.upper(), s)
    done = 0
    for oname, faces in mesh.objects.items():
        name = oname.upper()
        if name not in by_name and "." in name:
            name = name.rsplit(".", 1)[0]               # Blender's MCLAREN_A.001
        s = by_name.get(name)
        if s is None and name.startswith(("WHEEL_", "BRAKE_")) and "__" in name:
            report("object %s: a placed copy from the whole car (edit the part itself), skipped" % oname)
            continue
        if s is None:
            report("object %s: no solid of that name in this car, skipped" % oname)
            continue
        if only and s.name not in only and s.full_name not in only:
            continue
        if not faces:
            report("object %s: no faces, skipped" % oname)
            continue
        rebuild_solid(geo, s, faces, mesh, name_to_hash, report)
        done += 1
    if not done:
        report("nothing imported")
    return report.lines
