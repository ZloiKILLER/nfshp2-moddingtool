"""Cars of the PC games after HP2 (Underground 1 for now) read for the Experimental tab: their solids and their textures.

The layouts follow NFS-ModTools (github.com/NFSTools/NFS-ModTools, Common/Geometry and Common/Textures), checked on the files.

Underground 1 (speed.exe with TRACKS\\STREAML1RA.BUN): CARS\\<CAR>\\GEOMETRY.BIN and TEXTURES.BIN.
- Solid list 0x80134000: 0x80134001 headers, then 0x80134010 objects. An object: 0x134011 header (16-aligned in the
  file: 12 bytes, u8 version 0x13, u8, u16 flags, u32 name hash, u16 polys, u16 vertices, 4 bytes of counts, 4, f32 min[3],
  4, f32 max[3], 4, f32 pivot[16], 8, 4, 4, 4, then char[28] name), 0x134012 texture hashes (u32 hash, u32), 0x80134100
  the mesh: 0x134900 descriptor (16-aligned: ..., u32 materials at +16, u32 triangles at +36, u16 vertices at +52),
  0x134b01 the vertex buffer (0x80-aligned; 36 bytes: position, normal, u32 colour, uv; 24: position, colour, uv; 60: with
  bone weights), 0x134b02 the materials (16-aligned, 60 bytes: f32 min[3], u32 indices, f32 max[3], s32 texture,
  s32 light material, 4 words, u32 index offset, u32 flags), 0x134b03 the indices (16-aligned, u16 triangle lists, each
  material's in turn).
- Texture pack 0xb3300000: 0x33310001 info, 0x33310004 textures (124 bytes: 12, char[24] name, u32 hash, u32 class,
  u32 parent, u32 data offset, u32 palette offset, u32 data size, u32 palette size, u32 base size, u16 width, u16 height,
  u8 shift w, u8 shift h, u8 compression, u8, u16 palette entries, u8 mips, ...), 0x33310005 the D3D formats (32 bytes,
  the format at +20), 0x33320002 the data (0x80-aligned base).
Alignment is to the position in the file, as the games read them.
"""

import io
import os
import struct
from dataclasses import dataclass, field

import numpy as np

GAMES = ("Underground",)


def detect_game(d):
    """The game installed in folder d, by its program and tracks (NFS-ModTools' GameDetector)."""
    j = lambda *p: os.path.join(d, *p)
    if os.path.isfile(j("speed.exe")) or os.path.isfile(j("SPEED.EXE")):
        if os.path.isfile(j("TRACKS", "L2RA.BUN")) and os.path.isfile(j("TRACKS", "STREAML2RA.BUN")):
            return "MostWanted"
        if os.path.isfile(j("TRACKS", "STREAML1RA.BUN")):
            return "Underground"
    if os.path.isfile(j("speed2.exe")):
        return "Underground2"
    if os.path.isfile(j("nfsc.exe")):
        return "Carbon"
    if os.path.isfile(j("nfs.exe")):
        return "Undercover" if os.path.isfile(j("TRACKS", "L8R_MW2.BUN")) else "ProStreet"
    if os.path.isfile(j("nfsw.exe")):
        return "World"
    return None


def find_game_root(d):
    """d, or the folder under it (two levels) that holds a game."""
    if detect_game(d):
        return d
    for root, dirs, files in os.walk(d):
        if root[len(d):].count(os.sep) > 4:
            dirs[:] = []
            continue
        if detect_game(root):
            return root
    return None


def _ci(d, name):
    """A path in d by name, whatever its case (the games' files are upper case on the disc, any case on Linux)."""
    if not os.path.isdir(d):
        return None
    for f in os.listdir(d):
        if f.upper() == name.upper():
            return os.path.join(d, f)
    return None


