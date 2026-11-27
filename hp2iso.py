"""A disc image of the game built from the installed game's data (Experimental): the original image gives everything but
the archive, the archive (NFSHP2\\ZZDATA.BIN and its directory ZDIR.BIN) is made again from data\\ with every change
in it. For PCSX2, OPL and a burnt disc on a PS2: what lies before the archive (the system area with the PS2 logo, the
volume descriptors, the directories, the IOP modules) is the original's byte for byte, and both file systems (ISO9660,
which the PS2 boots by, and the UDF bridge) are made to follow the archive's new size.

ZDIR: 12 bytes an entry {u32 name hash, u32 sector from the archive's start, u32 size}, in the archive's order, which is
data\\index.txt's. Files the disc keeps compressed (.LZC, a COMP container) go in plain: the game's loader unpacks only
what begins with COMP and takes anything else as it is (ResourceFile::LoadResourceIfFileTransferFinished), as the
installer's notes have it and as the Russian disc does. Entries that name the same file share its sectors.

The UDF of these discs is not exact (the archive's length is kept modulo 2^30 there); it is followed as it is: the moved
files' extents, the archive's length in the same form, the partition's length and the closing anchor."""

import os
import struct

S = 2048
ARCHIVE, DIRECTORY = "/NFSHP2/ZZDATA.BIN", "/NFSHP2/ZDIR.BIN"
DVD5 = 2295104                    # sectors of a single-layer DVD


