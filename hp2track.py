"""Tracks: TRACKS\\TRACKB<nn>.BUN (the TRACKA files are empty) and their pictures TEX<nn>TRACK.tex, TEX<nn>LOCATION.tex.

The drawn geometry is the cars' format: solid lists (0x80034000, ten a track) of eSolids with VU1 strip packets, read and
written by hp2core. Scenery sections (0x80034100) place them: 0x34102 kinds {u32 name hash per level of detail [3],
s16 far clip [3], ..., f32 radius at +36}, 0x34103 instances (48 bytes, 16-aligned: s16 box min[3] max[3], s16 kind,
u16 exclude flags, f32 position[3], s16 rotation[9] in 2^-14; world = v x R + position, R by rows; flag 0x200: drawn where
it is, the solid in world space), 0x34104 the culling tree (24 bytes: s16 box[6], s16 children, s16 codes[5]: >= 0 an
instance, < 0 node -code). See docs scenery.md and the research notes.

Import rebuilds the solids an OBJ names, as for cars, and makes the culling numbers follow: the instances' boxes, their
kinds' radius and the tree's boxes grow to take the new geometry in (they never shrink, which only costs a little culling).
The collision (0x34130-33), the AI's routes, the cameras and the rest stay as they are: cars drive on the old ground.
A changed solid list is followed by an empty chunk so that everything after it keeps its place modulo 2048, and its own
alignment.
"""

import math
import os
import struct

import numpy as np

import hp2core as core
import hp2model as model

SECTION = 0x80034100
SEC_HEAD = 0x00034101
KINDS = 0x00034102
INSTANCES = 0x00034103
TREE = 0x00034104
IN_PLACE = 0x200


def track_files(data):
    """[(name 'TRACKB12', path)] of the tracks that have data."""
    d = os.path.join(data, "TRACKS")
    out = []
    for f in sorted(os.listdir(d)):
        if f.upper().startswith("TRACKB") and f.upper().endswith(".BUN"):
            p = os.path.join(d, f)
            if os.path.getsize(p) > 0:
                out.append((f[:-4].upper(), p))
    return out


def texture_files(data, track):
    """The packs a track draws from: its own two and the game's shared ones."""
    n = track.upper().replace("TRACKB", "")
    rels = ["TRACKS/TEX%sTRACK.tex" % n, "TRACKS/TEX%sLOCATION.tex" % n, "GLOBAL/GLOBALB.BUN", "GLOBAL/INGAMEB.BUN"]
    return [r for r in rels if os.path.isfile(os.path.join(data, r))]


class Section:
    """A scenery section, its bytes kept; the kinds, instances and nodes are read and patched in place."""

    def __init__(self, raw):
        self.raw = bytearray(raw)           # the whole chunk, header included, as it was in the file
        self.kinds_at = self.inst_at = self.tree_at = None
        self.nkinds = self.ninst = self.nnodes = 0
        self.number = -1
        base = 0
        for cid, off, size in core.chunks(self.raw, 8, len(self.raw)):
            p = off + 8
            if cid == SEC_HEAD:
                q = p + ((-p) & 15) if self.raw[p:p + 1] == b"\x11" else p
                self.number = struct.unpack_from("<i", self.raw, q + 8)[0]
            elif cid == KINDS:
                self.kinds_at, self.nkinds = p, size // 40
            elif cid == INSTANCES:
                pad = 0
                while pad < 16 and pad < size and self.raw[p + pad] == 0x11 and (self.file_at + p + pad) % 16:
                    pad += 1
                self.inst_at, self.ninst = p + pad, (size - pad) // 48
            elif cid == TREE:
                self.tree_at, self.nnodes = p, size // 24

    file_at = 0

    def kind(self, i):
        o = self.kinds_at + 40 * i
        return struct.unpack_from("<3I", self.raw, o), struct.unpack_from("<f", self.raw, o + 36)[0]

    def set_radius(self, i, r):
        struct.pack_into("<f", self.raw, self.kinds_at + 40 * i + 36, r)

    def instance(self, i):
        o = self.inst_at + 48 * i
        box = struct.unpack_from("<6h", self.raw, o)
        kind, flags = struct.unpack_from("<hH", self.raw, o + 12)
        pos = struct.unpack_from("<3f", self.raw, o + 16)
        rot = np.array(struct.unpack_from("<9h", self.raw, o + 28), float).reshape(3, 3) / 16384.0
        return box, kind, flags, np.array(pos), rot

    def set_box(self, i, box):
        struct.pack_into("<6h", self.raw, self.inst_at + 48 * i, *box)

    def node(self, i):
        o = self.tree_at + 24 * i
        v = struct.unpack_from("<6hh5h", self.raw, o)
        return list(v[:6]), v[7:7 + v[6]]

    def set_node_box(self, i, box):
        struct.pack_into("<6h", self.raw, self.tree_at + 24 * i, *box)


