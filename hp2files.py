"""Every file of the install, and whether the game asks for it.

data\\index.txt lists the disc's files as "<hash> <path>": the hash is bStringHash of the name the game asks the disc for
(GLOBAL\\GLOBALB.LZC; the installer unpacked it to GLOBAL/GLOBALB.BUN), and the port finds a file by that hash. So a file is
used when some name the game can ask for hashes to its line. Those names come from the program's own strings (SLUS_203.62:
"TRACKS\\TRACKB%d.LZC", "Sound\\Speech\\%sBAN.pck", "NIS\\%s.cam", ...), filled with the numbers 0..999 and with every word
of the program and of the car records (car names, engine sound banks), and from the car records' geometry paths. A file
of the index that none of them hashes to is one the game never asks for (the demo disc's left-overs, test files).
Files beside the index are the port's own (data\\lang read by the port, data\\text written for reading, ...).
"""

import os
import re
import struct

import hp2core as core

KIND = {
    ".geo": ("car geometry", "Cars"), ".tex": ("texture pack", "Textures"), ".BUN": ("bundle", "Textures"),
    ".lang": ("texts", "Texts"), ".AVI": ("movie", "Movies"), ".avi": ("movie", "Movies"), ".MSH": ("sound bank index", "Sound"),
    ".MSB": ("sound bank", "Sound"), ".JBC": ("music", "Sound"), ".PCK": ("speech", "Sound"), ".pck": ("speech", "Sound"),
    ".sndbank": ("sound (unused build file)", ""), ".replay": ("demo replay", ""), ".markers": ("markers", ""),
    ".CAM": ("cut-scene camera", ""), ".nis": ("cut-scene", ""), ".CTB": ("engine sound curves", ""),
    ".LTB": ("engine sound curves", ""), ".EVT": ("speech events", ""), ".IRX": ("PS2 module", ""),
    ".62": ("the game's program", ""), ".TAG": ("disc tag", ""), ".ICO": ("PS2 icon", ""), ".table": ("speech table", ""),
}
PORT_FILES = {"index.txt": "the port: the disc's index", "lang": "the port: its translations and text overrides",
              "text": "written by the installer for reading; the game does not read it", "ui": "the port: its cursor"}


DEAD = {
    "SOUND/JUKEBOX.JBC": "the program opens only JukeboxM.JBC (and the demo disc's)",
    "SOUND/SNDHDR.SNDBANK": "a build file, no reference in the program",
    "SOUND/SNDDATA.SNDBANK": "a build file, no reference in the program",
    "KEY.TXT": "a note of the disc", "NFS.TAG": "the program asks for PAL.TAG, not this",
}


def read_index(data):
    out = []
    p = os.path.join(data, "index.txt")
    for line in open(p, encoding="latin-1"):
        line = line.strip()
        if not line or " " not in line:
            continue
        h, rel = line.split(" ", 1)
        try:
            out.append((int(h, 16), rel))
        except ValueError:
            pass
    return out


def _strings(b, n=2):
    return [x.decode("latin-1") for x in re.findall(rb"[ -~]{%d,}" % n, b)]


