"""Texture packs (chunk 0xb0300001): every texture of a file as RGBA, and a picture written back into the pack in place.

The layout is the GS's: PSMT4 / PSMT8 with a PSMCT32 CLUT, or PSMCT32; some levels are stored swizzled (uploaded as PSMCT32 and
read as PSMT8/PSMT4). The pixel and CLUT offsets count from the data chunk's payload rounded up to 128 bytes
(LoaderTexturePack, 0x00100830). Alpha is the GS's, 0x80 = opaque; the PNGs have it doubled, as everyone else reads a PNG.
Field names and the swizzle are those of NFSHP2-3DS's docs/formats/texture-pack.md (github.com/Octoblimp/NFSHP2-3DS).
"""

import struct

import numpy as np

PACK, PACK_HEADER, PACK_INFO, PACK_DATA = 0xB0300001, 0x30300002, 0x30300003, 0x30300004
RECORD = 164


def _chunks(buf, off, end):
    while off + 8 <= end:
        cid, size = struct.unpack_from("<II", buf, off)
        if off + 8 + size > end:
            return
        yield cid, off, size
        off += 8 + size


def find_packs(buf, off=0, end=None):
    """(offset, size) of every texture pack, nested ones too."""
    end = len(buf) if end is None else end
    out = []
    for cid, o, s in _chunks(buf, off, end):
        if cid == PACK:
            out.append((o, s))
        elif cid & 0x80000000:
            out.extend(find_packs(buf, o + 8, o + 8 + s))
    return out


class Texture:
    def __init__(self, buf, rec_at, base):
        r = rec_at
        self.rec_at, self.base = rec_at, base
        self.name = buf[r + 8:r + 0x20].split(b"\0")[0].decode("latin-1")
        self.hash, = struct.unpack_from("<I", buf, r + 0x20)
        self.width, self.height = struct.unpack_from("<2H", buf, r + 0x24)
        self.bpp = buf[r + 0x28]
        self.palette_entries, = struct.unpack_from("<H", buf, r + 0x2A)
        self.image_at, self.palette_at, self.image_size, self.palette_size = struct.unpack_from("<4I", buf, r + 0x30)
        self.parent, = struct.unpack_from("<I", buf, r + 0x40)
        self.levels = struct.unpack_from("<b", buf, r + 0x6E)[0] + 1
        self.swizzled = [struct.unpack_from("<b", buf, r + 0x55 + 4 * i)[0] == 1 for i in range(min(7, max(1, self.levels)))]

    def mips(self):
        """(level, w, h, offset in the blob, bytes)."""
        off = self.image_at
        for level in range(max(1, self.levels)):
            w, h = max(1, self.width >> level), max(1, self.height >> level)
            n = w * h * self.bpp // 8
            yield level, w, h, off, n
            off += n


def read_textures(buf):
    """Every texture of every pack in a file."""
    out = []
    for off, size in find_packs(buf):
        info_at = info_size = base = None
        for cid, o, s in _chunks(buf, off + 8, off + 8 + size):
            if cid == PACK_INFO:
                info_at, info_size = o + 8, s
            elif cid == PACK_DATA:
                base = (o + 8 + 127) & ~127
        if info_at is None or base is None:
            continue
        for r in range(info_at, info_at + info_size - RECORD + 1, RECORD):
            out.append(Texture(buf, r, base))
    return out


# ---- the swizzle -------------------------------------------------------------------------------------------------------------

_maps = {}


