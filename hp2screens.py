"""The menus' screens ("Flailer"): FRONTEND\\FRONTB.BUN, GLOBAL\\GLOBALB.BUN and GLOBAL\\INGAMEB.BUN, chunk 0x80010200.

A screen (0x80010201) is a header (0x10203: +8 name hash, +24/26 640x480, +28 the number of objects) and its objects:
pictures (0x10210, 144 bytes) and texts (0x10212, 100 bytes and MaxChars). Every object (docs flailer-ui.md "Retail"):
+8 name hash, +12 group hash, +16 char[24] name, +40 s8 type (1 text, 2 picture), +41 visible, +42 layer 0..28, +48 x,
+52 y (640x480), +56 scale x, +60 scale y, +64 rotation, +68 animation. A picture: +80 texture hash, +88 four corner
colours, +112 eight UV floats; it is drawn texture width x scale x by height x scale y. A text: +80 font hash, +84 MaxChars,
+88 format (1 right, 2 left, 4 centred, 8 dark box, 0x10 clip, 0x20 wrap, 0x40 fixed width), +92 colour, +96 text id
(0: the text at +100). Colours are bytes R, G, B, A with 0x80 as full. Layers draw back to front 24..20, 15..0, 19..16,
28..25. Fonts are chunks 0x15010: the sheet's hash, the glyphs (char, x, y, w, h, advance, offset in the sheet), kerning.

Everything is changed in place: no field changes size, so the files keep theirs. Slides, blurbs and the drifting
background are the game's code; objects it moves are placed by the code whatever their numbers say.
"""

import os
import struct

import numpy as np

import hp2core as core
import hp2tex as tex

FLAILER = 0x80010200
SCREEN = 0x80010201
SCREEN_HEAD = 0x00010203
BITMAP = 0x00010210
TEXT = 0x00010212
FONT = 0x00015010

FILES = ("FRONTEND/FRONTB.BUN", "GLOBAL/GLOBALB.BUN", "GLOBAL/INGAMEB.BUN")
PICTURE_FILES = ("FRONTEND/FRONTB.BUN", "GLOBAL/GLOBALB.BUN", "GLOBAL/INGAMEB.BUN", "FRONTEND/TSELECT.tex",
                 "GLOBAL/DYNTEX.tex", "GLOBAL/HUDTEX.tex")
LAYER_ORDER = list(range(24, 19, -1)) + list(range(15, -1, -1)) + list(range(19, 15, -1)) + list(range(28, 24, -1))

SCREEN_NAMES = {
    0xae0f8aa1: "NEW_MAIN_MENU", 0x5b35f533: "COPS_ON_MODE_SELECT", 0x033e7771: "COPS_OFF_MODE_SELECT",
    0xb5074ab4: "SELECT_CAR", 0x15417b53: "SELECT_TRACK", 0x2d62cfe2: "CHALLENGE", 0xb5761d00: "TITLE_SCREEN",
    0x95ad096b: "OPTIONS", 0x8bc68340: "DISPLAY_OPTIONS", 0xe116761c: "AUDIO_OPTIONS", 0x617a4e0a: "USERNAME_OPTIONS",
    0x632b068e: "LANGUAGE_OPTIONS", 0x8bd5060b: "JOYSTICK_PRECONFIG", 0x037f3133: "POPUP", 0x41c2fdc3: "SELECT_CAR_DIALOG",
    0xe55f1297: "CHALLENGE_BE_A_COP", 0xd1eadbca: "RACE_SETUP", 0x18dc8e52: "SELECT_CAR_2P", 0x28891a22: "CUSTOMIZE_HUD",
    0xb6657464: "JOYSTICK_CONFIG", 0xa4031ef6: "JOYSTICK_CALIBRATION", 0xddf09124: "CALIBRATE_DISPLAY",
    0x7ab428c1: "CALIBRATE_DISPLAY_OFFSET", 0x95b2b627: "JUKEBOX",
    # the port's own pages (pcmenu.cpp: the page's name upper case, spaces as _)
    0x1589cfa8: "PC_LANGUAGES (port)", 0xff14bf35: "PC_PROFILES (port)", 0x90d06622: "PC_GRAPHICS (port)",
    0xa282ac05: "PC_RESOLUTION (port)", 0x01862ce7: "PC_ADVANCED (port)", 0x113f3365: "PC_ANTIALIASING (port)",
    0x177b6505: "PC_CONTROLS (port)", 0x9024d262: "PC_KEYBOARD (port)", 0x11e4d6af: "PC_PLAYER_2 (port)",
    0xc102edc3: "PC_KEYBOARD_P2 (port)", 0xdd8ef420: "PC_GAMEPAD (port)",
}