def requested(data, log=None):
    """{hash: name} of every name the game can ask the disc for, as far as its program and its records say."""
    elf = open(os.path.join(data, "SLUS_203.62"), "rb").read()
    strs = _strings(elf, 2)
    words = set(w for s in strs for w in re.findall(r"[A-Za-z0-9_ ]{1,40}", s))
    words |= set(s for s in strs if len(s) <= 40)
    # the car records: names, base models, geometry paths, engine sound banks
    paths = set()
    gb = os.path.join(data, "GLOBAL", "GLOBALB.BUN")
    if os.path.isfile(gb):
        import hp2car
        for r in hp2car.car_type_records(open(gb, "rb").read()):
            raw = r.raw
            for off in (0, 32, 816):
                w = raw[off:off + 32].split(b"\0")[0].decode("latin-1")
                if w:
                    words.add(w)
            for off in (64, 96, 128, 160):
                w = raw[off:off + 32].split(b"\0")[0].decode("latin-1")
                if w:
                    paths.add(w)
    for l in ("ENGLISH", "FRENCH", "GERMAN", "ITALIAN", "SPANISH", "SWEDISH", "English", "French", "German", "Italian",
              "Spanish", "Swedish"):
        words.add(l)
    pats = [s for s in strs if "\\" in s or re.search(r"\.(bin|bun|lzc|avi|msh|msb|jbc|pck|evt|cam|ctb|ltb|tag)\b", s, re.I)]
    names = set(paths)
    for s in pats:
        s = s.lstrip("aA") if s.startswith("aATRACKS") else s
        if "%" not in s:
            names.add(s)
            continue
        parts = re.split(r"(%[0-9]*[sd])", s)
        cands = [""]
        for p in parts:
            if p.startswith("%") and p.endswith("d"):
                width = p[1:-1]
                nums = [("%0" + width + "d") % k if width else str(k) for k in range(1000)]
                cands = [c + n for c in cands for n in nums][:200000]
            elif p.startswith("%") and p.endswith("s"):
                cands = [c + w for c in cands for w in words][:400000]
            else:
                cands = [c + p for c in cands]
        names.update(cands)
    # sound banks: "SOUND\<name>.MSH/.MSB" from the bank names among the words
    for w in words:
        if 2 <= len(w) <= 20 and re.fullmatch(r"[A-Za-z0-9_]+", w):
            for ext in (".MSH", ".MSB", ".msh", ".msb"):
                names.add("SOUND\\" + w + ext)
            names.add("NIS\\" + w + ".bin")
            names.add("NIS\\" + w + ".cam")
            names.add("REPLAY\\" + w)
    out = {}
    for n in sorted(names):
        for v in (n, n.upper()):
            try:
                out.setdefault(core.bhash(v), v)
            except UnicodeEncodeError:
                pass
    if log:
        log("%d names the game can ask for" % len(names))
    return out


def real_name(rel, h, asked):
    """The name the game asks for a file that the install keeps by its hash (unnamed_<hash>...), or None."""
    if "UNNAMED" not in rel.upper() and not rel.upper().startswith("UNKNOWN/"):
        return None
    n = asked.get(h)
    return n.replace("\\", "/") if isinstance(asked, dict) and n else None


class Entry:
    def __init__(self, rel, size, status, kind, tab):
        self.rel, self.size, self.status, self.kind, self.tab = rel, size, status, kind, tab
        self.real = None            # the name the game asks for it, when the install keeps it by its hash


def survey(data, log=None):
    """[Entry] of every file under data, with its status: used, not asked for, empty, the port's, a backup."""
    index = read_index(data)
    asked = requested(data, log)
    seen = _seen()
    seen_families = set(re.sub(r"\d+", "#", s) for s in seen)
    in_index = {}
    for h, rel in index:
        in_index.setdefault(rel.replace("\\", "/").upper(), []).append(h)
    out = []
    for root, dirs, files in os.walk(data):
        for f in sorted(files):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, data).replace("\\", "/")
            size = os.path.getsize(p)
            ext = os.path.splitext(f)[1]
            kind, tab = KIND.get(ext, ("", ""))
            top = rel.split("/")[0]
            if f.endswith(".orig"):
                out.append(Entry(rel, size, "backup: the disc's, kept by the mod manager", "backup", ""))
                continue
            hs = in_index.get(rel.upper())
            fam = re.sub(r"\d+", "#", rel.upper())
            if hs is None:
                status = PORT_FILES.get(top) or PORT_FILES.get(f) or "not in the disc's index: the game cannot see it"
            elif size == 0:
                status = "empty on the disc"
            elif any(h in asked for h in hs):
                status = "used: the program names it"
            elif rel.upper() in seen:
                status = "used: read in the port's runs"
            elif fam in seen_families:
                status = "used: its numbered family is read"
            elif "UNNAMED" in rel.upper() or rel.upper() in DEAD:
                status = "unused: " + DEAD.get(rel.upper(), "no name the game builds hashes to it")
            else:
                status = "not seen in the port's runs (may be used: cut-scenes, regions, demos)"
            e = Entry(rel, size, status, kind, tab)
            # a file the install keeps by its hash (no name was known to it), named by what the game asks for
            e.real = next((real_name(rel, h, asked) for h in (hs or ()) if real_name(rel, h, asked)), None)
            out.append(e)
    return out


def _seen():
    """The files the port read in its test runs (seen_files.txt: the five recorded demos, 2026-11-14, HP2_FILELOG)."""
    import sys
    here = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(here, "seen_files.txt")
    if not os.path.isfile(p):
        return set()
    return set(l.strip().upper() for l in open(p, encoding="latin-1") if l.strip())