def list_cars(root):
    cars = _ci(root, "CARS")
    out = []
    if cars:
        for f in sorted(os.listdir(cars)):
            p = os.path.join(cars, f)
            if os.path.isdir(p) and _ci(p, "GEOMETRY.BIN"):
                out.append(f.upper())
    return out


# ---- compression ---------------------------------------------------------------------------------------------------------

def decompress(blob):
    """A packed blob of the PC games (JDLZ so far) -> its bytes."""
    import ctypes
    import hp2movie
    blob = bytes(blob)
    if blob[:4] == b"JDLZ":
        n = struct.unpack_from("<I", blob, 8)[0]
        out = ctypes.create_string_buffer(n)
        lib = hp2movie.lib()
        lib.jdlz_decompress.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        got = lib.jdlz_decompress(blob, len(blob), out, n)
        if got != n:
            raise ValueError("JDLZ: %d of %d bytes" % (got, n))
        return out.raw
    raise ValueError("packed with %r, not known yet" % blob[:4])


# ---- chunks -------------------------------------------------------------------------------------------------------------

def chunks(buf, off, end):
    while off + 8 <= end:
        cid, size = struct.unpack_from("<II", buf, off)
        yield cid, off + 8, size
        off += 8 + size


def align(p, a):
    return (p + a - 1) & ~(a - 1)


# ---- solids -------------------------------------------------------------------------------------------------------------

@dataclass
class Material:
    texture: int            # texture hash, or None
    indices: np.ndarray     # triangle list into the solid's vertices
    flags: int = 0