FORMAT_BITS = ((1, "right"), (2, "left"), (4, "centred"), (8, "dark box"), (0x10, "clip"), (0x20, "wrap"),
               (0x40, "fixed width"))


class Obj:
    """One object; `at` is its payload's offset in the file, the fields are read from and written to the buffer."""

    def __init__(self, buf, at, kind, size):
        self.buf, self.at, self.kind, self.size = buf, at, kind, size

    def _get(self, off, fmt):
        return struct.unpack_from("<" + fmt, self.buf, self.at + off)[0]

    def _set(self, off, fmt, v):
        struct.pack_into("<" + fmt, self.buf, self.at + off, v)

    name = property(lambda s: bytes(s.buf[s.at + 16:s.at + 40]).split(b"\0")[0].decode("latin-1"))
    is_text = property(lambda s: s.kind == TEXT)
    x = property(lambda s: s._get(48, "f"), lambda s, v: s._set(48, "f", float(v)))
    y = property(lambda s: s._get(52, "f"), lambda s, v: s._set(52, "f", float(v)))
    scale_x = property(lambda s: s._get(56, "f"), lambda s, v: s._set(56, "f", float(v)))
    scale_y = property(lambda s: s._get(60, "f"), lambda s, v: s._set(60, "f", float(v)))
    visible = property(lambda s: s._get(41, "b"), lambda s, v: s._set(41, "b", int(v)))
    layer = property(lambda s: s._get(42, "b"), lambda s, v: s._set(42, "b", int(v)))
    rotation = property(lambda s: s._get(64, "i"), lambda s, v: s._set(64, "i", int(v)))
    animation = property(lambda s: s._get(68, "i"))
    # pictures
    texture = property(lambda s: s._get(80, "I"), lambda s, v: s._set(80, "I", int(v)))

    def colours(self):
        return [self._get(88 + 4 * i, "I") for i in range(4)]

    def set_colours(self, cs):
        for i, c in enumerate(cs):
            self._set(88 + 4 * i, "I", int(c))

    def uvs(self):
        return [self._get(112 + 4 * i, "f") for i in range(8)]

    # texts
    font = property(lambda s: s._get(80, "I"), lambda s, v: s._set(80, "I", int(v)))
    max_chars = property(lambda s: s._get(84, "I"))
    format = property(lambda s: s._get(88, "I"), lambda s, v: s._set(88, "I", int(v)))
    colour = property(lambda s: s._get(92, "I"), lambda s, v: s._set(92, "I", int(v)))
    text_id = property(lambda s: s._get(96, "i"), lambda s, v: s._set(96, "i", int(v)))

    @property
    def inline(self):
        n = min(self.max_chars, self.size - 100)
        return bytes(self.buf[self.at + 100:self.at + 100 + n]).split(b"\0")[0]

    def set_inline(self, b):
        n = min(self.max_chars, self.size - 100)
        if len(b) >= n:
            raise ValueError("%s holds %d characters" % (self.name, n - 1))
        self.buf[self.at + 100:self.at + 100 + n] = b + bytes(n - len(b))


class Screen:
    def __init__(self, file, hash_, objects):
        self.file, self.hash, self.objects = file, hash_, objects

    @property
    def name(self):
        return SCREEN_NAMES.get(self.hash, "SCREEN_%08X" % self.hash)


