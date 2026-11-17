"""The game's texts: LANGUAGES\\FE_<LANGUAGE>.lang, one chunk 0x39000 each (the disc's FE_*.BIN).

Layout (docs language-table.md, checked on the disc): +16 char[64] file name, +80 s32 language, +84 u32 entries in the
hash table, +88 u32 entries in the ID table (the same), +92 u32 size of the texts, +96..107 three pointers (0), +108 the
hash table {s32 key, u32 offset}, then the ID table {s32 id, u32 offset}, both sorted as signed numbers, then the texts,
NUL-terminated, Latin-1. A hash key is bStringHash of the English text the game had: the game finds some texts by that, so
the keys stay as they are when a text changes. The file is padded to 4 bytes; the chunk's size is the file's less 8.

Texts here are Unicode; the bytes 0x80..0x9F (the pad's button pictures) go as \\xNN, '@' is a new line in the game, and
%s %d %c are filled in by the game.
"""

import csv
import os
import struct

LANG_CHUNK = 0x00039000
LANGUAGES = ("ENGLISH", "FRENCH", "GERMAN", "ITALIAN", "SPANISH", "SWEDISH")
NUL = bytes(1)
BACKSLASH = 0x5C


class LangFile:
    def __init__(self, buf):
        cid, size = struct.unpack_from("<II", buf, 0)
        if cid != LANG_CHUNK:
            raise ValueError("not a language file (chunk %08x)" % cid)
        self.head = bytes(buf[:108])
        self.language = struct.unpack_from("<i", buf, 80)[0]
        nh, ni, tsize = struct.unpack_from("<III", buf, 84)
        p = 108
        self.hash_table = [struct.unpack_from("<iI", buf, p + 8 * i) for i in range(nh)]
        p += 8 * nh
        self.id_table = [struct.unpack_from("<iI", buf, p + 8 * i) for i in range(ni)]
        p += 8 * ni
        self.pool = bytes(buf[p:p + tsize])
        self.last_nul = self.pool.endswith(NUL)
        by_off = {}
        for key, off in self.hash_table:
            by_off.setdefault(off, []).append(key)
        self.texts = {}           # id -> bytes
        self.keys = {}            # id -> hash key
        for i, off in self.id_table:
            end = self.pool.find(NUL, off)
            self.texts[i] = self.pool[off:end if end >= 0 else len(self.pool)]
            ks = by_off.get(off)
            if ks:
                self.keys[i] = ks.pop(0)

    def build(self):
        """The file again: both tables pointing at the texts, laid out in the disc's order of the texts (not the ids'),
        so an unchanged file comes out byte for byte."""
        pool = bytearray()
        offs = {}
        order = sorted(self.id_table, key=lambda e: e[1])
        for k, (i, off) in enumerate(order):
            offs[i] = len(pool)
            pool += self.texts[i]
            # what the disc has after the text up to the next one: its NUL, and a few strings no id points at
            nxt = order[k + 1][1] if k + 1 < len(order) else len(self.pool)
            end = self.pool.find(NUL, off)
            pool += self.pool[end:nxt] if 0 <= end < nxt else (NUL if k + 1 < len(order) else b"")
        id_table = [(i, offs[i]) for i, _ in self.id_table]
        # the hash table in its own order (equal keys keep theirs), pointing at where each text went
        moved = {old: offs[i] for i, old in self.id_table}
        hash_table = [(k, moved.get(o, o)) for k, o in self.hash_table]
        body = bytearray(self.head)
        struct.pack_into("<III", body, 84, len(hash_table), len(id_table), len(pool))
        body += b"".join(struct.pack("<iI", k, o) for k, o in hash_table)
        body += b"".join(struct.pack("<iI", i, o) for i, o in id_table)
        body += pool
        body += bytes((-len(body)) & 3)
        struct.pack_into("<I", body, 4, len(body) - 8)
        return bytes(body)


def to_text(b):
    """Game bytes -> a Unicode line for editing."""
    out = []
    for c in b:
        if c == BACKSLASH:
            out.append("\\\\")
        elif 0x80 <= c <= 0x9F or c in (9, 10, 13):
            out.append("\\x%02X" % c)
        else:
            out.append(chr(c))
    return "".join(out)


def from_text(s):
    """And back; a character the game's Latin-1 has not is an error."""
    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and s[i + 1:i + 2] == "\\":
            out.append(BACKSLASH)
            i += 2
            continue
        if c == "\\" and s[i + 1:i + 2] in ("x", "X"):
            try:
                out.append(int(s[i + 2:i + 4], 16))
                i += 4
                continue
            except ValueError:
                pass
        o = ord(c)
        if o > 0xFF:
            raise ValueError("%r: the game's font has no %r" % (s, c))
        out.append(o)
        i += 1
    return bytes(out)


def lang_path(data, lang):
    return os.path.join(data, "LANGUAGES", "FE_%s.lang" % lang)


def load_all(data):
    """{LANGUAGE: LangFile} of the game's six."""
    out = {}
    for lang in LANGUAGES:
        p = lang_path(data, lang)
        if os.path.isfile(p):
            out[lang] = LangFile(open(p, "rb").read())
    return out


def export_tsv(data, path):
    """One row an id: id, then the six languages. UTF-8 with a BOM, so Excel opens it right."""
    files = load_all(data)
    langs = [l for l in LANGUAGES if l in files]
    ids = sorted(files[langs[0]].texts)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        w.writerow(["id"] + langs)
        for i in ids:
            w.writerow([i] + [to_text(files[l].texts.get(i, b"")) for l in langs])
    return len(ids)


def read_tsv(path):
    """{LANGUAGE: {id: text}} of a table in export_tsv's form."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t"))
    head = [h.strip().upper() for h in rows[0]]
    out = {l: {} for l in head[1:]}
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        i = int(r[0])
        for l, v in zip(head[1:], r[1:]):
            out[l][i] = v
    return out


def apply(files, table):
    """Put the table's texts into the LangFiles; answers (changed languages, report lines)."""
    changed, lines = set(), []
    for lang, texts in table.items():
        lf = files.get(lang)
        if lf is None:
            lines.append("%s: no such language file, skipped" % lang)
            continue
        for i, s in texts.items():
            if i not in lf.texts:
                lines.append("%s %d: no such text id, skipped (new ids are not possible)" % (lang, i))
                continue
            b = from_text(s)
            if b != lf.texts[i]:
                lines.append("%s %d: %s -> %s" % (lang, i, to_text(lf.texts[i])[:40], s[:40]))
                lf.texts[i] = b
                changed.add(lang)
    return changed, lines


def port_texts(data):
    """The port's language files (data/lang/<LANGUAGE>.txt, recomp/runtime/pclang.cpp): {LANGUAGE: (overrides {id: text},
    its own strings {English: translation})}. An override replaces a game text when the language is loaded."""
    d = os.path.join(data, "lang")
    out = {}
    if not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        if not f.lower().endswith(".txt"):
            continue
        over, own = {}, {}
        with open(os.path.join(d, f), encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\r\n")
                if not line or line[0] in ";@" or "\t" not in line:
                    continue
                a, b = line.split("\t", 1)
                if a.startswith("#"):
                    try:
                        over[int(a[1:])] = b
                    except ValueError:
                        pass
                else:
                    own[a] = b
        out[f[:-4].upper()] = (over, own)
    return out
