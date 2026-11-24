"""A car's characteristics as the menus show them, and the few physics numbers that make them.

The car select screen's name and specs come from the game's CarLanguageInfo table in the ELF (SLUS_203.62, 0x30d578, 50 rows
of 28 bytes: s32 car type, then the text ids of 0-60, top speed mph, top speed km/h, BHP, full name, short name). The ids are
texts of the language files, so changing them is changing texts (all six languages at once here). A car type without a row
of its own (the HP versions, traffic) shows the first row's. The physics side is hp2physics' fields, with two multipliers on
top: power (the torque curve) and grip (the tyres' friction).
"""

import os
import struct

import hp2physics as ph
import hp2text as tx

ELF = "SLUS_203.62"
LANG_INFO = 0x30D578
ROWS = 50
SPEC_KEYS = ("zero_to_60", "top_mph", "top_kph", "bhp", "full_name", "short_name")
SPEC_TITLES = ("0-60 mph (s)", "Top speed (mph)", "Top speed (km/h)", "Power (BHP)", "Full name", "Short name")


def _elf_offset(elf, vaddr):
    phoff = struct.unpack_from("<I", elf, 0x1C)[0]
    n, size = struct.unpack_from("<HH", elf, 0x2C)[0], struct.unpack_from("<H", elf, 0x2A)[0]
    n = struct.unpack_from("<H", elf, 0x2C)[0]
    for i in range(n):
        t, off, va, pa, fs, ms = struct.unpack_from("<6I", elf, phoff + i * size)
        if t == 1 and va <= vaddr < va + fs:
            return off + vaddr - va
    raise ValueError("0x%x is not in the ELF's file" % vaddr)


def spec_rows(data):
    """{car type: {key: text id}} from the ELF; type -1 is the fallback row."""
    elf = open(os.path.join(data, ELF), "rb").read()
    o = _elf_offset(elf, LANG_INFO)
    out = {}
    for r in range(ROWS):
        row = struct.unpack_from("<i6I", elf, o + 28 * r)
        out.setdefault(row[0], dict(zip(SPEC_KEYS, row[1:])))
    return out


class Stats:
    """One car type's characteristics: the texts (by id) and its CarType record."""

    def __init__(self, data):
        self.data = data
        self.langs = tx.load_all(data)
        self.rows = spec_rows(data)
        self.gb_path = os.path.join(data, "GLOBAL", "GLOBALB.BUN")
        self.gb = open(self.gb_path, "rb").read()
        self.records = ph.records(self.gb)

    def car_names(self):
        return [r.name for r in self.records]

    def record(self, car):
        return next(r for r in self.records if r.name == car)

    def row_of(self, car):
        """(the row's ids, True if the car has a row of its own)."""
        r = self.record(car)
        t = struct.unpack_from("<i", r.raw, 1332)[0]
        if t in self.rows:
            return self.rows[t], True
        return self.rows.get(-1, {}), False

    def texts(self, car, lang="ENGLISH"):
        ids, own = self.row_of(car)
        lf = self.langs.get(lang)
        return {k: tx.to_text(lf.texts.get(i, b""), lf.cyrillic) if lf else "" for k, i in ids.items()}, own

    def shared_with(self, car):
        """Other car types showing the same texts (by the fallback, or a shared row)."""
        ids, _ = self.row_of(car)
        return [r.name for r in self.records if r.name != car and self.row_of(r.name)[0] == ids]

    def set_texts(self, car, values):
        """values {key: text}: written into every language's file (in memory). Answers the changed languages."""
        ids, _ = self.row_of(car)
        changed = set()
        for key, s in values.items():
            i = ids.get(key)
            if i is None:
                continue
            for lang, lf in self.langs.items():
                b = tx.from_text(s, lf.cyrillic)
                if i in lf.texts and lf.texts[i] != b:
                    lf.texts[i] = b
                    changed.add(lang)
        return changed

    def physics(self, car):
        v = ph.read_values(self.record(car).raw)
        return v

    def apply_physics(self, car, values, power=1.0, grip=1.0):
        """values {field: value} plus the power and grip multipliers -> the new GLOBALB bytes (self.gb updated)."""
        v = dict(values)
        cur = ph.read_values(self.record(car).raw)
        if abs(power - 1.0) > 1e-9:
            for k in range(9):
                v["Torque%d" % k] = cur["Torque%d" % k] * power
        if abs(grip - 1.0) > 1e-9:
            for end in ("Front", "Rear"):
                for f in ("StaticFriction", "DynamicFriction"):
                    key = "Tire%s.%s" % (end, f)
                    v[key] = cur[key] * grip
        self.gb, lines = ph.apply(self.gb, {car: v})
        self.records = ph.records(self.gb)
        return lines

    def write(self, langs_changed, physics_changed):
        import hp2assets as cli
        for lang in langs_changed:
            cli.replace_file(tx.lang_path(self.data, lang), self.langs[lang].build())
        if physics_changed:
            cli.replace_file(self.gb_path, self.gb)
