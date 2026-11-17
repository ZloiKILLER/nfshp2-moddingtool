"""The game's files as the asset tool reads and writes them: bChunk trees, car geometry (eSolid with its VU1 strip packets),
body damage keys and texture packs.

Nothing here is guessed from another game: the layouts are those the port's renderer reads (nfshp2-port-win, recomp/runtime/native.cpp: the
packet, the ADC bits, the winding), the game's own loaders as decompiled for the port, and the format notes of NFSHP2-3DS
(github.com/Octoblimp/NFSHP2-3DS, docs/formats). `hp2assets.py verify` re-encodes every car of an install and compares it with the disc's.
"""

import struct
from dataclasses import dataclass, field

FILLER = 0x11

# ---- bChunk ------------------------------------------------------------------------------------------------------------------

SOLID_LIST, SOLID_LIST_HEADER, SOLID = 0x80034000, 0x00034001, 0x80034002
SOLID_HEADER, STRIP_ENTRIES, STRIP_DATA = 0x00034003, 0x00034004, 0x00034005
TEXTURE_TABLE, LIGHT_MATERIALS = 0x00034006, 0x0003401D
BODY_DAMAGE = 0x00034030

# Leaves whose loader takes GetAlignedData(16): the packer puts 0x11 in front of the payload up to a 16-byte boundary of the
# file (the file is loaded on a 128-byte boundary). Measured over every car file of the disc; the rest are read where they start.
ALIGNED16 = {0x00034003, 0x0003401D, 0x00034004, 0x00034005, 0x00034012, 0x00034013, 0x00034023, 0x00034024, 0x00034025,
             0x00034026}


def chunks(buf, off=0, end=None):
    """(id, header offset, payload size) of each chunk in [off, end)."""
    end = len(buf) if end is None else end
    while off + 8 <= end:
        cid, size = struct.unpack_from("<II", buf, off)
        if off + 8 + size > end:
            raise ValueError("chunk %08x at 0x%x runs past its parent" % (cid, off))
        yield cid, off, size
        off += 8 + size


def leaf_payload(buf, cid, off, size):
    """A leaf's payload without the packer's front filler."""
    p = off + 8
    if cid in ALIGNED16:
        pad = (-p) & 15
        if pad <= size and all(b == FILLER for b in buf[p:p + pad]):
            return bytes(buf[p + pad:p + size])
    return bytes(buf[p:p + size])


class Writer:
    """Chunks as the packer wrote them, at their place in the file."""

    def __init__(self, base=0):
        self.out = bytearray()
        self.base = base            # the file offset of out[0]
        self.stack = []

    def tell(self):
        return self.base + len(self.out)

    def raw(self, data):
        self.out += data

    def leaf(self, cid, payload):
        self.out += struct.pack("<II", cid, 0)
        at = len(self.out)
        if cid in ALIGNED16:
            self.out += bytes([FILLER]) * ((-self.tell()) & 15)
        self.out += payload
        struct.pack_into("<I", self.out, at - 4, len(self.out) - at)

    def open(self, cid):
        self.out += struct.pack("<II", cid, 0)
        self.stack.append(len(self.out))

    def close(self):
        at = self.stack.pop()
        struct.pack_into("<I", self.out, at - 4, len(self.out) - at)


def bhash(s):
    """bStringHash: h = h * 33 + c from 0xffffffff."""
    h = 0xFFFFFFFF
    for c in s.encode("latin-1") if isinstance(s, str) else s:
        h = (h * 33 + c) & 0xFFFFFFFF
    return h


# ---- the strip packet --------------------------------------------------------------------------------------------------------
#
# VU memory of a strip (quads): 0 header {NumVerts, NumLoops, 3 NumVerts, 4 LightMaterial} V4-8, 1 the ADC seeds V4-32,
# 2.. XYZ transposed in fours (three quads to four vertices), 32.. ST two vertices to a quad, mirrored (S0 T0 T1 S1),
# 52.. RGBA5551 one quad a vertex, 92.. normals V4-8 transposed like XYZ (optional). Then MSCAL 0 and NOPs to a quadword.

MAX_STRIP_VERTS = 30
XYZ_AT, ST_AT, RGBA_AT, NORMAL_AT = 2, 0x20, 0x34, 0x5C


def _lfsr(r):
    return (r << 1 | ((r >> 22 ^ r >> 4) & 1)) & 0x7FFFFF