class Track:
    """items in file order: ("raw", bytes) | ("solids", head, [Solid], original size) | ("section", Section)."""

    def __init__(self, buf):
        self.items = []
        for cid, off, size in core.chunks(buf):
            if cid == core.SOLID_LIST:
                head, solids = None, []
                for c, o, s in core.chunks(buf, off + 8, off + 8 + size):
                    if c == core.SOLID_LIST_HEADER:
                        head = core.leaf_payload(buf, c, o, s)
                    elif c == core.SOLID:
                        solids.append(core.read_solid(buf, o, s))
                    else:
                        raise ValueError("chunk %08x in a solid list" % c)
                self.items.append(["solids", head, solids, size + 8, off])
            elif cid == SECTION:
                Section.file_at = off
                sec = Section(buf[off:off + 8 + size])
                self.items.append(["section", sec, off])
            else:
                self.items.append(["raw", bytes(buf[off:off + 8 + size])])
        self.changed = set()

    def solids(self):
        return [s for it in self.items if it[0] == "solids" for s in it[2]]

    def damage(self):
        return []

    def sections(self):
        return [it[1] for it in self.items if it[0] == "section"]

    def placed(self, only=None):
        """[(label, solid, matrix rows + offset, False)] of every instance at level 0 (the whole track). only: just the
        instances whose direction bits (flags & 0x0C, see DIRECTIONS) are that value."""
        by_hash = {s.name_hash: s for s in self.solids()}
        out = []
        for sec in self.sections():
            for i in range(sec.ninst):
                box, kind, flags, pos, rot = sec.instance(i)
                if not 0 <= kind < sec.nkinds:
                    continue
                if only is not None and flags & 0x0C != only:
                    continue
                hashes, _ = sec.kind(kind)
                s = by_hash.get(hashes[0])
                if s is None:
                    continue
                # world = v x R + P: the rows of R multiply x, y, z; as a matrix on a column vector it is R transposed
                m = (tuple(rot[:, 0]), tuple(rot[:, 1]), tuple(rot[:, 2]), tuple(pos))
                out.append(("S%d_I%d_%s" % (sec.number, i, s.full_name), s, m, False))
        return out

    def build(self):
        w = core.Writer()
        for it in self.items:
            if it[0] == "raw":
                w.raw(it[1])
            elif it[0] == "section":
                w.raw(bytes(it[1].raw))
            else:
                _, head, solids, size, at = it
                start = w.tell()
                w.open(core.SOLID_LIST)
                w.leaf(core.SOLID_LIST_HEADER, head)
                for s in solids:
                    core.write_solid(w, s)
                w.close()
                # what follows keeps its place modulo 2048: an empty chunk takes up the difference
                end, want = w.tell(), at + size
                pad = (want - end) % 2048
                if pad:
                    if pad < 8:
                        pad += 2048
                    w.raw(struct.pack("<II", 0, pad - 8) + bytes(pad - 8))
        return bytes(w.out)