def read_screens(rel, buf):
    """[Screen] of a file's Flailer project; the objects read and write `buf` (a bytearray)."""
    out = []
    for cid, off, size in core.chunks(buf):
        if cid != FLAILER:
            continue
        for c2, o2, s2 in core.chunks(buf, off + 8, off + 8 + size):
            if c2 != SCREEN:
                continue
            h, objs = 0, []
            for c3, o3, s3 in core.chunks(buf, o2 + 8, o2 + 8 + s2):
                if c3 == SCREEN_HEAD:
                    h = struct.unpack_from("<I", buf, o3 + 16)[0]
                elif c3 in (BITMAP, TEXT):
                    objs.append(Obj(buf, o3 + 8, c3, s3))
            out.append(Screen(rel, h, objs))
    return out


# ---- fonts and pictures -------------------------------------------------------------------------------------------------

class Font:
    def __init__(self, sheet, glyphs):
        self.sheet, self.glyphs = sheet, glyphs
        self.height = max((g[3] for g in glyphs.values()), default=16)


def read_fonts(buf):
    out = {}
    for cid, off, size in core.chunks(buf):
        if cid != FONT:
            continue
        p = off + 8
        h, n, nk, goff, koff = struct.unpack_from("<IIIII", buf, p)
        glyphs = {}
        for i in range(n):
            g = off + goff + 32 * i
            ch, _ = struct.unpack_from("<HH", buf, g)
            x, y, w, hh, adv, ofs = struct.unpack_from("<6f", buf, g + 4)
            glyphs[ch] = (x, y, w, hh, adv, ofs)
        out[h] = Font(h, glyphs)
    return out


class Library:
    """The pictures, fonts and texts a screen draws with, from all the menu files."""

    def __init__(self, data, lang="ENGLISH"):
        import hp2text
        self.data = data
        self.packs = {}
        self.fonts = {}
        self.names = {}
        for rel in PICTURE_FILES:
            p = os.path.join(data, rel)
            if not os.path.isfile(p):
                continue
            buf = open(p, "rb").read()
            for t in tex.read_textures(buf):
                self.packs.setdefault(t.hash, (t, buf))
                self.names.setdefault(t.hash, t.name)
            if rel.endswith(".BUN"):
                self.fonts.update(read_fonts(buf))
        self.cache = {}
        try:
            lf = hp2text.load_all(data).get(lang)
            self.texts = lf.texts if lf else {}
        except Exception:
            self.texts = {}

    def picture(self, h):
        if h in self.cache:
            return self.cache[h]
        img = None
        hit = self.packs.get(h)
        if hit is not None:
            t, buf = hit
            if t.parent and t.parent in self.packs:
                t, buf = self.packs[t.parent]
            img = tex.decode(t, buf)
        self.cache[h] = img
        return img

    def size(self, h):
        hit = self.packs.get(h)
        return (hit[0].width, hit[0].height) if hit else None


def _rgba(c):
    """A colour word as 0..1 factors (0x80 is 1)."""
    return [min(2.0, ((c >> s) & 255) / 128.0) for s in (0, 8, 16, 24)]


def text_of(o, lib):
    if o.text_id:
        b = lib.texts.get(o.text_id)
        if b is not None:
            return b
    return o.inline


def object_box(o, lib):
    """(x0, y0, x1, y1) of an object on the 640x480 screen, as near as the data says."""
    if not o.is_text:
        sz = lib.size(o.texture) or (16, 16)
        return o.x, o.y, o.x + sz[0] * o.scale_x, o.y + sz[1] * o.scale_y
    f = lib.fonts.get(o.font)
    s = text_of(o, lib)
    lines = s.split(b"@") if s else [b""]
    if f is None:
        w = max(len(l) for l in lines) * 8 * o.scale_x
        hh = 12 * o.scale_y * len(lines)
    else:
        w = max(sum(f.glyphs.get(c, (0, 0, 0, 0, 8, 0))[4] for c in l) for l in lines) * o.scale_x
        hh = f.height * o.scale_y * len(lines)
    x0 = o.x
    if o.format & 1:
        x0 = o.x - w
    elif o.format & 4:
        x0 = o.x - w / 2
    return x0, o.y, x0 + w, o.y + hh