def _adc_segments(loops, n):
    """For each vertex, (seed word, steps since the seed) as vuiReferenceStripper takes them (native.cpp strip_adc)."""
    out, word, k, v = [], 0, 0, 0
    for call in range(11 - loops, 12):
        if call == 4:
            word, k = 2, 0
        if call == 8:
            word, k = 3, 0
        for _ in range(7 if call == 11 - loops else 4):
            if v >= n:
                return out
            k += 1
            out.append((word, k))
            v += 1
    while v < n:            # past the last call: drawn as restarts
        out.append((None, 0))
        v += 1
    return out


def adc_decode(words, loops, n):
    """True for a vertex that does not kick a triangle."""
    r, out = words[0] & 0x7FFFFF, []
    for call in range(11 - loops, 12):
        if call == 4:
            r = words[2] & 0x7FFFFF
        if call == 8:
            r = words[3] & 0x7FFFFF
        for _ in range(7 if call == 11 - loops else 4):
            if len(out) >= n:
                break
            r = _lfsr(r)
            out.append(bool(r >> 15 & 1))
    while len(out) < n:
        out.append(True)
    return out


def adc_encode(dead, loops, n):
    """Seeds that make the VU program suppress exactly the vertices in `dead` (a list of bools)."""
    seeds = {0: 0, 2: 0, 3: 0}
    seg = _adc_segments(loops, n)
    for v, (word, k) in enumerate(seg):
        if word is None:
            if not dead[v]:
                raise ValueError("vertex %d is past the strip program's calls" % v)
            continue
        want = 1 if dead[v] else 0
        s = seeds[word]
        if k <= 15:
            s |= want << (15 - k)
        else:
            j = k - 15                      # the j-th feedback bit lands at bit 15 after k steps
            if j > 4:
                raise ValueError("too many vertices for one ADC seed")
            low = s >> (5 - j) & 1          # bit 4 of the register before step j, set by output 11 + j - 1
            s |= (want ^ low) << (23 - j)   # bit 22 of the register before step j
        seeds[word] = s
    words = [seeds[0], 0, seeds[2], seeds[3]]
    if adc_decode(words, loops, n) != list(dead):
        raise AssertionError("ADC seeds do not reproduce the restarts")
    return words