def _swizzle_map(bpp, w, h):
    """For each texel in raster order, where the GS keeps it: a byte offset (8 bpp) or a nibble offset (4 bpp)."""
    key = (bpp, w, h)
    if key in _maps:
        return _maps[key]
    y, x = np.mgrid[0:h, 0:w]
    if bpp == 8:
        page_y, py = y >> 6, y & 63
        block_y, cy = py >> 4, py & 15
        col = cy >> 2
        swap = ((cy >> 1) & 1) ^ (col & 1)
        base = page_y * 64 * w + block_y * 16 * w + col * 4 * w + (cy & 1) * 2 * w + ((cy >> 1) & 1)
        page_x, px = x >> 7, x & 127
        block_x, cx = px >> 4, px & 15
        m = (base + page_x * 256 + block_x * 32 + ((cx >> 3) & 1) * 2 + (cx & 1) * 4 + ((cx >> 1) & 1) * 8
             + (((cx >> 2) & 1) ^ swap) * 16)
    else:
        page_y, py = y >> 7, y & 127
        block_y, cy = py >> 4, py & 15
        col = cy >> 2
        swap = ((cy >> 1) & 1) ^ (col & 1)
        base = page_y * 128 * w + col * 8 * w + (cy & 1) * 4 * w + block_y * 64 + ((cy >> 1) & 1)
        page_x, px = x >> 7, x & 127
        block_x, cx = px >> 5, px & 31
        m = (base + page_x * 512 + block_x * 32 * w + ((cx >> 3) & 1) * 2 + ((cx >> 4) & 1) * 4 + (cx & 1) * 8
             + ((cx >> 1) & 1) * 16 + (((cx >> 2) & 1) ^ swap) * 32)
    m = m.reshape(-1)
    _maps[key] = m
    return m


def _swizzle_closes(w, h, bpp):
    return w % 128 == 0 and h % (64 if bpp == 8 else 128) == 0


def _clut_order(entries, bpp):
    """The stored index of each palette index: PSMT8 CLUTs are in CSM1 order (8..15 and 16..23 of each 32 swapped)."""
    i = np.arange(entries)
    if bpp != 8:
        return i
    j = np.where(np.isin(i & 0x18, (0x08, 0x10)), i ^ 0x18, i)
    return np.where(j < entries, j, i)


# ---- decode ------------------------------------------------------------------------------------------------------------------

def palette(t, buf):
    """The CLUT in palette order, (entries, 4) GS bytes."""
    raw = np.frombuffer(buf, np.uint8, t.palette_size, t.base + t.palette_at).reshape(-1, 4)
    return raw[_clut_order(len(raw), t.bpp)]


def indices(t, buf, level=0):
    """A level's palette indices in raster order."""
    for lvl, w, h, off, n in t.mips():
        if lvl == level:
            break
    else:
        return None
    px = np.frombuffer(buf, np.uint8, n, t.base + off)
    sw = level < len(t.swizzled) and t.swizzled[level] and _swizzle_closes(w, h, t.bpp)
    if t.bpp == 8:
        return (px[_swizzle_map(8, w, h)] if sw else px.copy()).reshape(h, w)
    nib = np.empty(w * h, np.uint8)
    nib[0::2], nib[1::2] = px & 15, px >> 4
    return (nib[_swizzle_map(4, w, h)] if sw else nib).reshape(h, w)


def decode(t, buf, level=0):
    """(h, w, 4) RGBA with the alpha doubled, or None."""
    if t.parent or t.width == 0 or t.height == 0:
        return None
    if t.bpp == 32:
        for lvl, w, h, off, n in t.mips():
            if lvl == level:
                px = np.frombuffer(buf, np.uint8, n, t.base + off).reshape(h, w, 4).copy()
                px[..., 3] = np.minimum(255, px[..., 3].astype(np.int32) * 2)
                return px
        return None
    if t.bpp not in (4, 8):
        return None
    pal = palette(t, buf).astype(np.int32)
    idx = indices(t, buf, level)
    idx = np.where(idx < len(pal), idx, 0)
    out = pal[idx].copy()
    out[..., 3] = np.minimum(255, out[..., 3] * 2)
    return out.astype(np.uint8)


# ---- encode ------------------------------------------------------------------------------------------------------------------