def render(screen, lib, scale=1.0, hidden=False):
    """The screen drawn with PIL at 640x480 (times scale): pictures with their UVs and corner colour, texts with the game's
    fonts. Rotation and the code's animation are not drawn."""
    from PIL import Image
    W, H = int(640 * scale), int(480 * scale)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    order = {l: i for i, l in enumerate(LAYER_ORDER)}
    objs = sorted(enumerate(screen.objects), key=lambda e: (order.get(e[1].layer, 99), e[0]))
    for _, o in objs:
        if not o.visible and not hidden:
            continue
        try:
            if o.is_text:
                _draw_text(canvas, o, lib, scale)
            else:
                _draw_picture(canvas, o, lib, scale)
        except Exception:      # a picture that will not draw is left out of the preview
            pass
    return canvas


def _draw_picture(canvas, o, lib, scale):
    from PIL import Image
    img = lib.picture(o.texture)
    if img is None:
        return
    h, w = img.shape[:2]
    uv = o.uvs()
    us, vs = uv[0::2], uv[1::2]
    u0, u1 = max(0.0, min(us)), min(1.0, max(us))
    v0, v1 = max(0.0, min(vs)), min(1.0, max(vs))
    crop = img[int(v0 * h):max(int(v0 * h) + 1, int(round(v1 * h))), int(u0 * w):max(int(u0 * w) + 1,
                                                                                      int(round(u1 * w)))]
    if us[0] > us[1]:
        crop = crop[:, ::-1]
    if vs[0] > vs[3]:
        crop = crop[::-1]
    dw, dh = int(w * o.scale_x * scale), int(h * o.scale_y * scale)
    if dw <= 0 or dh <= 0 or dw > 8000 or dh > 8000:
        return
    k = _rgba(o.colours()[0])
    c = crop.astype(np.float32) * np.array(k, np.float32)
    pic = Image.fromarray(np.clip(c, 0, 255).astype(np.uint8), "RGBA").resize((dw, dh))
    canvas.alpha_composite(pic, (int(o.x * scale), int(o.y * scale))) if _inside(canvas, o, scale, dw, dh) else \
        _paste_clipped(canvas, pic, int(o.x * scale), int(o.y * scale))


def _inside(canvas, o, scale, dw, dh):
    x, y = int(o.x * scale), int(o.y * scale)
    return x >= 0 and y >= 0 and x + dw <= canvas.width and y + dh <= canvas.height