# ---- what a race uses: the direction, the start, the ground ---------------------------------------------------------

# The game leaves out the instances whose ExcludeFlags share a low bit with the view's: 0x08 on a forward race, 0x04 on a
# backward one (and 0x01 in split screen). Both kinds stand in the file at the same places, so drawn together they
# overlap: barriers of the other direction, doubled signs and road pieces.
DIRECTIONS = {"forward": 0x08, "backward": 0x04}

MARKERS = 0x00034146                # TrackPositionMarker, 24 bytes: list node (8), name hash, param, x, y
TOPO_POLYGONS = 0x00034132          # TopologyTreePolygon, 32 bytes: the collision surface
MARKER_NAMES = ("ForwardStartingPosition", "BackwardStartingPosition", "ForwardStartLine", "BackwardStartLine",
                "SplitTimeBoundary1", "SplitTimeBoundary2")

# TopologyTreePolygon flags
INFINITELY_HIGH, VERTICAL, Z_TIMES_FOUR, UPSIDE_DOWN, QUAD = 1, 2, 4, 8, 16


def _leaf(buf, cid):
    """(payload start past the 0x11 alignment filler, end) of the first chunk cid anywhere in the file, or None."""
    def walk(s, e):
        for c, off, size in core.chunks(buf, s, e):
            if c == cid:
                p = off + 8
                while p < off + 8 + size and buf[p] == 0x11 and p % 16:
                    p += 1
                return p, off + 8 + size
            if c & 0x80000000:
                r = walk(off + 8, off + 8 + size)
                if r:
                    return r
        return None
    return walk(0, len(buf))


