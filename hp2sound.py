"""The game's sound: effects banks (SOUND\\*.MSH + *.MSB), the music (SOUND\\JUKEBOXM.JBC) and speech
(SOUND\\SPEECH\\<LANGUAGE>BAN.PCK + DAT.PCK). All of it is the SPU's ADPCM (hp2codec.dll; see hp2movie.Adpcm).

Effects: the .MSH is u32 size, u32 pad, u32 count, then 52-byte records {char[32] name, s8 pan, u8 loop/channel (bit 0
loops, bit 4 the right half of a stereo pair), u16 rate, u16 volume, u16 effect volume, u32 offset in the .MSB, u32 ADSR,
u32 0}; the .MSH is padded to 64 bytes. A patch runs to the next one's offset. It starts with a frame of zeros; a patch that
loops has the flags 6, 2, ..., 3 (from its second frame to its last), one that does not ends with 1.

Music: a 32-byte header (16, 2 channels, 32000 Hz, 1, 4096), an index of 4096 bytes at 32 (a 64-byte category with the
count, then 96-byte tunes {u32 offset of the tune's 48-byte VAG header, u32 size, u32 0, char[84] name}), each tune's audio
at offset + 48 on a 2048-byte boundary, stereo in 0x8000-byte blocks left then right; the last real frame of both channels
has the flag 1 and the next the flag 7, and the last pair is padded to its full size.

Speech: the BAN's 16-byte entries {u32 count/handle, u32 the bank's offset in the BAN, u32 0, u32 the bank's base in the
DAT}; a bank: u16 id, u16 sub, u8 flags (low nibble: parameters a sample), u8 samples, u8 queue, u8 unit (U = (b+1)*256),
u16 end in units, u16; from +12 each sample's big-endian u16 offset in units and its parameters. A clip at base + offset*U is
a 48-byte VAG header and mono ADPCM at 24000 Hz. The game plays a clip to the next clip's offset (the VAG header is
skipped, its size not read), so a replaced clip gets a place of its own length: its bank is laid out anew and the DAT
rebuilt back to back (Speech.rebuild).

Files may change size: the port builds its archive from the files at start. Keep the names: the game finds patches by name.
"""

import os
import struct

import numpy as np

import hp2movie as mv

MUSIC = "SOUND/JUKEBOXM.JBC"
SPEECH_RATE = 24000
MUSIC_RATE = 32000
FRAME = 16
SAMPLES = 28


# ---- ADPCM with flags ---------------------------------------------------------------------------------------------------

def decode_mono(data):
    """ADPCM frames to samples, stopping at an end flag (1: this frame counts, 7: it does not)."""
    n = len(data) // FRAME
    end = n
    for i in range(n):
        f = data[i * FRAME + 1]
        if f == 7:
            end = i
            break
        if f == 1:
            end = i + 1
            break
    return mv.Adpcm().decode(data[:end * FRAME])


def encode_mono(pcm, lead_in=True):
    """Samples to ADPCM frames (flags 0), a frame of zeros first if lead_in, padded to whole frames."""
    pcm = np.asarray(pcm, np.int16)
    pad = (-len(pcm)) % SAMPLES
    if pad:
        pcm = np.concatenate([pcm, np.zeros(pad, np.int16)])
    body = mv.Adpcm().encode(pcm)
    return (bytes(FRAME) if lead_in else b"") + body


def set_flags(data, loop):
    """The effects' flags: looping 0, 6, 2.., 3 (at least three frames); not looping 0.., 1."""
    b = bytearray(data)
    n = len(b) // FRAME
    if loop:
        while n < 3:
            b += bytes(FRAME)
            n += 1
        for i in range(1, n):
            b[i * FRAME + 1] = 6 if i == 1 else 3 if i == n - 1 else 2
    else:
        for i in range(n):
            b[i * FRAME + 1] = 1 if i == n - 1 else 0
    return bytes(b)


def resample(pcm, src, dst):
    """(n, channels) int16 from rate src to dst, linear."""
    if src == dst or not len(pcm):
        return pcm
    t = np.arange(int(len(pcm) * dst / src)) * (src / dst)
    return np.clip(np.round(np.stack([np.interp(t, np.arange(len(pcm)), pcm[:, c]) for c in range(pcm.shape[1])], 1)),
                   -32768, 32767).astype(np.int16)


def read_wav_any(path):
    """(pcm (n, ch) int16, rate) of a WAV, as it is."""
    import wave
    with wave.open(path, "rb") as w:
        ch, width, r, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        if width == 2 and ch in (1, 2):
            # the usual one, and every one the export writes: the samples as they are, no arithmetic (a mass import
            # reads tens of thousands of these)
            return np.frombuffer(w.readframes(n), "<i2").reshape(-1, ch).copy(), r
    pcm = mv.read_wav(path, r)          # 2 channels, at its own rate
    if ch == 1:
        pcm = pcm[:, :1]
    return pcm, r