def _to_gs_alpha(a):
    a = a.astype(np.int32)
    return np.where(a >= 255, 128, a // 2).astype(np.uint8)


def _nearest(colors, pal):
    """Palette index of each colour (n, 4) by squared distance in RGBA."""
    out = np.empty(len(colors), np.int64)
    p = pal.astype(np.int64)
    for i in range(0, len(colors), 65536):
        c = colors[i:i + 65536].astype(np.int64)
        d = ((c[:, None, :] - p[None, :, :]) ** 2).sum(-1)
        out[i:i + 65536] = d.argmin(1)
    return out


def _quantize(rgba_gs, entries):
    """A palette of `entries` colours for an (n, 4) image of GS colours, and each pixel's index."""
    uniq, inv = np.unique(rgba_gs, axis=0, return_inverse=True)
    if len(uniq) <= entries:
        pal = np.zeros((entries, 4), np.uint8)
        pal[:len(uniq)] = uniq
        return pal, inv.reshape(-1)
    from PIL import Image
    img = Image.fromarray(rgba_gs.reshape(1, -1, 4).astype(np.uint8), "RGBA")
    q = img.quantize(colors=entries, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    pal = np.array(q.getpalette(rawmode="RGBA")[:entries * 4], np.uint8).reshape(-1, 4)
    if len(pal) < entries:
        pal = np.vstack([pal, np.zeros((entries - len(pal), 4), np.uint8)])
    return pal, _nearest(rgba_gs, pal)


def _levels(rgba, t):
    from PIL import Image
    img = Image.fromarray(rgba, "RGBA")
    out = [rgba]
    for lvl, w, h, off, n in t.mips():
        if lvl:
            out.append(np.array(img.resize((w, h), Image.Resampling.BOX)))
    return out


def encode_into(buf, t, rgba):
    """Write an (h, w, 4) PNG-alpha picture into texture t of the bytearray buf, its size and format unchanged.

    Answers what was done: "unchanged", "palette kept" or "new palette".
    """
    if t.parent:
        raise ValueError("%s borrows its pixels from another texture (hash %08x): change that one" % (t.name, t.parent))
    if rgba.shape[:2] != (t.height, t.width):
        raise ValueError("%s is %dx%d, the picture %dx%d" % (t.name, t.width, t.height, rgba.shape[1], rgba.shape[0]))
    old = decode(t, buf)
    if old is not None and np.array_equal(old, rgba):
        return "unchanged"
    levels = _levels(rgba, t)
    if t.bpp == 32:
        for (lvl, w, h, off, n), img in zip(t.mips(), levels):
            px = img.copy()
            px[..., 3] = _to_gs_alpha(px[..., 3])
            buf[t.base + off:t.base + off + n] = px.tobytes()
        return "new pixels"
    entries = len(palette(t, buf))
    gs = [np.concatenate([l[..., :3], _to_gs_alpha(l[..., 3])[..., None]], -1).reshape(-1, 4) for l in levels]
    pal_old = palette(t, buf)
    # a picture made only of the palette's colours keeps the palette, so a touched-up export stays exact
    kept = set(map(bytes, pal_old))
    if all(bytes(c) in kept for c in np.unique(gs[0], axis=0)):
        pal, how = pal_old, "palette kept"
        idx0 = _nearest(gs[0], pal)
    else:
        pal, idx0 = _quantize(gs[0], entries)
        how = "new palette"
    idxs = [idx0] + [_nearest(g, pal) for g in gs[1:]]
    for (lvl, w, h, off, n), idx in zip(t.mips(), idxs):
        idx = idx.astype(np.uint8)
        sw = lvl < len(t.swizzled) and t.swizzled[lvl] and _swizzle_closes(w, h, t.bpp)
        if t.bpp == 8:
            px = np.empty(w * h, np.uint8)
            if sw:
                px[_swizzle_map(8, w, h)] = idx
            else:
                px[:] = idx
        else:
            nib = np.empty(w * h, np.uint8)
            if sw:
                nib[_swizzle_map(4, w, h)] = idx
            else:
                nib[:] = idx
            px = (nib[0::2] & 15) | (nib[1::2] << 4)
        buf[t.base + off:t.base + off + n] = px.tobytes()
    stored = np.empty_like(pal)
    stored[_clut_order(len(pal), t.bpp)] = pal
    buf[t.base + t.palette_at:t.base + t.palette_at + t.palette_size] = stored.tobytes()
    return how


def write_png(path, rgba):
    from PIL import Image
    Image.fromarray(rgba, "RGBA").save(path)


def read_png(path):
    from PIL import Image
    return np.array(Image.open(path).convert("RGBA"))