def read_markers(buf):
    """{name: [(param, x, y)]} of the track's named points (the starting grids, the start lines, the split times)."""
    hit = _leaf(buf, MARKERS)
    names = {core.bhash(n): n for n in MARKER_NAMES}
    out = {}
    if hit:
        p, end = hit
        for i in range((end - p) // 24):
            h, param, x, y = struct.unpack_from("<Iiff", buf, p + 24 * i + 8)
            out.setdefault(names.get(h, "%08x" % h), []).append((param, x, y))
    for v in out.values():
        v.sort()
    return out


def start_places(markers, direction):
    """[(x, y, heading in radians)] of a direction's starting grid, first place first. The cars face the start line: the
    grid stands behind it."""
    d = "Forward" if direction == "forward" else "Backward"
    grid = markers.get(d + "StartingPosition", [])
    line = markers.get(d + "StartLine")
    if not grid:
        return []
    pts = np.array([(x, y) for _, x, y in grid], float)
    aim = np.array(line[0][1:], float) if line else pts[0] + (pts[0] - pts.mean(0))
    v = aim - pts.mean(0)
    heading = math.atan2(v[1], v[0])
    return [(float(x), float(y), heading) for x, y in pts]


class Ground:
    """The collision surface (the TopologyTreePolygons of chunk 0x34132) as the game's GetElevation and its walls use it:
    x and y in eighths of a metre, z in 1/256 above a whole-metre base (four times that on the tall walls). A grid of
    cells finds the polygons near a point."""

    CELL = 24.0

    def __init__(self, buf):
        hit = _leaf(buf, TOPO_POLYGONS)
        n = (hit[1] - hit[0]) // 32 if hit else 0
        self.n = n
        self.cells = {}
        if not n:
            return
        a = np.frombuffer(buf, np.uint8, n * 32, hit[0]).reshape(n, 32)
        self.type = a[:, 2].astype(np.int8)
        self.flags = a[:, 3].copy()
        zbase = a[:, 4:6].copy().view("<i2").reshape(n).astype(np.int64)
        vx = a[:, 8:16].copy().view("<i2").reshape(n, 4).astype(np.float64) / 8.0
        vy = a[:, 16:24].copy().view("<i2").reshape(n, 4).astype(np.float64) / 8.0
        w = (a[:, 24:32].copy().view("<i2").reshape(n, 4).astype(np.int64) << 8) + (zbase[:, None] << 16)
        vz = ((w + (1 << 31)) % (1 << 32) - (1 << 31)).astype(np.float64) / 65536.0     # added as words: it wraps
        vz[(self.flags & Z_TIMES_FOUR) != 0] *= 4.0
        self.v = np.stack([vx, vy, vz], 2)                  # (n, 4, 3)
        self.nv = np.where(self.flags & QUAD, 4, 3)
        nrm = np.cross(self.v[:, 1] - self.v[:, 0], self.v[:, 2] - self.v[:, 0])
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
        self.normal = nrm
        self.d = (self.v[:, 0] * nrm).sum(1)
        self.wall = (self.flags & VERTICAL) != 0
        self.floor = ~self.wall & ((self.flags & UPSIDE_DOWN) == 0) & (np.abs(nrm[:, 2]) > 1e-3)
        lo, hi = self.v[:, :, :2].min(1), self.v[:, :, :2].max(1)
        self.zlo, self.zhi = self.v[:, :, 2].min(1), self.v[:, :, 2].max(1)
        c0, c1 = np.floor(lo / self.CELL).astype(int), np.floor(hi / self.CELL).astype(int)
        for i in range(n):
            for cx in range(c0[i, 0], c1[i, 0] + 1):
                for cy in range(c0[i, 1], c1[i, 1] + 1):
                    self.cells.setdefault((cx, cy), []).append(i)
        # a wall's foot: its two vertices farthest apart in x and y
        self.foot = np.zeros((n, 2, 2))
        for i in np.nonzero(self.wall)[0]:
            p = self.v[i, :self.nv[i], :2]
            dd = ((p[:, None] - p[None]) ** 2).sum(2)
            j, k = np.unravel_index(int(dd.argmax()), dd.shape)
            self.foot[i] = (p[j], p[k])

    def near(self, x, y):
        return self.cells.get((int(math.floor(x / self.CELL)), int(math.floor(y / self.CELL))), ())

    def _inside(self, i, x, y):
        p = self.v[i, :self.nv[i], :2]
        sign = 0
        for k in range(len(p)):
            ax, ay = p[k]
            bx, by = p[(k + 1) % len(p)]
            c = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
            if c != 0:
                if sign == 0:
                    sign = 1 if c > 0 else -1
                elif (c > 0) != (sign > 0):
                    return False
        return True

    def elevation(self, x, y, below=None):
        """(z, terrain type) of the highest ground under (x, y) and not above `below` (so a car stays under a bridge it
        drives beneath), or (None, None) off the surface."""
        best = (None, None)
        for i in self.near(x, y):
            if not self.floor[i] or not self._inside(i, x, y):
                continue
            nx, ny, nz = self.normal[i]
            z = (self.d[i] - nx * x - ny * y) / nz
            if below is not None and z > below:
                continue
            if best[0] is None or z > best[0]:
                best = (float(z), int(self.type[i]))
        return best

    def wall_hit(self, x0, y0, x1, y1, zlo, zhi):
        """The unit direction along the foot of the wall that the move (x0, y0) -> (x1, y1) crosses between the heights
        zlo and zhi, or None."""
        seen = set()
        for cx, cy in ((x0, y0), (x1, y1)):
            for i in self.near(cx, cy):
                if i in seen or not self.wall[i]:
                    continue
                seen.add(i)
                if self.zhi[i] < zlo or (self.zlo[i] > zhi and not self.flags[i] & INFINITELY_HIGH):
                    continue
                (ax, ay), (bx, by) = self.foot[i]
                if _segments_cross(x0, y0, x1, y1, ax, ay, bx, by):
                    d = np.array([bx - ax, by - ay])
                    return d / max(1e-9, float(np.linalg.norm(d)))
        return None


def _segments_cross(ax, ay, bx, by, cx, cy, dx, dy):
    def side(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)
    d1, d2 = side(cx, cy, dx, dy, ax, ay), side(cx, cy, dx, dy, bx, by)
    d3, d4 = side(ax, ay, bx, by, cx, cy), side(ax, ay, bx, by, dx, dy)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def _aabb(points):
    return points.min(0), points.max(0)


def update_culling(track, changed_hashes):
    """After solids changed: the boxes of the instances drawing them (at any level), their kinds' radius, and the culling
    tree's boxes, grown to take the new geometry in. Answers report lines."""
    by_hash = {s.name_hash: s for s in track.solids()}
    lines = []
    for sec in track.sections():
        touched = set()
        for k in range(sec.nkinds):
            hashes, radius = sec.kind(k)
            if not any(h in changed_hashes for h in hashes if h):
                continue
            s0 = by_hash.get(hashes[0])
            if s0 is not None and hashes[0] in changed_hashes:
                pts = np.array([v.pos for st in s0.strips for v in st.verts], float)
                if len(pts):
                    r = float(np.sqrt((pts ** 2).sum(1)).max())
                    if r > radius:
                        sec.set_radius(k, r)
            for i in range(sec.ninst):
                box, kind, flags, pos, rot = sec.instance(i)
                if kind != k:
                    continue
                lo, hi = list(box[:3]), list(box[3:])
                for h in hashes:
                    s = by_hash.get(h)
                    if not h or s is None:
                        continue
                    pts = np.array([v.pos for st in s.strips for v in st.verts], float)
                    if not len(pts):
                        continue
                    world = pts @ rot + pos
                    a, b = world.min(0), world.max(0)
                    lo = [min(lo[j], max(-32768, math.floor(a[j]))) for j in range(3)]
                    hi = [max(hi[j], min(32767, math.ceil(b[j]))) for j in range(3)]
                if (lo, hi) != (list(box[:3]), list(box[3:])):
                    sec.set_box(i, lo + hi)
                    touched.add(i)
        if touched:
            _grow_tree(sec)
            lines.append("section %d: %d instance boxes grown" % (sec.number, len(touched)))
    return lines


def _grow_tree(sec):
    if not sec.nnodes:
        return

    def box_of(code):
        if code >= 0:
            return list(sec.instance(code)[0])
        return visit(-code)

    def visit(n):
        box, codes = sec.node(n)
        lo, hi = box[:3], box[3:]
        for c in codes:
            b = box_of(c)
            lo = [min(lo[j], b[j]) for j in range(3)]
            hi = [max(hi[j], b[3 + j]) for j in range(3)]
        if lo + hi != box:
            sec.set_node_box(n, lo + hi)
        return lo + hi
    visit(0)


def export_track(data, track, out_root, names, picture, bare=False, log=print):
    """OUT/<TRACK>/<TRACK>.obj: every solid in its own space (those drawn where they are in world space): the file to edit
    and import back; <TRACK>_world.obj: the whole track put together (export only); .mtl and textures/."""
    path = dict(track_files(data))[track]
    t = Track(open(path, "rb").read())
    out = os.path.join(out_root, track)
    os.makedirs(out, exist_ok=True)
    mtl = os.path.join(out, track + ".mtl")
    _, mats = model.export_obj(t, names, os.path.join(out, track + ".obj"), write_mtl=False, mtl_path=mtl)
    placed = [_Placed(*p) for p in t.placed()]
    _, mats2 = model.export_obj(t, names, os.path.join(out, track + "_world.obj"), placed=placed, write_mtl=False,
                                mtl_path=mtl)
    mats.update(mats2)
    model.write_mtl_file(mtl, mats, None if bare else picture, "textures")
    log("%s: %d solids, %d placed, %d materials -> %s" % (track, len(t.solids()), len(placed), len(mats), out))
    return t, mats


class _Placed:
    def __init__(self, label, solid, matrix, mirrored):
        self.label, self.solid, self.matrix, self.mirrored = label, solid, matrix, mirrored