# ---- effects banks ------------------------------------------------------------------------------------------------------

class Patch:
    def __init__(self, raw, index):
        self.raw = bytearray(raw)
        self.index = index

    name = property(lambda s: bytes(s.raw[:32]).split(b"\0")[0].decode("latin-1"))
    flags = property(lambda s: s.raw[33])
    loops = property(lambda s: bool(s.raw[33] & 1))
    right = property(lambda s: bool(s.raw[33] & 16))
    rate = property(lambda s: struct.unpack_from("<H", s.raw, 34)[0])
    volume = property(lambda s: struct.unpack_from("<H", s.raw, 36)[0])
    offset = property(lambda s: struct.unpack_from("<I", s.raw, 40)[0])


class Bank:
    def __init__(self, msh, msb):
        size, pad, n = struct.unpack_from("<III", msh, 0)
        self.head = bytes(msh[:12])
        self.patches = [Patch(msh[12 + 52 * i:12 + 52 * (i + 1)], i) for i in range(n)]
        self.audio = []
        for i, p in enumerate(self.patches):
            end = self.patches[i + 1].offset if i + 1 < n else len(msb)
            self.audio.append(bytes(msb[p.offset:end]))

    def sounds(self):
        """[(name, [patch indices: one, or left and right])]"""
        out, i = [], 0
        while i < len(self.patches):
            p = self.patches[i]
            if i + 1 < len(self.patches) and self.patches[i + 1].right and self.patches[i + 1].name == p.name:
                out.append((p.name, [i, i + 1]))
                i += 2
            else:
                out.append((p.name, [i]))
                i += 1
        return out

    def pcm(self, idx):
        """The sound without the patch's frame of zeros in front."""
        chans = [decode_mono(self.audio[i])[SAMPLES:] for i in idx]
        n = max(len(c) for c in chans)
        return np.stack([np.pad(c, (0, n - len(c))) for c in chans], 1)

    def replace(self, idx, pcm, rate):
        """Put a sound in: pcm (n, ch) at `rate`, made the patches' rate and channel count, flags as they had."""
        target = self.patches[idx[0]].rate
        pcm = resample(pcm, rate, target)
        if pcm.shape[1] < len(idx):
            pcm = np.repeat(pcm, len(idx), 1)
        for k, i in enumerate(idx):
            ch = pcm[:, k] if len(idx) > 1 else (pcm.mean(1).astype(np.int16) if pcm.shape[1] > 1 else pcm[:, 0])
            self.audio[i] = set_flags(encode_mono(ch), self.patches[i].loops)

    def build(self):
        """(msh, msb): the offsets made again from the patches' sizes."""
        msb = bytearray()
        recs = []
        for p, a in zip(self.patches, self.audio):
            msb += bytes((-len(msb)) & 15)
            r = bytearray(p.raw)
            struct.pack_into("<I", r, 40, len(msb))
            recs.append(bytes(r))
            msb += a
        body = b"".join(recs)
        n = 12 + len(body)
        pad = (-n) & 63
        msh = struct.pack("<III", n + pad, pad, len(recs)) + body + bytes(pad)
        return msh, bytes(msb)


def engine_banks(data):
    """{engine bank name as the game asks for it (NEWEDNF...): [the car types that use it]}, from the car records
    (GLOBALB 0x34600, the engine's bank at +816)."""
    out = {}
    gb = os.path.join(data, "GLOBAL", "GLOBALB.BUN")
    if os.path.isfile(gb):
        import hp2car
        for r in hp2car.car_type_records(open(gb, "rb").read()):
            e = r.raw[816:848].split(b"\0")[0].decode("latin-1").upper()
            if e:
                out.setdefault(e, []).append(r.raw[0:32].split(b"\0")[0].decode("latin-1"))
    return out


# the folder name a renamed bank had in exports made before it had its name: Effects\<old>
BANK_ALIASES = {}