def _paste_clipped(canvas, pic, x, y):
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(canvas.width, x + pic.width), min(canvas.height, y + pic.height)
    if x1 <= x0 or y1 <= y0:
        return
    canvas.alpha_composite(pic.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def _draw_text(canvas, o, lib, scale):
    from PIL import Image, ImageDraw
    s = text_of(o, lib)
    if not s:
        return
    k = _rgba(o.colour)
    f = lib.fonts.get(o.font)
    sheet = lib.picture(f.sheet) if f else None
    x0, y0, x1, y1 = object_box(o, lib)
    if o.format & 8:
        d = ImageDraw.Draw(canvas)
        d.rectangle([x0 * scale, y0 * scale, x1 * scale, y1 * scale], fill=(0, 0, 0, 160))
    if f is None or sheet is None:
        d = ImageDraw.Draw(canvas)
        d.text((x0 * scale, y0 * scale), s.decode("latin-1"), fill=tuple(int(min(255, v * 255)) for v in k[:3]) + (255,))
        return
    sc_x, sc_y = o.scale_x * scale, o.scale_y * scale
    col = np.array(k, np.float32)
    y = y0 * scale
    for line in s.split(b"@"):
        lw = sum(f.glyphs.get(c, (0, 0, 0, 0, 8, 0))[4] for c in line) * sc_x
        x = (o.x * scale - lw) if o.format & 1 else (o.x * scale - lw / 2) if o.format & 4 else o.x * scale
        for c in line:
            g = f.glyphs.get(c)
            if g is None:
                x += 8 * sc_x
                continue
            gx, gy, gw, gh, adv, ofs = g
            if gw > 0 and gh > 0:
                cut = sheet[int(gy):int(gy + gh), int(gx):int(gx + gw)].astype(np.float32) * col
                gi = Image.fromarray(np.clip(cut, 0, 255).astype(np.uint8), "RGBA")
                gi = gi.resize((max(1, int(gw * sc_x)), max(1, int(gh * sc_y))))
                _paste_clipped(canvas, gi, int(x + ofs * sc_x), int(y))
            x += adv * sc_x
        y += f.height * sc_y


# ---- the menus as the port draws them: HP2_FLDUMP ----------------------------------------------------------------------

class DumpObj:
    """An object of the port's dump (pcmenu.cpp dump_project): the fields the preview draws, read only."""

    def __init__(self, f):
        self.__dict__.update(f)

    def colours(self):
        return [self.col] * 4

    def uvs(self):
        return [0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]

    @property
    def inline(self):
        return self.text


class DumpScreen:
    def __init__(self, project, hash_, objects):
        self.file, self.hash, self.objects = "port", hash_, objects

    @property
    def name(self):
        return SCREEN_NAMES.get(self.hash, "SCREEN_%08X" % self.hash)


PROJECT_FILES = {0x255842FD: "FRONTEND/FRONTB.BUN", 0xECA3270E: "GLOBAL/INGAMEB.BUN", 0xE3448A8E: "GLOBAL/GLOBALB.BUN"}


def read_dump(path):
    """{file: [DumpScreen]} of the last load of each project in an HP2_FLDUMP file."""
    import re
    out, cur, screen = {}, None, None
    line_re = re.compile(r'^  ([0-9a-f]{8}) (.{24}) (text  |bitmap|other ) vis(-?\d+) z\s*(-?\d+)\s+(\S+)\s+(\S+)\s+x(\S+) '
                         r'y(\S+) grp ([0-9a-f]{8})(.*) @([0-9a-f]{8})$')
    for raw in open(path, encoding="latin-1"):
        line = raw.rstrip("\n")
        if line.startswith("project "):
            h = int(line.split()[1], 16)
            cur = []
            out[PROJECT_FILES.get(h, "project %08x" % h)] = cur
        elif line.startswith(" screen ") and cur is not None:
            screen = DumpScreen(None, int(line.split()[1], 16), [])
            cur.append(screen)
        elif screen is not None:
            m = line_re.match(line)
            if not m:
                continue
            kind = m.group(3).strip()
            f = dict(hash=int(m.group(1), 16), name=m.group(2).strip(), is_text=kind == "text",
                     visible=int(m.group(4)), layer=int(m.group(5)), x=float(m.group(6)), y=float(m.group(7)),
                     scale_x=float(m.group(8)), scale_y=float(m.group(9)), rotation=0, animation=0,
                     texture=0, col=0x80808080, font=0, max_chars=0, format=0, colour=0x80808080, text_id=0, text=b"",
                     addr=int(m.group(12), 16))
            rest = m.group(11)
            if kind == "text":
                t = re.match(r' font ([0-9a-f]{8}) max (\d+) fmt ([0-9a-f]+) col ([0-9a-f]{8}) lang (\d+) "(.*)"$', rest)
                if t:
                    f.update(font=int(t.group(1), 16), max_chars=int(t.group(2)), format=int(t.group(3), 16),
                             colour=int(t.group(4), 16), text_id=int(t.group(5)), text=t.group(6).encode("latin-1"))
            elif kind == "bitmap":
                t = re.match(r' tex ([0-9a-f]{8}) col ([0-9a-f]{8})', rest)
                if t:
                    f.update(texture=int(t.group(1), 16), col=int(t.group(2), 16))
            screen.objects.append(DumpObj(f))
    return out


def mark_port_objects(dump_screens, file_screens):
    """Each dump object gets .port: "added" (not in the file's screen), "moved" or ""."""
    by_hash = {s.hash: s for s in file_screens}
    for ds in dump_screens:
        fs = by_hash.get(ds.hash)
        known = {}
        if fs is not None:
            for o in fs.objects:
                known.setdefault((struct.unpack_from("<I", o.buf, o.at + 8)[0], o.name), []).append(o)
        for o in ds.objects:
            cands = known.get((o.hash, o.name), [])
            if not cands:
                o.port = "added"
            elif any(abs(c.x - o.x) < 0.5 and abs(c.y - o.y) < 0.5 for c in cands):
                o.port = ""
            else:
                o.port = "moved"
