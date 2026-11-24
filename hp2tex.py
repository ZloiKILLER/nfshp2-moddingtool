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
    _write_indexed(buf, t, pal, idxs)
    return how


def _write_indexed(buf, t, pal, idxs):
    """A paletted texture's levels (palette indices in raster order, one array a level) and its palette, written."""
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


# ---- a new size ----------------------------------------------------------------------------------------------------------
#
# A texture's pixels are a range of its pack's blob ([ImagePlacement, + ImageSize]), and that is all the game reads of
# them: LoaderTexturePack points at it, and the streamed packs (CARS\TEXTURES, GLOBAL\HUDTEX, GLOBAL\DYNTEX) read just
# that range from the file when a texture is asked for. So a texture of another size gets its pixels at the end of the
# blob, and its record the fields that follow from the size. The old pixels stay where they were, unread. The table does
# not move, and it stays inside the first 128 KB that LoadTextureTableFromFile reads.

# a 256-byte block's number in its page, by block row and column, as the GS arranges them
_B32 = [[0, 1, 4, 5, 16, 17, 20, 21], [2, 3, 6, 7, 18, 19, 22, 23], [8, 9, 12, 13, 24, 25, 28, 29],
        [10, 11, 14, 15, 26, 27, 30, 31]]
_B4 = [[0, 2, 8, 10], [1, 3, 9, 11], [4, 6, 12, 14], [5, 7, 13, 15], [16, 18, 24, 26], [17, 19, 25, 27],
       [20, 22, 28, 30], [21, 23, 29, 31]]
_GEOM = {32: (64, 32, 8, 8, _B32), 8: (128, 64, 16, 16, _B32), 4: (128, 128, 32, 16, _B4)}   # page, block, table

MAX_SIDE = 2048             # what the port's renderer takes; the PS2's GS took 1024
# The most GS memory one texture may take, in 256-byte blocks (ImageVramBlocksRequired): the disc's largest, SPLASH_SCREEN
# (512 x 256, 32-bit). Past it the game does not cope: a 911 skin made 1024 x 640 at 8 bits (2560 blocks) made the car
# select build more than 64 MB of lists in one frame and stop, on the colour that shows it (2026-11-23). The game's
# texture memory manager is where the limit is; the tool keeps to what the disc itself uses.
MAX_VRAM_BLOCKS = 2048