def bank_paths(data):
    """{bank name: (msh path, msb path)} of SOUND. A bank the install keeps by its hash (unnamed_<hash of the .MSB>,
    as no name was known to the installer) takes the name the game asks for, found among the cars' engine banks:
    unnamed_38aae9f9 is NEWETESTAROSA, the F50's engine."""
    import hp2core as core
    out = {}
    d = os.path.join(data, "SOUND")
    engines = None
    for f in sorted(os.listdir(d)):
        if f.upper().endswith(".MSH"):
            msb = os.path.join(d, f[:-4] + ".MSB")
            if os.path.isfile(msb):
                name = f[:-4]
                if name.lower().startswith("unnamed_"):
                    try:
                        h = int(name[8:], 16)
                    except ValueError:
                        h = None
                    if engines is None:
                        engines = engine_banks(data)
                    real = next((e for e in engines if core.bhash("SOUND\\%s.MSB" % e) == h), None)
                    if real:
                        BANK_ALIASES[real] = name
                        name = real
                out[name] = (os.path.join(d, f), msb)
    return out


def load_bank(data, name):
    msh, msb = bank_paths(data)[name]
    return Bank(open(msh, "rb").read(), open(msb, "rb").read())


# ---- music --------------------------------------------------------------------------------------------------------------