class Image:
    """An ISO9660 image read: its files {path: [extent, size, (dir sector, offset of the record)]} and its UDF parts."""

    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        self.sectors = os.path.getsize(path) // S
        pvd = self.sec(16)
        if pvd[1:6] != b"CD001" or pvd[0] != 1:
            raise ValueError("%s is not an ISO9660 image" % path)
        self.volume, = struct.unpack_from("<I", pvd, 80)
        self.files = {}
        root = pvd[156:190]
        self._walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "/")
        self._udf()

    def sec(self, n, count=1):
        self.f.seek(n * S)
        return self.f.read(S * count)

    def read_file(self, path):
        e, s, _ = self.files[path]
        self.f.seek(e * S)
        return self.f.read(s)

    def _walk(self, extent, length, prefix):
        data = self.sec(extent, (length + S - 1) // S)
        p = 0
        while p < length:
            ln = data[p]
            if ln == 0:
                p = (p // S + 1) * S
                continue
            ext, size = struct.unpack_from("<I", data, p + 2)[0], struct.unpack_from("<I", data, p + 10)[0]
            flags, nl = data[p + 25], data[p + 32]
            name = data[p + 33:p + 33 + nl]
            if name not in (b"\0", b"\1"):
                n = name.decode("latin-1").split(";")[0]
                if flags & 2:
                    self._walk(ext, size, prefix + n + "/")
                else:
                    self.files[(prefix + n).upper()] = [ext, size, (extent + p // S, p % S)]
            p += ln

    def _udf(self):
        """The partition descriptors (main and reserve), the anchors and the file entries by the sector they point at."""
        self.udf = None
        a = self.sec(256)
        if struct.unpack_from("<H", a, 0)[0] != 2:
            return
        main_len, main_loc, res_len, res_loc = struct.unpack_from("<IIII", a, 16)
        parts = []
        part_start = None
        for loc, ln in ((main_loc, main_len), (res_loc, res_len)):
            for n in range(loc, loc + ln // S):
                d = self.sec(n)
                if struct.unpack_from("<H", d, 0)[0] == 5:
                    parts.append(n)
                    part_start = struct.unpack_from("<I", d, 188)[0]
        anchors = [k for k in (256, self.sectors - 1, self.sectors - 257)
                   if 0 <= k < self.sectors and struct.unpack_from("<H", self.sec(k), 0)[0] == 2]
        entries = {}
        if part_start is not None:
            first_file = min(e for e, _, _ in self.files.values())
            for n in range(part_start, first_file):
                d = self.sec(n)
                if struct.unpack_from("<H", d, 0)[0] != 261:
                    continue
                l_ea, l_ad = struct.unpack_from("<II", d, 168)
                if l_ad == 8:           # one short allocation descriptor
                    length, pos = struct.unpack_from("<II", d, 176 + l_ea)
                    entries[pos + part_start] = (n, 176 + l_ea)
        self.udf = {"parts": parts, "start": part_start, "anchors": anchors, "entries": entries}


def _crc(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _retag(d, location):
    """A UDF descriptor's tag made right again after a change: its location, CRC and checksum."""
    d = bytearray(d)
    struct.pack_into("<I", d, 12, location)
    crc_len, = struct.unpack_from("<H", d, 10)
    struct.pack_into("<H", d, 8, _crc(bytes(d[16:16 + crc_len])))
    d[4] = sum(d[0:4] + d[5:16]) & 0xFF
    return bytes(d)


def read_index(data):
    out = []
    for line in open(os.path.join(data, "index.txt"), encoding="latin-1"):
        p = line.strip().split(" ", 1)
        if len(p) == 2:
            try:
                out.append((int(p[0], 16), p[1]))
            except ValueError:
                pass
    return out


def plan(data, img):
    """[(hash, path or None, size)] of the new archive in ZDIR's order, and the problems found (the image is not the
    disc the game was installed from, a file is missing)."""
    index = read_index(data)
    problems = []
    zdir = img.read_file(DIRECTORY)
    disc = [struct.unpack_from("<III", zdir, i)[0] for i in range(0, len(zdir) // 12 * 12, 12)]
    if sorted(disc) != sorted(h for h, _ in index):
        problems.append("the image's archive names other files than data\\index.txt: it is not the disc the game was "
                        "installed from (%d entries against %d)" % (len(disc), len(index)))
    out = []
    for h, rel in index:
        p = os.path.join(data, *rel.split("/"))
        if not os.path.isfile(p):
            problems.append("%s is missing from data" % rel)
            continue
        out.append((h, p, os.path.getsize(p)))
    return out, problems


def build(src, data, dst, log=print):
    """dst: the image src with its archive made from data. Answers a report dict."""
    if os.path.abspath(src) == os.path.abspath(dst):
        raise ValueError("the new image must not be the original")
    img = Image(src)
    for p in (ARCHIVE, DIRECTORY):
        if p not in img.files:
            raise ValueError("%s has no %s" % (src, p))
    entries, problems = plan(data, img)
    if problems:
        raise ValueError("; ".join(problems))
    zz_ext, zz_size, zz_rec = img.files[ARCHIVE]
    zz_end_old = zz_ext + (zz_size + S - 1) // S
    after = sorted((v[0], k) for k, v in img.files.items() if v[0] >= zz_end_old)
    tail_gap = img.volume - max(e + (s + S - 1) // S for e, s, _ in img.files.values())
    # the archive's layout: each file from a new sector, the entries of one file on the same sectors
    zdir = bytearray()
    at, placed = 0, {}
    for h, p, size in entries:
        key = os.path.normcase(os.path.abspath(p))
        if key not in placed:
            placed[key] = at
            at += (size + S - 1) // S
        zdir += struct.pack("<III", h, placed[key] if size else placed[key], size)
    zz_sectors = at
    new_size = zz_sectors * S
    if new_size > 0xFFFFFFFF:
        raise ValueError("the archive would be %d bytes, more than one ISO9660 file holds (4 GB)" % new_size)
    old_zdir_size = img.files[DIRECTORY][1]
    if len(zdir) != old_zdir_size:
        raise ValueError("ZDIR would change its size (%d -> %d)" % (old_zdir_size, len(zdir)))
    # where the files after the archive go
    moved, pos = {}, zz_ext + zz_sectors
    for ext, path in after:
        moved[path] = pos
        pos += (img.files[path][1] + S - 1) // S
    last_used = pos
    total = last_used + tail_gap
    log("archive: %d files, %d sectors (was %d); the image %d sectors (was %d)%s" % (
        len(placed), zz_sectors, zz_size // S if zz_size % S == 0 else zz_size // S + 1, total, img.sectors,
        "; more than a single-layer DVD holds (%d)" % DVD5 if total > DVD5 else ""))
    tmp = dst + ".part"
    with open(tmp, "wb") as out:
        # everything before the archive as it is, then the archive, then the files that were after it
        img.f.seek(0)
        left = zz_ext * S
        while left:
            b = img.f.read(min(left, 1 << 24))
            out.write(b)
            left -= len(b)
        done = 0
        bufs = {}
        for h, p, size in entries:
            key = os.path.normcase(os.path.abspath(p))
            if key in bufs:
                continue
            bufs[key] = True
            with open(p, "rb") as fh:
                b = fh.read()
            out.write(b + bytes((-len(b)) % S))
            done += 1
        for ext, path in after:
            b = img.read_file(path)
            out.write(b + bytes((-len(b)) % S))
        out.write(bytes(S * tail_gap))
    # the file systems follow
    with open(tmp, "r+b") as out:
        def put(sector, offset, data):
            out.seek(sector * S + offset)
            out.write(data)

        def both(v):
            return struct.pack("<I", v) + struct.pack(">I", v)
        put(img.files[DIRECTORY][0], 0, bytes(zdir))
        put(zz_rec[0], zz_rec[1] + 10, both(new_size))
        for path, new_ext in moved.items():
            rec = img.files[path][2]
            put(rec[0], rec[1] + 2, both(new_ext))
        put(16, 80, both(total))
        u = img.udf
        if u:
            start = u["start"]
            for n in u["parts"]:
                d = bytearray(img.sec(n))
                struct.pack_into("<I", d, 192, total - start - 1)
                put(n, 0, _retag(d, n))
            for target, (n, ad_off) in u["entries"].items():
                d = bytearray(img.sec(n))
                if target == zz_ext:
                    struct.pack_into("<Q", d, 56, new_size)
                    length, posn = struct.unpack_from("<II", d, ad_off)
                    struct.pack_into("<I", d, ad_off, (length & 0xC0000000) | (new_size & 0x3FFFFFFF))
                    # the blocks recorded (logical blocks of the file)
                    struct.pack_into("<Q", d, 64, zz_sectors)
                else:
                    path = next((p for p, v in img.files.items() if v[0] == target), None)
                    if path not in moved:
                        continue
                    struct.pack_into("<I", d, ad_off + 4, moved[path] - start)
                put(n, 0, _retag(d, n - start))         # a file entry's place counts from the partition
            # the closing anchor at the new end (the old one is not copied: only what lay before the archive is)
            anchor = img.sec(256)
            if img.sectors - 1 in u["anchors"]:
                put(total - 1, 0, _retag(anchor, total - 1))
    os.replace(tmp, dst)
    return {"files": len(placed), "archive_sectors": zz_sectors, "sectors": total, "moved": moved,
            "over_dvd5": total > DVD5}


def ps2_warnings(data):
    """What the port takes and a PS2 may not: pictures wider or taller than the GS's 1024. Lines to show."""
    import glob
    import hp2tex as tex
    out = []
    for pat in ("CARS/TEXTURES.tex", "GLOBAL/*.tex", "GLOBAL/*.BUN", "FRONTEND/*.tex", "FRONTEND/*.BUN",
                "TRACKS/*.tex", "TRACKS/*.BUN"):
        for p in glob.glob(os.path.join(data, pat)):
            if not os.path.exists(p + ".orig"):
                continue                            # the disc's own file: as the PS2 has it
            buf = open(p, "rb").read()
            disc = {t.hash: (t.width, t.height, t.bpp) for t in tex.read_textures(open(p + ".orig", "rb").read())}
            for t in tex.read_textures(buf):
                if t.width > 1024 or t.height > 1024:
                    out.append("%s: %s is %dx%d; a PS2 draws at most 1024 a side" % (
                        os.path.relpath(p, data), t.name, t.width, t.height))
                elif t.hash in disc and not t.parent and (t.width, t.height, t.bpp) != disc[t.hash]:
                    w, h, b = disc[t.hash]
                    out.append("%s: %s is %dx%d %d-bit (the disc's %dx%d %d-bit): textures of a new size are not "
                               "recommended on a disc for a PS2 yet" % (os.path.relpath(p, data), t.name, t.width,
                                                                       t.height, t.bpp, w, h, b))
    return out


def check(dst, data, log=print):
    """The new image read back as the installer reads one: every archive entry's bytes against data, the boot files.
    Answers the number of entries that differ."""
    img = Image(dst)
    zz = img.files[ARCHIVE]
    zdir = img.read_file(DIRECTORY)
    index = dict(read_index(data))
    bad = 0
    for i in range(0, len(zdir) // 12 * 12, 12):
        h, at, size = struct.unpack_from("<III", zdir, i)
        img.f.seek((zz[0] + at) * S)
        got = img.f.read(size)
        rel = index.get(h)
        want = open(os.path.join(data, *rel.split("/")), "rb").read() if rel else None
        if got != want:
            bad += 1
            if bad <= 5:
                log("differs: %08x %s" % (h, rel))
    log("read back: %d archive entries, %d differ; boot files %s" % (
        len(zdir) // 12, bad, ", ".join(sorted(p for p in img.files if not p.startswith("/NFSHP2/")))))
    return bad