@dataclass
class DonorSolid:
    name: str
    hash: int
    pos: np.ndarray                     # (n, 3)
    normal: np.ndarray = None           # (n, 3) or None
    colour: np.ndarray = None           # (n, 4) 0..1, or None
    uv: np.ndarray = None               # (n, 2)
    materials: list = field(default_factory=list)
    pivot: np.ndarray = None
    markers: list = field(default_factory=list)     # (name hash, (x, y, z))

    def triangles(self):
        return sum(len(m.indices) // 3 for m in self.materials)


def _read_u1_object(buf, off, end):
    name, h, pivot = "", 0, None
    textures, markers = [], []
    vb, nverts, mats_raw, idx_at = None, 0, [], None
    for cid, p, size in chunks(buf, off, end):
        e = p + size
        if cid == 0x134011:
            q = align(p, 16)
            h = struct.unpack_from("<I", buf, q + 16)[0]
            pivot = np.array(struct.unpack_from("<16f", buf, q + 64), np.float32)
            name = buf[q + 148:q + 148 + 28].split(b"\0")[0].decode("latin-1")
        elif cid == 0x134012:
            textures = [struct.unpack_from("<I", buf, p + 8 * i)[0] for i in range(size // 8)]
        elif cid == 0x13401A:
            q = align(p, 16)
            for i in range((e - q) // 80):
                r = q + 80 * i
                markers.append((struct.unpack_from("<I", buf, r)[0], struct.unpack_from("<3f", buf, r + 64)))
        elif cid == 0x80134100:
            for c2, p2, s2 in chunks(buf, p, e):
                if c2 == 0x134900:
                    q = align(p2, 16)
                    nverts = struct.unpack_from("<H", buf, q + 52)[0]
                elif c2 == 0x134b01:
                    q = align(p2, 0x80)
                    vb = buf[q:p2 + s2]
                elif c2 == 0x134b02:
                    q = align(p2, 16)
                    for i in range((p2 + s2 - q) // 60):
                        r = struct.unpack_from("<3fI3fii4III", buf, q + 60 * i)
                        mats_raw.append((r[3], r[7], r[13], r[14]))   # indices, texture, offset, flags
                elif c2 == 0x134b03:
                    idx_at = align(p2, 16)
    s = DonorSolid(name, h, np.zeros((0, 3), np.float32), pivot=pivot, markers=markers)
    if vb is None or not nverts:
        return s
    stride = len(vb) // nverts
    a = np.frombuffer(vb[:stride * nverts], np.uint8).reshape(nverts, stride)
    f = lambda o, n: a[:, o:o + 4 * n].copy().view("<f4").reshape(nverts, n)
    if stride in (36, 60):
        s.pos, s.normal = f(0, 3), f(12, 3)
        col, s.uv = a[:, 24:28], f(28, 2)
    elif stride == 24:
        s.pos = f(0, 3)
        col, s.uv = a[:, 12:16], f(16, 2)
    else:
        raise ValueError("%s: vertices of %d bytes" % (name, stride))
    s.colour = col[:, [2, 1, 0, 3]].astype(np.float32) / 255.0      # BGRA
    p = idx_at
    for n, tex, offset, flags in mats_raw:
        ind = np.frombuffer(buf, "<u2", n, p).astype(np.int64)
        p += 2 * n
        s.materials.append(Material(textures[tex] if 0 <= tex < len(textures) else None, ind, flags))
    return s


def read_solids(buf, game="Underground"):
    """[DonorSolid] of every solid list in the file."""
    if game != "Underground":
        raise SystemExit("%s cars are not read yet" % game)
    out = []
    for cid, p, size in chunks(buf, 0, len(buf)):
        if cid != 0x80134000:
            continue
        for c2, p2, s2 in chunks(buf, p, p + size):
            if c2 == 0x80134010:
                out.append(_read_u1_object(buf, p2, p2 + s2))
    return out


# ---- textures -----------------------------------------------------------------------------------------------------------

@dataclass
class DonorTexture:
    name: str
    hash: int
    width: int
    height: int
    format: int
    compression: int
    data: bytes
    palette: bytes = b""

    def rgba(self):
        """The top mip as (h, w, 4) uint8, or None for a format not known."""
        w, h = self.width, self.height
        fmt = self.format
        fourcc = struct.pack("<I", fmt)
        if fourcc in (b"DXT1", b"DXT3", b"DXT5"):
            from PIL import Image
            bs = 8 if fourcc == b"DXT1" else 16
            size = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * bs
            head = struct.pack("<4sIIIIIII44sIIIIIIIIIIIII", b"DDS ", 124, 0x81007, h, w, size, 0, 1, bytes(44),
                               32, 4, fmt, 0, 0, 0, 0, 0, 0x1000, 0, 0, 0, 0)
            img = Image.open(io.BytesIO(head + self.data[:size]))
            img.load()
            return np.asarray(img.convert("RGBA")).copy()
        if self.palette and len(self.data) >= w * h:
            pal = np.frombuffer(self.palette, np.uint8).reshape(-1, 4)[:, [2, 1, 0, 3]]
            idx = np.frombuffer(self.data[:w * h], np.uint8).reshape(h, w)
            return pal[idx].copy()
        if fmt in (21, 22) and len(self.data) >= w * h * 4:       # A8R8G8B8, X8R8G8B8
            a = np.frombuffer(self.data[:w * h * 4], np.uint8).reshape(h, w, 4)[:, :, [2, 1, 0, 3]].copy()
            if fmt == 22:
                a[:, :, 3] = 255
            return a
        return None


def read_textures(buf, game="Underground"):
    """{hash: DonorTexture} of every texture pack (0xb3300000) in the file."""
    out = {}
    for cid, p, size in chunks(buf, 0, len(buf)):
        if cid == 0xB3300000:
            out.update(_read_tpk_v1(buf, p, p + size))
    return out


def _walk(buf, p, end, found):
    for cid, q, size in chunks(buf, p, end):
        if cid & 0x80000000:
            _walk(buf, q, q + size, found)
        else:
            found.append((cid, q, size))


def _read_tpk_v1(buf, p, end):
    leaves = []
    _walk(buf, p, end, leaves)
    infos, formats, base, comp = [], [], None, None
    for cid, q, size in leaves:
        if cid == 0x33310004:
            for i in range(size // 124):
                r = q + 124 * i
                name = buf[r + 12:r + 36].split(b"\0")[0].decode("latin-1")
                h, cls, parent, doff, poff, dsize, psize, bsize = struct.unpack_from("<8I", buf, r + 36)
                w, hh = struct.unpack_from("<HH", buf, r + 68)
                compression = buf[r + 74]
                infos.append((name, h, doff, poff, dsize, psize, w, hh, compression))
        elif cid == 0x33310005:
            formats = [struct.unpack_from("<I", buf, q + 32 * i + 20)[0] for i in range(size // 32)]
        elif cid == 0x33310003:
            comp = {}
            for i in range(size // 20):
                hh_, off_, lc_, l_, fl_ = struct.unpack_from("<5I", buf, q + 20 * i)
                comp[hh_] = (off_, lc_)
        elif cid == 0x33320002:
            base = align(q, 0x80)
    out = {}
    if base is None:
        return out
    for k, (name, h, doff, poff, dsize, psize, w, hh, compression) in enumerate(infos):
        fmt = formats[k] if k < len(formats) else 0
        if comp:
            # each texture packed on its own (JDLZ) at a place of the file: its pixels, then its palette
            if h not in comp:
                continue
            off_, lc_ = comp[h]
            blob = decompress(buf[off_:off_ + lc_])
            data = blob[:dsize]
            pal = blob[poff - doff:poff - doff + psize] if psize else b""
        else:
            data = bytes(buf[base + doff:base + doff + dsize])
            pal = bytes(buf[base + poff:base + poff + psize]) if psize else b""
        out[h] = DonorTexture(name, h, w, hh, fmt, compression, data, pal)
    return out


# ---- a donor car as a whole --------------------------------------------------------------------------------------------

class DonorCar:
    """A car of a donor game: its stock parts (the BASE and KIT00 ones), its textures, and the slots the game fills at
    run time resolved the way U1 fills them (the paint for <CAR>_SKIN1, the lights' OFF pictures for their slots)."""

    def __init__(self, root, car, game=None):
        self.root, self.car = root, car.upper()
        self.game = game or detect_game(root)
        cdir = _ci(_ci(root, "CARS"), car)
        self.solids = read_solids(open(_ci(cdir, "GEOMETRY.BIN"), "rb").read(), self.game)
        self.textures = {}
        files = [_ci(cdir, "TEXTURES.BIN"), _ci(_ci(root, "CARS"), "TEXTURES.BIN")]
        g = _ci(root, "GLOBAL")
        if g:
            files += [os.path.join(g, f) for f in sorted(os.listdir(g)) if f.upper() in ("GLOBALB.BUN", "INGAMEB.BUN")]
        for f in files:
            if f and os.path.isfile(f):
                for h, t in read_textures(open(f, "rb").read(), self.game).items():
                    self.textures.setdefault(h, t)
        self.by_name = {}
        for t in self.textures.values():
            self.by_name.setdefault(t.name.upper(), t)
        self._rgba = {}

    def lods(self):
        """The levels of detail the stock parts have: 'A'.. """
        out = set()
        for s in self.stock_parts(None):
            if s.name[-2:-1] == "_" and s.name[-1] in "ABCD":
                out.add(s.name[-1])
        return sorted(out)

    def stock_parts(self, lod="A", wheels=False):
        """The stock car's parts at a level of detail: BASE and KIT00 (not the other kits, styles and decals); the
        engine (under the bonnet) and the wheels are left out unless asked."""
        c = self.car
        out = []
        for s in self.solids:
            n = s.name.upper()
            if not n.startswith(c + "_") or not len(s.pos):
                continue
            rest = n[len(c) + 1:]
            if not (rest.startswith("BASE") or rest.startswith("KIT00_")):
                continue
            has_lod = n[-2:-1] == "_" and n[-1] in "ABCD"
            if lod is not None and has_lod and not n.endswith("_" + lod):
                continue
            if not has_lod and any(o.name.upper() == n for o in out):
                continue                    # a part without levels (the mirrors) is in the file twice
            if "ENGINE" in rest or ("WHEEL" in rest) != wheels and "WHEEL" in rest:
                continue
            out.append(s)
        if lod is not None and wheels is False:
            out = [s for s in out if "WHEEL" not in s.name.upper()]
        return out

    def wheel(self, lod="A"):
        for s in self.solids:
            n = s.name.upper()
            if n.startswith(self.car + "_KIT00_WHEEL") and n.endswith("_" + lod) and len(s.pos):
                return s
        return None

    def texture_name(self, h):
        t = self.textures.get(h)
        return t.name if t else None

    def picture(self, h, paint=(0.55, 0.05, 0.05)):
        """(rgba, kind) the material of hash h shows: kind 'paint' for the car's skin slot (rgba a flat colour), 'slot'
        for a light slot, 'texture', or 'unknown' (rgba None)."""
        if h in self._rgba:
            return self._rgba[h]
        c = self.car
        res = (None, "unknown")
        t = self.textures.get(h)
        if t is not None:
            res = (t.rgba(), "texture")
        else:
            for k in range(1, 10):
                if h == bhash("%s_SKIN%d" % (c, k)):
                    px = np.zeros((4, 4, 4), np.uint8)
                    px[..., :3] = (np.array(paint) * 255).astype(np.uint8)
                    px[..., 3] = 255
                    res = (px, "paint")
                    break
            else:
                for kind in ("HEADLIGHT", "BRAKELIGHT"):
                    for side in ("LEFT", "RIGHT"):
                        if h == bhash("%s_KIT00_%s_%s" % (c, kind, side)):
                            off = self.lamp_picture(kind, "OF")
                            if off is not None:
                                res = (off, "slot")
        self._rgba[h] = res
        return res

    def slot_of(self, h):
        """("HEADLIGHT"|"BRAKELIGHT", "LEFT"|"RIGHT") of a lamp slot's hash."""
        for kind in ("HEADLIGHT", "BRAKELIGHT"):
            for side in ("LEFT", "RIGHT"):
                if h == bhash("%s_KIT00_%s_%s" % (self.car, kind, side)):
                    return kind, side
        return None

    def lamp_picture(self, kind, state):
        """The stock lamp's picture: state "OF", "ON" or "DA" (damaged). Found by the hash of the whole name: the pack
        keeps names cut at 23 characters, and ..._OFF and ..._ON can come out the same."""
        ends = {"OF": ("OFF",), "ON": ("ON",), "DA": ("DAMAGE", "DAMAGED", "DAMAGE0", "DAM")}[state]
        for e in ends:
            t = self.textures.get(bhash("%s_KIT00_%s_%s" % (self.car, kind, e)))
            if t is not None:
                return t.rgba()
        t = self._prefix("%s_KIT00_%s_%s" % (self.car, kind, state))
        return t.rgba() if t is not None else None

    def markers(self, name):
        """Positions of the stock parts' markers of that name (LEFT_HEADLIGHT, REAR_LICENSE_PLATE, LEFT_EXHAUST...)."""
        h = bhash(name)
        out = []
        for s in self.stock_parts(None):
            if s.name[-1:] in "BCD" and s.name[-2:-1] == "_":
                continue
            for mh, pos in s.markers:
                if mh == h and pos not in out:
                    out.append(pos)
        return out

    def marker(self, name):
        m = self.markers(name)
        return m[0] if m else None

    def brake(self, lod="A"):
        """The stock brake (disc and caliper) of CARS/BRAKES: BRAKE_KIT00_<lod>, or None."""
        if not hasattr(self, "_brakes"):
            self._brakes = {}
            d = _ci(_ci(self.root, "CARS"), "BRAKES")
            g = _ci(d, "GEOMETRY.BIN") if d else None
            if g:
                for s in read_solids(open(g, "rb").read(), self.game):
                    self._brakes[s.name.upper()] = s
        return self._brakes.get("BRAKE_KIT00_" + lod) or self._brakes.get("BRAKE_KIT00_A")

    def _prefix(self, p):
        for n, t in self.by_name.items():
            if n.startswith(p):
                return t
        return None


def bhash(s):
    import hp2core
    return hp2core.bhash(s)


# ---- the game's own records: the car's wheels and the paints --------------------------------------------------------

U1_CAR_TYPE = 3216          # Underground's CarTypeInfo (GLOBALB 0x34600): name +0, base model +32, geometry +64,
                            # wheels at +288, 48 bytes each (x, y, z, 0, radius, width, ...), FL FR RR RL as in HP2


def _globalb(root):
    g = _ci(root, "GLOBAL")
    p = _ci(g, "GLOBALB.BUN") if g else None
    return open(p, "rb").read() if p else None


def car_wheels(root, car):
    """[(x, y, z, radius, width)] of the car's four wheels from the game's car record, or None."""
    b = _globalb(root)
    if not b:
        return None
    for cid, p, size in chunks(b, 0, len(b)):
        if cid != 0x00034600:
            continue
        end = p + size
        while p < end and b[p] == 0x11 and p % 16:        # the packer's filler up to a 16-byte boundary
            p += 1
        size = end - p
        for i in range(size // U1_CAR_TYPE):
            r = p + i * U1_CAR_TYPE
            names = (b[r:r + 32].split(b"\0")[0].decode("latin-1").upper(),
                     b[r + 32:r + 64].split(b"\0")[0].decode("latin-1").upper())
            if car.upper() in names:
                out = []
                for k in range(4):
                    x, y, z = struct.unpack_from("<3f", b, r + 288 + 48 * k)
                    rad, wid = struct.unpack_from("<2f", b, r + 288 + 48 * k + 16)
                    out.append((x, y, z, rad, wid))
                return out
    return None


def paints(root):
    """[(name, (r, g, b) 0..1)] of the game's paints (the car part database, GLOBALB 0x80034602: 48-byte parts {u32 name
    offset, ..., u32 first attribute at +20, u32 count at +28}, 8-byte attributes {u32 key hash, u32 value}, RED GREEN
    BLUE among them), gloss first, in the database's order."""
    import hp2core
    b = _globalb(root)
    if not b:
        return []
    RED, GREEN, BLUE = hp2core.bhash("RED"), hp2core.bhash("GREEN"), hp2core.bhash("BLUE")
    for cid, p, size in chunks(b, 0, len(b)):
        if cid != 0x80034602:
            continue
        ch = {c: (q, n) for c, q, n in chunks(b, p, p + size)}
        if not all(k in ch for k in (0x34604, 0x34605, 0x34606)):
            return []
        (pp, ps), (ap, asz), (sp, ssz) = ch[0x34604], ch[0x34605], ch[0x34606]
        strs = b[sp:sp + ssz]
        out = []
        for i in range(ps // 48):
            row = struct.unpack_from("<12I", b, pp + 48 * i)
            name_off, first, count = row[0], row[5], row[7]
            if name_off >= ssz:
                continue
            name = strs[name_off:strs.find(b"\0", name_off)].decode("latin-1")
            if not (name.startswith("GLOSS_L") or name.startswith("METAL_L") or name.startswith("PEARL")):
                continue
            rgb = {}
            for k in range(first, min(first + count, asz // 8)):
                key, val = struct.unpack_from("<II", b, ap + 8 * k)
                if key in (RED, GREEN, BLUE):
                    rgb[key] = val & 255
            if len(rgb) == 3:
                out.append((name, (rgb[RED] / 255.0, rgb[GREEN] / 255.0, rgb[BLUE] / 255.0)))
        out.sort(key=lambda e: (not e[0].startswith("GLOSS"), e[0]))
        return out
    return []