def vram_blocks(bpp, w, h):
    """The 256-byte GS blocks a level takes: whole pages but the last, and in the last page up to its highest block
    (ImageVramBlocksRequired is their sum over the levels: so on 12314 of the disc's 12367 textures)."""
    pw, ph, bw, bh, table = _GEOM[bpp]
    npw, nph = -(-w // pw), -(-h // ph)
    lw, lh = w - (npw - 1) * pw, h - (nph - 1) * ph
    top = max(table[r][c] for r in range(-(-lh // bh)) for c in range(-(-lw // bw)))
    return (npw * nph - 1) * 32 + top + 1


def buffer_width(bpp, w):
    """TBW, the buffer width in 64s: even and at least 2 for the palette modes (every level on the disc has it so)."""
    b = -(-w // 64)
    return max(2, b + (b & 1)) if bpp in (4, 8) else max(1, b)


def _containing(buf, at, off=0, end=None):
    """The headers of the containers that hold the chunk at `at`, outermost first, and that chunk's own header."""
    end = len(buf) if end is None else end
    for cid, o, s in _chunks(buf, off, end):
        if o == at:
            return [o]
        if o < at < o + 8 + s and cid & 0x80000000:
            return [o] + _containing(buf, at, o + 8, o + 8 + s)
    return []


PSM = {4: 0x14, 8: 0x13, 32: 0x00}


class TooBig(ValueError):
    """A size and depth that would take more of the GS's memory than the game copes with (MAX_VRAM_BLOCKS)."""


def fits(t, w, h, bpp=None):
    """Whether texture t may become w x h (at bpp, or its own depth) without passing MAX_VRAM_BLOCKS."""
    bpp = bpp or t.bpp
    levels = max(1, min(t.levels, min(w, h).bit_length()))
    return sum(vram_blocks(bpp, max(1, w >> l), max(1, h >> l)) for l in range(levels)) <= MAX_VRAM_BLOCKS


def resize(buf, t, w, h, bpp=None):
    """The file `buf` (bytes) with texture t made w x h, and with bpp 8 a 4-bit texture made 8-bit (256 colours in place of
    16): its number of levels kept (as many as the new size has room for), its pixels at the end of its pack's blob,
    cleared, and with a new depth its palette and those of the textures that borrow its pixels there too, cleared. Its
    record and those textures' get the new size. Everything after the blob moves by a multiple of 2048 bytes, so every
    chunk after it keeps its alignment. Answers the new bytes; write the picture with encode_into (or all of it with
    replace) after reading the textures again."""
    if t.parent:
        raise ValueError("%s borrows its pixels from another texture (hash %08x): change that one" % (t.name, t.parent))
    if t.bpp not in _GEOM:
        raise ValueError("%s: %d bits a texel" % (t.name, t.bpp))
    bpp = bpp or t.bpp
    if bpp != t.bpp and not (t.bpp == 4 and bpp == 8):
        raise ValueError("%s: %d bits a texel cannot become %d" % (t.name, t.bpp, bpp))
    if not (8 <= w <= MAX_SIDE and 8 <= h <= MAX_SIDE) or w % 2:
        raise ValueError("%dx%d: a side from 8 to %d, the width even" % (w, h, MAX_SIDE))
    buf = bytearray(buf)
    # the pack's blob
    pack = next((o, s) for o, s in find_packs(buf) if o < t.rec_at < o + 8 + s)
    data = next(o for cid, o, s in _chunks(buf, pack[0] + 8, pack[0] + 8 + pack[1]) if cid == PACK_DATA)
    size, = struct.unpack_from("<I", buf, data + 4)
    blob_end = data + 8 + size
    base = t.base
    # the levels and where the pixels go, and the palettes when the depth changes
    levels = max(1, min(t.levels, min(w, h).bit_length()))
    sizes = [(max(1, w >> l), max(1, h >> l)) for l in range(levels)]
    need = sum(vram_blocks(bpp, lw, lh) for lw, lh in sizes)
    if need > MAX_VRAM_BLOCKS:
        raise TooBig("%s at %dx%d, %d-bit takes %d blocks of the GS's memory; the game copes with %d at most (the "
                     "disc's largest texture). Make the picture smaller%s." % (
                         t.name, w, h, bpp, need, MAX_VRAM_BLOCKS, " or keep 16 colours" if bpp == 8 and t.bpp == 4
                         else ""))
    nbytes = sum(lw * lh * bpp // 8 for lw, lh in sizes)
    place = (blob_end - base + 127) & ~127
    end = place + nbytes
    kids = [o for o in read_textures(buf) if o.parent == t.hash]
    pals = {}
    if bpp != t.bpp:
        for o in [t] + [k for k in kids if k.palette_size]:
            pals[o.rec_at] = (end + 127) & ~127
            end = pals[o.rec_at] + 1024
    grow = base + end - blob_end
    grow += (-grow) % 2048
    buf[blob_end:blob_end] = bytes(grow)
    for hdr in _containing(buf, data):
        struct.pack_into("<I", buf, hdr + 4, struct.unpack_from("<I", buf, hdr + 4)[0] + grow)
    # the record
    r = t.rec_at
    if bpp != t.bpp:
        buf[r + 0x28] = bpp
        struct.pack_into("<HH", buf, r + 0x2A, 256, 4)          # NumPaletteEntries, PaletteVramBlocksRequired
        buf[r + 0x4A] = PSM[bpp]
    struct.pack_into("<2H", buf, r + 0x24, w, h)
    struct.pack_into("<H", buf, r + 0x2E, sum(vram_blocks(bpp, lw, lh) for lw, lh in sizes))
    struct.pack_into("<I", buf, r + 0x30, place)
    struct.pack_into("<I", buf, r + 0x38, nbytes)
    struct.pack_into("<I", buf, r + 0x44, nbytes)
    buf[r + 0x48] = max(0, (w - 1).bit_length())
    buf[r + 0x49] = max(0, (h - 1).bit_length())
    blocks = 0
    for l in range(7):
        e = r + 0x52 + 4 * l
        if l < levels:
            lw, lh = sizes[l]
            struct.pack_into("<HBb", buf, e, blocks, buffer_width(bpp, lw),
                             1 if bpp != 32 and _swizzle_closes(lw, lh, bpp) else 0)
            blocks += vram_blocks(bpp, lw, lh)
        else:
            struct.pack_into("<HBb", buf, e, 0, 0, 0)
    struct.pack_into("<b", buf, r + 0x6E, levels - 1)
    # the textures that show these pixels under another name take the same size
    for o in read_textures(buf):
        if o.parent == t.hash:
            buf[o.rec_at + 0x24:o.rec_at + 0x30] = buf[r + 0x24:r + 0x30]
            buf[o.rec_at + 0x38:o.rec_at + 0x3C] = buf[r + 0x38:r + 0x3C]
            buf[o.rec_at + 0x44:o.rec_at + 0x4B] = buf[r + 0x44:r + 0x4B]
            buf[o.rec_at + 0x52:o.rec_at + 0x6F] = buf[r + 0x52:r + 0x6F]
            if not o.palette_size:
                struct.pack_into("<HH", buf, o.rec_at + 0x2A, 0, 0)
    for rec, at in pals.items():
        struct.pack_into("<I", buf, rec + 0x34, at)
        struct.pack_into("<I", buf, rec + 0x3C, 1024)
        buf[rec + 0x4A] = PSM[bpp]
    return bytes(buf)


def replace(buf, t, rgba, bpp=None):
    """The file `buf` with texture t's picture made rgba (h, w, 4, PNG alpha), of any size (and with bpp 8 a 4-bit texture
    made 8-bit). The textures that show t's pixels under another name keep their colours: a copy of t's palette becomes
    the new one, and a palette of their own (a dash or a wheel in other colours) is laid on the new indices by the
    picture. Answers (new bytes, what was done)."""
    if t.parent:
        raise ValueError("%s borrows its pixels from another texture (hash %08x): change that one" % (t.name, t.parent))
    h, w = rgba.shape[:2]
    paletted = t.bpp in (4, 8)
    old_idx = indices(t, buf) if paletted else None
    old_pal = palette(t, buf) if paletted else None
    kids = []
    for k in read_textures(buf):
        if k.parent == t.hash and k.palette_size and paletted:
            kp = palette(k, buf)
            kids.append((k.hash, "copy" if np.array_equal(kp, old_pal[:len(kp)]) else "own", kp))
    resized = (w, h) != (t.width, t.height) or (bpp or t.bpp) != t.bpp
    out = bytearray(resize(buf, t, w, h, bpp) if resized else buf)
    t2 = next(x for x in read_textures(out) if x.rec_at == t.rec_at)
    own = [kp for _, kind, kp in kids if kind == "own"]
    if not kids or not paletted:
        how = encode_into(out, t2, rgba)
    else:
        how = _encode_with_kids(out, t2, rgba, old_idx, old_pal, kids)
    if resized:
        how = "now %dx%d, %d-bit: %s" % (w, h, t2.bpp, how)
    if kids and paletted:
        how += "; %d textures sharing its pixels keep their colours%s" % (
            len(kids), " (%d with colours of their own)" % len(own) if own else "")
    return bytes(out), how


def _encode_with_kids(out, t, rgba, old_idx, old_pal, kids):
    """encode_into for a texture whose pixels others show with palettes of their own. The old indices where any of those
    palettes differs from t's (a dash's colour patch, a wheel's tint) keep an entry each in the new palette, for the pixels
    that had them, so every such texture keeps its own colour there; the rest of the picture takes the other entries.
    Then every such palette is made again over the new indices."""
    from PIL import Image
    h, w = rgba.shape[:2]
    if old_idx.shape != (h, w):
        old_idx = np.array(Image.fromarray(old_idx.astype(np.uint8), "L").resize((w, h), Image.Resampling.NEAREST))
    entries = len(palette(t, out))
    differs = set()
    for _, kind, kp in kids:
        if kind == "own":
            for o in range(min(len(kp), len(old_pal))):
                if not np.array_equal(kp[o], old_pal[o]):
                    differs.add(o)
    present = set(np.unique(old_idx).tolist())
    keep = sorted(o for o in differs if o in present)[:max(0, entries // 2)]
    levels = _levels(rgba, t)
    gs = [np.concatenate([l[..., :3], _to_gs_alpha(l[..., 3])[..., None]], -1).reshape(-1, 4) for l in levels]
    flat_old = old_idx.reshape(-1)
    mask = np.isin(flat_old, keep)
    pal = np.zeros((entries, 4), np.uint8)
    rest = entries - len(keep)
    if (~mask).any():
        p, idx_rest = _quantize(gs[0][~mask], rest)
        pal[:rest] = p[:rest]
    idx0 = np.zeros(len(flat_old), np.int64)
    if (~mask).any():
        idx0[~mask] = idx_rest
    slot = {}
    for j, o in enumerate(keep):
        e = rest + j
        slot[o] = e
        m = flat_old == o
        pal[e] = np.round(gs[0][m].astype(np.float64).mean(0)).astype(np.uint8)
        idx0[m] = e
    idxs = [idx0]
    for lvl_img, (lvl, lw, lh, _, _) in zip(gs[1:], list(t.mips())[1:]):
        o_l = np.array(Image.fromarray(old_idx.astype(np.uint8), "L").resize((lw, lh), Image.Resampling.NEAREST))
        o_l = o_l.reshape(-1)
        idx = _nearest(lvl_img, pal[:rest]) if rest else np.zeros(len(lvl_img), np.int64)
        for o, e in slot.items():
            idx[o_l == o] = e
        idxs.append(idx)
    _write_indexed(out, t, pal, idxs)
    # every borrowing texture's palette over the new indices: the new palette, with its own colour at each kept index
    # (elsewhere its palette was t's own colours, and those are the picture's now)
    by_hash = {x.hash: x for x in read_textures(out)}
    for hsh, kind, kp in kids:
        k = by_hash[hsh]
        kpal = pal.copy()
        if kind == "own":
            for o, e in slot.items():
                if o < len(kp):
                    kpal[e] = kp[o]
        stored = np.zeros((k.palette_size // 4, 4), np.uint8)
        stored[_clut_order(len(stored), k.bpp)] = kpal[:len(stored)]
        out[k.base + k.palette_at:k.base + k.palette_at + k.palette_size] = stored.tobytes()
    return "new palette, %d colours kept for the textures that share it" % len(keep) if keep else "new palette"


def write_png(path, rgba):
    from PIL import Image
    Image.fromarray(rgba, "RGBA").save(path)


def read_png(path):
    from PIL import Image
    return np.array(Image.open(path).convert("RGBA"))