class Jukebox:
    def __init__(self, buf):
        self.buf = buf
        self.head = buf[:32]
        isize = struct.unpack_from("<I", buf, 16)[0]
        self.index = bytearray(buf[32:32 + isize])
        n = struct.unpack_from("<I", self.index, 0)[0]
        self.tunes = []
        for i in range(n):
            o = 64 + 96 * i
            off, size = struct.unpack_from("<II", self.index, o)
            self.tunes.append([off, size, bytes(buf[off:off + size])])

    def name(self, i):
        return bytes(self.index[64 + 96 * i + 12:64 + 96 * (i + 1)]).split(b"\0")[0].decode("latin-1")

    def pcm(self, i):
        """(n, 2) int16 at 32000."""
        data = self.tunes[i][2][48:]
        pairs = len(data) // (2 * mv.BLOCK)
        L, R = [], []
        for k in range(pairs):
            p = k * 2 * mv.BLOCK
            L.append(data[p:p + mv.BLOCK])
            R.append(data[p + mv.BLOCK:p + 2 * mv.BLOCK])
        lpcm, rpcm = decode_mono(b"".join(L)), decode_mono(b"".join(R))
        n = min(len(lpcm), len(rpcm))
        return np.stack([lpcm[:n], rpcm[:n]], 1)

    def replace(self, i, pcm, rate):
        pcm = resample(pcm, rate, MUSIC_RATE)
        if pcm.shape[1] == 1:
            pcm = np.repeat(pcm, 2, 1)
        chans = [bytearray(encode_mono(pcm[:, c], lead_in=False)) for c in range(2)]
        # the end: flag 1 on the last real frame, then a frame with 7, in both channels at the same place
        for c in chans:
            c[-FRAME + 1] = 1
            c += bytes([0, 7]) + bytes(FRAME - 2)
        per = len(chans[0])
        pairs = -(-per // mv.BLOCK)
        for c in chans:
            c += bytes(pairs * mv.BLOCK - len(c))
        body = bytearray()
        for k in range(pairs):
            body += chans[0][k * mv.BLOCK:(k + 1) * mv.BLOCK] + chans[1][k * mv.BLOCK:(k + 1) * mv.BLOCK]
        old = self.tunes[i][2]
        head = bytearray(old[:48])
        struct.pack_into(">I", head, 12, 2 * per)
        self.tunes[i][2] = bytes(head) + bytes(body)

    def build(self):
        out = bytearray(self.head) + self.index
        for i, t in enumerate(self.tunes):
            # the audio after the 48-byte header on a 2048-byte boundary, as the disc has it
            while (len(out) + 48) % 2048:
                out.append(0)
            off = len(out)
            out += t[2]
            struct.pack_into("<II", out, 32 + 64 + 96 * i, off, len(t[2]))
            out += bytes(2048)                     # and a sector of zeros after each tune
        while len(out) % 2048:
            out.append(0)
        return bytes(out)


# ---- speech -------------------------------------------------------------------------------------------------------------

class SpeechBank:
    def __init__(self, ban, n, entry):
        self.entry = entry
        _, boff, _, base = struct.unpack_from("<IIII", ban, entry * 16)
        self.ban_off, self.base = boff, base
        self.unit = (ban[boff + 7] + 1) * 256
        self.npar = ban[boff + 4] & 15
        self.count = ban[boff + 5]
        self.end = struct.unpack_from("<H", ban, boff + 8)[0]
        self.offsets = [struct.unpack_from(">H", ban, boff + 12 + i * (2 + self.npar))[0] for i in range(self.count)]


class Speech:
    def __init__(self, ban, dat):
        self.ban = bytearray(ban)
        self.dat = bytearray(dat)
        n = struct.unpack_from("<I", ban, 0)[0]
        self.n = n
        self.banks = [SpeechBank(self.ban, n, e) for e in range(n)]
        self._read_names()

    # The DAT ends in the table its packer left: u32 count, then for each bank u32 n, n bytes (its file's name, a NUL,
    # and what was left of the path in the buffer), u32 size, u32 size, u32 offset; it starts where the last bank ends.
    # The game goes by the BAN; the table gives the banks their names ("19AddPrime", "CarDa"...), by offset.
    def _read_names(self):
        self.names, self.table = {}, None
        if not self.banks:
            return
        d = self.dat
        start = max(bk.base + bk.end * bk.unit for bk in self.banks)
        if self._table_at(struct.unpack_from("<I", d, 0)[0] if len(d) >= 4 else 0):
            start = struct.unpack_from("<I", d, 0)[0]          # the first word says where the table is
        try:
            count, = struct.unpack_from("<I", d, start)
            p, rows = start + 4, []
            for _ in range(count):
                ln, = struct.unpack_from("<I", d, p)
                block = bytes(d[p + 4:p + 4 + ln])
                size, size2, off = struct.unpack_from("<III", d, p + 4 + ln)
                rows.append([block, size, size2, off])
                p += 16 + ln
        except struct.error:
            return
        if p != len(d) or not 0 < count < 100000:
            return
        self.table = (start, rows)
        by_off = {r[3]: r for r in rows}
        for b, bk in enumerate(self.banks):
            r = by_off.get(bk.base)
            if r is not None:
                n = r[0].split(b"\0")[0].decode("latin-1")
                self.names[b] = n[:-4] if n.lower().endswith(".dat") else n

    def _table_at(self, start):
        """Whether a whole name table starts at start and runs to the end of the DAT."""
        d = self.dat
        try:
            count, = struct.unpack_from("<I", d, start)
            if not 0 < count < 100000:
                return False
            p = start + 4
            for _ in range(count):
                ln, = struct.unpack_from("<I", d, p)
                p += 16 + ln
            return p == len(d)
        except struct.error:
            return False

    def name(self, b):
        return self.names.get(b, "")

    def clip_range(self, b, i):
        """(start, slot end) of clip i of bank b in the DAT."""
        bk = self.banks[b]
        off = bk.offsets[i] & 0x7FFF
        nxt = [o & 0x7FFF for o in bk.offsets if (o & 0x7FFF) > off]
        end = min(nxt) if nxt else bk.end
        return bk.base + off * bk.unit, bk.base + end * bk.unit

    def pcm(self, b, i):
        s, e = self.clip_range(b, i)
        if self.dat[s:s + 4] != b"VAGp":
            return np.zeros(0, np.int16)
        size = struct.unpack_from(">I", self.dat, s + 12)[0]
        return decode_mono(bytes(self.dat[s + 48:s + 48 + min(size, e - s - 48)]))

    def _clip(self, b, i, pcm, rate):
        """A clip's bytes (its 48-byte VAG header, the ADPCM) for pcm (n, ch) at rate."""
        pcm = resample(pcm, rate, SPEECH_RATE)
        mono = pcm.mean(1).astype(np.int16) if pcm.shape[1] > 1 else pcm[:, 0]
        data = encode_mono(mono)
        s, e = self.clip_range(b, i)
        head = bytearray(self.dat[s:s + 48]) if self.dat[s:s + 4] == b"VAGp" else bytearray(b"VAGp" + bytes(44))
        struct.pack_into(">I", head, 12, len(data))
        return bytes(head) + data

    def replace(self, b, i, pcm, rate):
        """A clip in, at its own length (replace_many)."""
        return self.replace_many(b, {i: (pcm, rate)})

    def replace_many(self, b, new):
        """Clips of bank b in, {clip: (pcm, rate)}, each at its own length. The game plays a clip from its offset in the
        BAN to the next clip's (iSPCH_UnPackSample, cSEDWedge::PlaySentence), so a clip left in a longer place would
        end in a pause and one in a shorter place would be cut: the bank is laid out anew and the DAT rebuilt."""
        self.replace_banks({b: new})
        return "at its own length" if len(new) == 1 else "at their own length"

    def replace_banks(self, new):
        """Clips of many banks in, {bank: {clip: (pcm, rate)}}, with one rebuild of the DAT for all of them."""
        changed = {}
        for b, clips in sorted(new.items()):
            bk = self.banks[b]
            cur = changed.get(bk.ban_off)
            if cur is None:
                cur = [bytes(self.dat[slice(*self.clip_range(b, k))]) for k in range(bk.count)]
                for t in self.twins(b):                     # one list for all: they stay one bank in the DAT
                    changed[self.banks[t].ban_off] = cur
            for i, (pcm, rate) in clips.items():
                cur[i] = self._clip(b, i, pcm, rate)
        if changed:
            self.rebuild(changed)

    def _desc(self, b):
        bk = self.banks[b]
        return bytes(self.ban[bk.ban_off:bk.ban_off + 12 + bk.count * (2 + bk.npar)])

    def twins(self, b):
        """b and the banks that are the same bank under another BAN entry: the same place in the DAT and the same
        description, byte for byte (Boulderturnout twice in English, 672 such in French). A clip put into one goes into
        all of them, or the game, which may take either, would sometimes say the old one."""
        bk = self.banks[b]
        d = self._desc(b)
        return [t for t, o in enumerate(self.banks) if t == b or (o.base == bk.base and self._desc(t) == d)]

    def rebuild(self, changed=None):
        """The DAT laid out anew, everything back to back as the game's packer left it: its first 256 bytes (the table's
        offset in the first word), then the banks in their order, then the name table. changed is {a bank's place in
        the BAN: [its clips' bytes]}: those banks are laid out from their clips (each padded to the bank's unit) next to
        where they were. What no bank and no table row points at (the copies left behind by moving banks, as this tool
        did up to 0.14) is dropped. Several BAN entries may share one bank (the same place in the BAN and the DAT):
        they move together. With nothing changed and nothing left behind the file comes out byte for byte the same."""
        import bisect
        changed = changed or {}
        ban, d = self.ban, self.dat
        ents = [struct.unpack_from("<IIII", ban, e * 16)[1::2] for e in range(self.n)]     # (place in the BAN, base)
        length = {bk.ban_off: bk.end * bk.unit for bk in self.banks}
        rows = [list(r) for r in self.table[1]] if self.table else []
        moved = {base for boff, base in ents if boff in changed}
        kept = {base for boff, base in ents if boff not in changed}
        for boff, clips in changed.items():
            bk = next(k for k in self.banks if k.ban_off == boff)
            if any(o & 0x8000 for o in bk.offsets):
                raise SystemExit("bank at %d: a clip of it stands for another one (not supported)" % boff)
        spans = [(base, base + length[boff]) for boff, base in ents if boff not in changed]
        spans += [(r[3], r[3] + r[1]) for r in rows if not (r[3] in moved and r[3] not in kept)]
        spans.sort()
        regions = []
        for s, e in spans:
            if regions and s <= regions[-1][1]:
                regions[-1][1] = max(regions[-1][1], e)
            else:
                regions.append([s, e])
        starts = [r[0] for r in regions]

        def inside(a):
            k = bisect.bisect_right(starts, a) - 1
            return k if k >= 0 and a < regions[k][1] else None

        # a new bank goes right after the region its old place was in (or where that place was, if nothing is left);
        # BAN entries given the same list of clips (twins) get one copy of it
        pieces = [((s, 0), "old", (s, e)) for s, e in regions]
        old_base = {}
        group = {}
        for boff in changed:
            base = next(b for o, b in ents if o == boff)
            old_base[boff] = base
            group.setdefault(id(changed[boff]), []).append(boff)
        for boffs in group.values():
            base = old_base[boffs[0]]
            k = inside(base)
            pieces.append(((regions[k][1] if k is not None else base, -1), "new", boffs))
        pieces.sort(key=lambda p: p[0])
        head = min([256] + [r[0] for r in regions] + list(moved) + [len(d)])     # the packer's head is 256 bytes
        out = [bytes(d[:head])]
        at = head
        new_start, new_base, new_len = [], {}, {}
        for _, what, x in pieces:
            if what == "old":
                s, e = x
                new_start.append(at)
                out.append(bytes(d[s:e]))
                at += e - s
                continue
            boffs = x
            clips = changed[boffs[0]]
            ubyte = ban[boffs[0] + 7]
            while True:
                unit = (ubyte + 1) * 256
                sizes = [len(c) + (-len(c) % unit) for c in clips]
                offs = [sum(sizes[:k]) // unit for k in range(len(sizes))]
                if (not offs or offs[-1] < 0x8000) and sum(sizes) // unit <= 0xFFFF:
                    break
                if ubyte == 255:
                    raise SystemExit("bank at %d would be too long" % boffs[0])
                ubyte += 1
            for c, sz in zip(clips, sizes):
                out.append(c + bytes(sz - len(c)))
            for boff in boffs:
                bk = next(k for k in self.banks if k.ban_off == boff)
                ban[boff + 7] = ubyte
                for k, o in enumerate(offs):
                    struct.pack_into(">H", ban, boff + 12 + k * (2 + bk.npar), o)
                struct.pack_into("<H", ban, boff + 8, sum(sizes) // unit)
                new_base[boff], new_len[boff] = at, sum(sizes)
            at += sum(sizes)

        def where(a):
            k = inside(a)
            return a - regions[k][0] + new_start[k]

        for e, (boff, base) in enumerate(ents):
            struct.pack_into("<I", ban, e * 16 + 12, new_base[boff] if boff in changed else where(base))
        for r in rows:
            if r[3] in moved and r[3] not in kept:
                boff = next(o for o in changed if old_base[o] == r[3])
                old = length[boff]
                r[1], r[2] = (new_len[boff] if r[1] == old else r[1]), (new_len[boff] if r[2] == old else r[2])
                r[3] = new_base[boff]
            else:
                r[3] = where(r[3])
        if self.table is not None:
            tab = [struct.pack("<I", len(rows))]
            for block, size, size2, off in rows:
                tab.append(struct.pack("<I", len(block)) + block + struct.pack("<III", size, size2, off))
            out.append(b"".join(tab))
        self.dat = bytearray(b"".join(out))
        if self.table is not None and head >= 4:
            struct.pack_into("<I", self.dat, 0, at)
        self.banks = [SpeechBank(self.ban, self.n, e) for e in range(self.n)]
        names = self.names
        self._read_names()
        if not self.names:
            self.names = names


def speech_languages(data):
    d = os.path.join(data, "SOUND", "SPEECH")
    out = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.upper().endswith("BAN.PCK"):
                lang = f[:-7]
                if os.path.isfile(os.path.join(d, lang + "DAT.PCK")):
                    out.append(lang)
    return out


def speech_paths(data, lang):
    d = os.path.join(data, "SOUND", "SPEECH")
    return os.path.join(d, lang + "BAN.PCK"), os.path.join(d, lang + "DAT.PCK")


# ---- many sounds at once ------------------------------------------------------------------------------------------------
#
# A folder of WAVs goes into one source (an effects bank, the music, a language's speech) by the names the export gives
# them; a tree of such folders (Effects\<BANK>\, Music\, Speech\<LANGUAGE>\) goes into the whole game. A WAV that is the
# sound as it is (an exported file left alone) is passed over: the ADPCM loses a little each time it is made again.

def safe(s):
    return "".join(c if c.isalnum() or c in "-_ ()." else "_" for c in s)


def open_source(data, kind, name):
    """(the object, its files) of a source: kind Effects (name a bank), Music, or Speech (name a language)."""
    if kind == "Effects":
        fs = list(bank_paths(data)[name])
        return Bank(open(fs[0], "rb").read(), open(fs[1], "rb").read()), fs
    if kind == "Music":
        fs = [os.path.join(data, MUSIC)]
        return Jukebox(open(fs[0], "rb").read()), fs
    fs = list(speech_paths(data, name))
    return Speech(open(fs[0], "rb").read(), open(fs[1], "rb").read()), fs


def built(kind, obj):
    """The source's files' new bytes, in the order of open_source's files."""
    if kind == "Effects":
        return list(obj.build())
    if kind == "Music":
        return [obj.build()]
    return [bytes(obj.ban), bytes(obj.dat)]


def sources(data):
    """[(kind, name, the folder's path in a tree)] of the game's sounds."""
    out = [("Effects", b, os.path.join("Effects", b)) for b in bank_paths(data)]
    if os.path.isfile(os.path.join(data, MUSIC)):
        out.append(("Music", "JUKEBOXM", "Music"))
    out += [("Speech", lang, os.path.join("Speech", lang)) for lang in speech_languages(data)]
    return out


def items(kind, obj):
    """[(key, file name without .wav, now)] of a source's sounds: now() is (pcm (n, ch) int16, rate) as the sound is; the
    key is what its replace takes (an effect's patch indices, a tune's number, (bank, clip))."""
    out = []
    if kind == "Effects":
        for n, idx in obj.sounds():
            out.append((tuple(idx), safe(n), lambda idx=idx: (obj.pcm(idx), obj.patches[idx[0]].rate)))
    elif kind == "Music":
        for i in range(len(obj.tunes)):
            n = obj.name(i)
            out.append((i, safe("%02d %s" % (i, n.split("-")[1] if "-" in n else n)),
                        lambda i=i: (obj.pcm(i), MUSIC_RATE)))
    else:
        for b, bk in enumerate(obj.banks):
            for i in range(bk.count):
                nm = safe(obj.name(b)).replace("_", "-")
                out.append(((b, i), ("bank%04d_%s_clip%02d" % (b, nm, i)) if nm else "bank%04d_clip%02d" % (b, i),
                            lambda b=b, i=i: (obj.pcm(b, i)[:, None], SPEECH_RATE)))
    return out


SUMS = "hp2sums.json"       # beside the WAVs an export writes: {name: [sha1 of the WAV file, sha1 of the sound's data]}


def _sha(b):
    import hashlib
    return hashlib.sha1(b).hexdigest()


def raw_of(kind, obj, key):
    """The bytes the game has for a sound (its ADPCM and what sets how it plays): equal bytes, equal sound."""
    if kind == "Effects":
        return b"".join(bytes(obj.audio[i]) + struct.pack("<H", obj.patches[i].rate) for i in key)
    if kind == "Music":
        return bytes(obj.tunes[key][2])
    s, e = obj.clip_range(*key)
    return bytes(obj.dat[s:e])


def _load_sums(folder):
    import json
    try:
        with open(os.path.join(folder, SUMS), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def export_source(kind, obj, folder, keys=None):
    """A source's sounds (or those of keys) as WAVs into folder, named as import_folder reads them, and their sums in
    SUMS: an import then knows a WAV left as it was without decoding the game's sound to compare."""
    import json
    os.makedirs(folder, exist_ok=True)
    sums = _load_sums(folder)
    n = 0
    for key, stem, now in items(kind, obj):
        if keys is not None and key not in keys:
            continue
        pcm, rate = now()
        p = os.path.join(folder, stem + ".wav")
        mv.write_wav(p, pcm, rate)
        with open(p, "rb") as f:
            sums[stem] = [_sha(f.read()), _sha(raw_of(kind, obj, key))]
        n += 1
    with open(os.path.join(folder, SUMS), "w", encoding="utf-8") as f:
        json.dump(sums, f, indent=0, sort_keys=True)
    return n


def _key_of(kind, stem, by_stem):
    """The key a WAV's name stands for: the export's name, or for music its number, for speech its bank and clip."""
    if stem in by_stem:
        return by_stem[stem]
    keys = set(by_stem.values())
    if kind == "Music" and stem[:2].isdigit():
        return int(stem[:2]) if int(stem[:2]) in keys else None
    if kind == "Speech":
        import re
        # bank0003_clip00 (before the banks had names) or bank0003_19AddPrime_clip00: the numbers are what count
        m = re.match(r"bank0*(\d+)(?:_[^_]*)?_clip0*(\d+)$", stem, re.I)
        if m and (int(m.group(1)), int(m.group(2))) in keys:
            return int(m.group(1)), int(m.group(2))
    return None


def import_folder(kind, obj, folder):
    """The WAVs of a folder into a source's object, by name. Answers {"changed": [names], "same": [names], "unknown":
    [file names], "bad": [(file name, why)]}."""
    its = items(kind, obj)
    by_stem = {stem: key for key, stem, _ in its}
    now_of = {key: now for key, _, now in its}
    name_of = {key: stem for key, stem, _ in its}
    rep = {"changed": [], "same": [], "unknown": [], "bad": []}
    speech = {}
    sums = _load_sums(folder)
    for f in sorted(os.listdir(folder)):
        if not f.lower().endswith(".wav"):
            continue
        stem = os.path.splitext(f)[0]
        key = _key_of(kind, stem, by_stem)
        if key is None:
            rep["unknown"].append(f)
            continue
        # the WAV as the export wrote it, of the sound as it still is: the same, with nothing decoded
        s = sums.get(stem)
        if s and s[1] == _sha(raw_of(kind, obj, key)):
            with open(os.path.join(folder, f), "rb") as fh:
                if _sha(fh.read()) == s[0]:
                    rep["same"].append(name_of[key])
                    continue
        try:
            pcm, rate = read_wav_any(os.path.join(folder, f))
        except Exception as e:          # a WAV the reader does not take: said, and the others go on
            rep["bad"].append((f, str(e)))
            continue
        old, old_rate = now_of[key]()
        if rate == old_rate and pcm.shape == old.shape and np.array_equal(pcm, old):
            rep["same"].append(name_of[key])
            continue
        if kind == "Effects":
            obj.replace(list(key), pcm, rate)
        elif kind == "Music":
            obj.replace(key, pcm, rate)
        else:
            speech.setdefault(key[0], {})[key[1]] = (pcm, rate)
        rep["changed"].append(name_of[key])
    if speech:
        obj.replace_banks(speech)
    return rep


def export_all(data, out, log=print):
    """Every sound of the game into a tree: Effects\\<BANK>\\, Music\\, Speech\\<LANGUAGE>\\."""
    total = 0
    for kind, name, rel in sources(data):
        obj, _ = open_source(data, kind, name)
        n = export_source(kind, obj, os.path.join(out, rel))
        log("%s: %d WAVs" % (rel, n))
        total += n
    log("%d WAVs -> %s" % (total, out))
    return total


def _find_dir(root, rel):
    """root/rel, in any case of its letters, or None."""
    here = root
    for part in rel.replace("\\", "/").split("/"):
        hit = None
        if os.path.isdir(here):
            for d in os.listdir(here):
                if d.upper() == part.upper() and os.path.isdir(os.path.join(here, d)):
                    hit = os.path.join(here, d)
                    break
        if hit is None:
            return None
        here = hit
    return here


def speech_folders(data, folder, lang=None):
    """[(language, folder of its WAVs)] that folder holds: WAVs of its own (for lang), or Speech\\<LANGUAGE> or
    <LANGUAGE> folders under it (an Export all tree, or a folder per language)."""
    if lang and any(f.lower().endswith(".wav") for f in os.listdir(folder)):
        return [(lang, folder)]
    out = []
    for name in speech_languages(data):
        for rel in (os.path.join("Speech", name), name):
            d = _find_dir(folder, rel)
            if d is not None and any(f.lower().endswith(".wav") for f in os.listdir(d)):
                out.append((name, d))
                break
    return out


def import_speech_anew(data, folder, write, lang=None, log=print):
    """Speech put in anew, in one go: for each language the folder has WAVs for (speech_folders), the disc's speech
    (the .orig the first write kept, else the files as they are) with the folder's WAVs in, every clip at its own
    length, written whole. What earlier imports left in the files (pauses after shorter clips, banks moved to the end
    by 0.14 and before) is gone; a clip not in the folder is the disc's. Answers the number of clips put in."""
    total = 0
    pairs = speech_folders(data, folder, lang)
    if not pairs:
        log("no speech WAVs in %s (bankNNNN_..._clipNN.wav, or Speech\\<LANGUAGE> folders)" % folder)
        return 0
    for name, d in pairs:
        files = list(speech_paths(data, name))
        src = [p + ".orig" if os.path.isfile(p + ".orig") else p for p in files]
        sp = Speech(open(src[0], "rb").read(), open(src[1], "rb").read())
        rep = import_folder("Speech", sp, d)
        for f in rep["unknown"]:
            log("%s: %s is no clip of it" % (name, f))
        for f, why in rep["bad"]:
            log("%s: %s: %s" % (name, f, why))
        new = [bytes(sp.ban), bytes(sp.dat)]
        wrote = []
        for p, b in zip(files, new):
            if os.path.getsize(p) != len(b) or open(p, "rb").read() != b:
                write(p, b)
                wrote.append(os.path.basename(p))
        log("%s: %d clips put in, %d as on the disc; from the disc's %s; %s" % (
            name, len(rep["changed"]), len(rep["same"]), "copy (.orig)" if src[1] != files[1] else "files",
            ("written " + ", ".join(wrote)) if wrote else "the files were that already"))
        total += len(rep["changed"])
    return total


def import_tree(data, root, write, log=print):
    """A tree as export_all makes it (any part of it: one bank's folder is enough) into the game; write(path, bytes) puts
    a file in. Answers the number of sounds changed."""
    total = 0
    for kind, name, rel in sources(data):
        folder = _find_dir(root, rel)
        if folder is None and kind == "Effects" and name in BANK_ALIASES:
            folder = _find_dir(root, os.path.join("Effects", BANK_ALIASES[name]))     # an export from before
        if folder is None:
            continue
        obj, files = open_source(data, kind, name)
        before = [os.path.getsize(p) for p in files]
        rep = import_folder(kind, obj, folder)
        for f in rep["unknown"]:
            log("%s: %s is no sound of it" % (rel, f))
        for f, why in rep["bad"]:
            log("%s: %s: %s" % (rel, f, why))
        if not rep["changed"]:
            if rep["same"]:
                log("%s: nothing changed (%d as they were)" % (rel, len(rep["same"])))
            continue
        new = built(kind, obj)
        grew = ""
        if kind == "Effects":
            d = len(new[1]) - before[1]
            if abs(d) >= 1024:
                grew = "; the bank %s by %d KB (the sound chip has 2 MB for every bank loaded at once, and a race " \
                       "leaves about 270 KB of it free)" % ("grows" if d > 0 else "shrinks", abs(d) // 1024)
        log("%s: %d changed, %d as they were%s" % (rel, len(rep["changed"]), len(rep["same"]), grew))
        for p, b in zip(files, new):
            write(p, b)
        total += len(rep["changed"])
    log("%d sounds changed" % total)
    return total