def vif_unpack(data):
    """Replay a strip's UNPACKs: {address: (raw u32 lanes)} and which addresses had what command."""
    mem, cmds, p, end = {}, [], 0, len(data)
    while p + 4 <= end:
        code, = struct.unpack_from("<I", data, p)
        p += 4
        cmd, num, imm = code >> 24 & 0x7F, code >> 16 & 0xFF, code & 0xFFFF
        if cmd & 0x60 != 0x60:
            if cmd in (0x14, 0x15, 0x17):
                break
            continue
        vn, vl = cmd >> 2 & 3, cmd & 3
        n = num or 256
        usn, at = imm >> 14 & 1, imm & 0x3FF
        elems = vn + 1
        if vl == 3:
            nbytes = (n * 2 + 3) & ~3
        else:
            nbytes = ((n * elems * (32 >> vl) + 31) // 32) * 4
        cmds.append((cmd, n, imm))
        for i in range(n):
            if vl == 3:
                h, = struct.unpack_from("<H", data, p + i * 2)
                mem[at + i] = (h & 31, h >> 5 & 31, h >> 10 & 31, h >> 15 & 1, h)
            elif vl == 0:
                mem[at + i] = struct.unpack_from("<%dI" % elems, data, p + i * elems * 4)
            elif vl == 1:
                mem[at + i] = struct.unpack_from("<%d%s" % (elems, "H" if usn else "h"), data, p + i * elems * 2)
            else:
                mem[at + i] = struct.unpack_from("<%d%s" % (elems, "B" if usn else "b"), data, p + i * elems)
        p += nbytes
    return mem, cmds


def f32(u):
    return struct.unpack("<f", struct.pack("<I", u))[0]


@dataclass
class Vertex:
    pos: tuple          # 3 floats, the game's frame (x forward, y left, z up)
    st: tuple           # S, T as the GS takes them (T = 0 at the image's top row)
    rgba: int           # the RGBA5551 halfword
    normal: tuple       # 3 signed bytes, or None for a strip without normals

    def key(self):
        return (struct.pack("<3f2f", *self.pos, *self.st), self.rgba, self.normal)


@dataclass
class Strip:
    verts: list
    dead: list          # per vertex: no triangle kicked
    light_material: int  # -1 none
    raw_adc: tuple = (0, 0, 0, 0)

    def triangles(self):
        """The strip's triangles, indices into verts, wound as its normals face.

        The winding's parity counts from the first vertex of each restart pair (from 0 for the first sub-strip): checked
        against the vertex normals on the whole disc (NFSHP2-3DS, docs/formats/solid-geometry.md, "Winding"). The PS2 culls no
        triangle by its winding, so the order only matters to an editor."""
        out, ref = [], 0
        for v in range(len(self.verts)):
            if self.dead[v]:
                if v == 0 or not self.dead[v - 1]:
                    ref = v
                continue
            if v < 2:
                continue
            if (v - ref) & 1:
                out.append((v - 2, v, v - 1))
            else:
                out.append((v - 2, v - 1, v))
        return out


def decode_strip(data):
    mem, cmds = vif_unpack(data)
    head = mem.get(0)
    if head is None or 1 not in mem:
        raise ValueError("strip without its header")
    n, loops, lm4 = head[0] & 0xFF, head[1] & 0xFF, head[3]
    if not 3 <= n <= MAX_STRIP_VERTS:
        raise ValueError("strip of %d vertices" % n)
    adc = tuple(mem[1]) + (0,) * (4 - len(mem[1]))
    has_n = NORMAL_AT in mem
    verts = []
    for v in range(n):
        g, l = XYZ_AT + 3 * (v // 4), v % 4
        pos = tuple(f32(mem[g + c][l]) for c in range(3))
        q = mem.get(ST_AT + (v >> 1), (0, 0, 0, 0))
        st = (f32(q[3]), f32(q[2])) if v & 1 else (f32(q[0]), f32(q[1]))
        rgba = mem[RGBA_AT + v][4] if RGBA_AT + v in mem else 0xFFFF
        nrm = tuple(mem[NORMAL_AT + 3 * (v // 4) + c][l] for c in range(3)) if has_n else None
        verts.append(Vertex(pos, st, rgba, nrm))
    lm = (lm4 - 256 if lm4 > 127 else lm4) // 4 if isinstance(lm4, int) else -1
    return Strip(verts, adc_decode(adc, loops, n), lm, adc)


def encode_strip(strip, adc_words=None):
    """The packet for a strip, as the disc's packer lays it out."""
    verts, n = strip.verts, len(strip.verts)
    if not 3 <= n <= MAX_STRIP_VERTS:
        raise ValueError("a strip holds 3 to %d vertices, not %d" % (MAX_STRIP_VERTS, n))
    if not strip.dead[0] or not strip.dead[1]:
        raise ValueError("a strip starts with two suppressed vertices")
    loops = (n - 1) >> 2
    words = list(adc_words) if adc_words is not None else adc_encode(strip.dead, loops, n)
    out = bytearray()

    def code(cmd, num, imm):
        out.extend(struct.pack("<I", cmd << 24 | (num & 0xFF) << 16 | imm))

    code(0x6E, 1, 0x8000)
    out += struct.pack("<4b", n, loops, 3 * n if 3 * n < 128 else 3 * n - 256, 4 * strip.light_material)
    code(0x6C, 1, 0xC001)
    out += struct.pack("<4I", *words)
    full, rem = divmod(n, 4)
    if full:
        code(0x6C, 3 * full, 0xC000 | XYZ_AT)
        for g in range(full):
            for c in range(3):
                out += struct.pack("<4f", *(verts[4 * g + l].pos[c] for l in range(4)))
    if rem:
        code((0x60, 0x64, 0x68)[rem - 1], 3, 0xC000 | (XYZ_AT + 3 * full))
        for c in range(3):
            out += struct.pack("<%df" % rem, *(verts[4 * full + l].pos[c] for l in range(rem)))
    pairs = n >> 1
    code(0x6C, pairs, 0xC000 | ST_AT)
    for i in range(pairs):
        a, b = verts[2 * i].st, verts[2 * i + 1].st
        out += struct.pack("<4f", a[0], a[1], b[1], b[0])
    if n & 1:
        code(0x64, 1, 0xC000 | (ST_AT + pairs))
        out += struct.pack("<2f", *verts[n - 1].st)
    code(0x6F, n, 0xC000 | RGBA_AT)
    col = struct.pack("<%dH" % n, *(v.rgba for v in verts))
    out += col + bytes((-len(col)) & 3)
    if verts[0].normal is not None:
        groups = (n + 3) // 4
        code(0x6E, 3 * groups, 0x8000 | NORMAL_AT)
        for g in range(groups):
            for c in range(3):
                lanes = [verts[4 * g + l].normal[c] if 4 * g + l < n else 0 for l in range(4)]
                out += struct.pack("<4b", *lanes)
    code(0x14, 0, 0)
    out += bytes((-len(out)) & 15)
    return bytes(out)


# ---- eSolid ------------------------------------------------------------------------------------------------------------------

@dataclass
class StripEntry:
    raw: bytes          # the 64 bytes as on the disc

    @property
    def texture(self):
        return self.raw[0] if self.raw[0] < 128 else self.raw[0] - 256

    @property
    def flags(self):
        return struct.unpack_from("<H", self.raw, 0x0E)[0]

    @property
    def group(self):
        return self.raw[0x1C]

    @property
    def qwords(self):
        return struct.unpack_from("<H", self.raw, 0x0C)[0]


@dataclass
class Solid:
    header: bytes                   # the 192-byte eSolid
    textures: list                  # name hashes of 0x34006
    light_materials: list           # name hashes of 0x3401d
    entries: list                   # StripEntry
    strips: list                    # Strip, decoded
    packets: list                   # the strips' packets as stored
    extra: list = field(default_factory=list)   # other leaves, (id, payload), in place
    order: list = field(default_factory=list)   # the children's ids in file order
    raw_tex_table: bytes = b""
    raw_lm_table: bytes = b""

    @property
    def name(self):
        return self.header[0x10:0x28].split(b"\0")[0].decode("latin-1")

    @property
    def name_hash(self):
        return struct.unpack_from("<I", self.header, 0x08)[0]

    @property
    def full_name(self):
        """The name its hash was made from: the stored one stops at 23 characters, and two mirrors of a car can come out
        the same (CORVETTECOP_SIDE_MIRROR_LEFT and _RIGHT). Unknown endings give NAME@hash."""
        n, h = self.name, self.name_hash
        if bhash(n) == h:
            return n
        for end in _NAME_ENDS:
            if bhash(n + end) == h:
                return n + end
        return "%s@%08X" % (n, h)

    def counts(self):
        return struct.unpack_from("<HHhhhh", self.header, 0x30)  # Flags, StripFlags, strips, polys, verts, original verts


_WORDS = ("LEFT", "RIGHT", "FRONT", "REAR", "A", "B", "C", "D", "_A", "_B", "_C", "_D", "_LEFT", "_RIGHT", "_FRONT", "_REAR",
          "PLATE_REAR", "PLATE_FRONT", "MIRROR_LEFT", "MIRROR_RIGHT", "WIPER_LEFT", "WIPER_RIGHT", "BLUR_F", "BLUR_R")
_NAME_ENDS = sorted({w[i:] for w in _WORDS for i in range(len(w))} | {w + x for w in ("LEFT", "RIGHT", "FRONT", "REAR")
                                                                     for x in ("_A", "_B", "_C", "_D")}, key=len)


def _hash_table(payload):
    return [struct.unpack_from("<I", payload, i)[0] for i in range(0, len(payload) - 7, 8)]


def read_solid(buf, off, size):
    parts, order = {}, []
    for cid, coff, csize in chunks(buf, off + 8, off + 8 + size):
        if cid & 0x80000000:
            raise ValueError("a container inside a solid")
        parts[cid] = leaf_payload(buf, cid, coff, csize)
        order.append(cid)
    header = parts[SOLID_HEADER]
    if len(header) != 192:
        raise ValueError("eSolid of %d bytes" % len(header))
    nstrips = struct.unpack_from("<h", header, 0x34)[0]
    ent = parts.get(STRIP_ENTRIES, b"")
    data = parts.get(STRIP_DATA, b"")
    entries, strips, packets, p = [], [], [], 0
    for i in range(nstrips):
        e = StripEntry(ent[i * 64:(i + 1) * 64])
        pk = data[p:p + e.qwords * 16]
        p += e.qwords * 16
        entries.append(e)
        packets.append(pk)
        strips.append(decode_strip(pk))
    extra = [(cid, parts[cid]) for cid in order
             if cid not in (SOLID_HEADER, STRIP_ENTRIES, STRIP_DATA, TEXTURE_TABLE, LIGHT_MATERIALS)]
    return Solid(header, _hash_table(parts.get(TEXTURE_TABLE, b"")), _hash_table(parts.get(LIGHT_MATERIALS, b"")),
                 entries, strips, packets, extra, order, parts.get(TEXTURE_TABLE, b""), parts.get(LIGHT_MATERIALS, b""))


def write_solid(w, s):
    w.open(SOLID)
    tex = s.raw_tex_table if s.raw_tex_table is not None else b"".join(struct.pack("<II", h, 0) for h in s.textures)
    lms = s.raw_lm_table if s.raw_lm_table is not None else b"".join(struct.pack("<II", h, 0) for h in s.light_materials)
    payloads = {SOLID_HEADER: s.header, TEXTURE_TABLE: tex, LIGHT_MATERIALS: lms,
                STRIP_ENTRIES: b"".join(e.raw for e in s.entries), STRIP_DATA: b"".join(s.packets)}
    payloads.update(dict(s.extra))
    order = s.order or [SOLID_HEADER, TEXTURE_TABLE, LIGHT_MATERIALS, STRIP_ENTRIES, STRIP_DATA]
    for cid in order:
        w.leaf(cid, payloads[cid])
    w.close()


# ---- body damage (0x34030) ---------------------------------------------------------------------------------------------------

@dataclass
class DamageInfo:
    raw: bytes      # the 84-byte info as stored (its list node is the packer's garbage and is overwritten at load)
    keys: list      # one u32 per key
    tail: bytes = b""

    @property
    def name(self):
        return self.raw[8:40].split(b"\0")[0].decode("latin-1")

    @property
    def num_vertices(self):
        return struct.unpack_from("<i", self.raw, 68)[0]

    def payload(self):
        raw = bytearray(self.raw)
        struct.pack_into("<ii", raw, 68, self.num_vertices_new, len(self.keys))
        return bytes(raw) + struct.pack("<%dI" % len(self.keys), *self.keys) + self.tail

    num_vertices_new: int = -1


def read_damage(payload):
    nverts, nkeys = struct.unpack_from("<ii", payload, 68)
    keys = list(struct.unpack_from("<%dI" % nkeys, payload, 84))
    d = DamageInfo(payload[:84], keys, payload[84 + 4 * nkeys:])
    d.num_vertices_new = nverts
    return d


# ---- a car's GEOMETRY ------------------------------------------------------------------------------------------------------

@dataclass
class Geometry:
    """A GEOMETRY.geo (GEOMETRY.BIN unpacked). Everything but the damage infos and the solid list is kept as bytes."""
    items: list         # ("raw", bytes) | ("damage", DamageInfo) | ("solids", list_header_payload, [Solid]) in file order
    source: bytes = b""

    def solids(self):
        for it in self.items:
            if it[0] == "solids":
                return it[2]
        return []

    def damage(self):
        return [it[1] for it in self.items if it[0] == "damage"]

    def solid(self, name):
        for s in self.solids():
            if s.name == name:
                return s
        return None


def read_geometry(buf):
    items = []
    for cid, off, size in chunks(buf):
        if cid == BODY_DAMAGE:
            items.append(("damage", read_damage(leaf_payload(buf, cid, off, size))))
        elif cid == SOLID_LIST:
            head, solids = None, []
            for c, o, s in chunks(buf, off + 8, off + 8 + size):
                if c == SOLID_LIST_HEADER:
                    head = leaf_payload(buf, c, o, s)
                elif c == SOLID:
                    solids.append(read_solid(buf, o, s))
                else:
                    raise ValueError("chunk %08x in a solid list" % c)
            items.append(("solids", head, solids))
        else:
            items.append(("raw", bytes(buf[off:off + 8 + size])))
    return Geometry(items, bytes(buf))


def write_geometry(geo):
    w = Writer()
    for it in geo.items:
        if it[0] == "raw":
            w.raw(it[1])
        elif it[0] == "damage":
            w.leaf(BODY_DAMAGE, it[1].payload())
        else:
            w.open(SOLID_LIST)
            w.leaf(SOLID_LIST_HEADER, it[1])
            for s in it[2]:
                write_solid(w, s)
            w.close()
    return bytes(w.out)
