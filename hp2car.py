"""A car put together as the game draws it, and the car type records it is put together from.

The parts of GEOMETRY.geo are in two kinds of space. The bodies, the mirrors and the plates are in the car's own space and
draw where they are. The tyres and the brakes are made round their own middle and are placed at the car type's four wheels
(CarTypeInfo.Wheels in GLOBALB's 0x34600 records): the left tyres are the right ones turned round, the left brakes are the
right ones mirrored in y, and a rear with no solid of its own draws the front's. The wipers and the wheel blur only draw while
they run, and the scuffs are damage, so the whole car leaves them out.

A skin n puts <CAR>_SKINn in the place of <CAR>_SKIN1 (bodies A and B, the mirrors) and <CAR>_SKINnB in that of
<CAR>_SKIN1B (bodies C and D, which have SKIN1 renamed to SKIN1B). See docs car-render-info.md and car-type-info.md.
"""

import re
import struct
from dataclasses import dataclass, field

import hp2core as core

CAR_TYPES = 0x00034600
CAR_TYPE_SIZE = 1376
LODS = "ABCD"

# Wheels[i] of CarTypeInfo: front left, front right, rear right, rear left (the y of 0 and 3 is positive, y is left).
WHEEL_NAMES = ("FL", "FR", "RR", "RL")


@dataclass
class CarType:
    index: int                      # record number in the chunk
    offset: int                     # the record's offset in GLOBALB
    raw: bytes

    def _str(self, off, n):
        return self.raw[off:off + n].split(b"\0")[0].decode("latin-1")

    @property
    def name(self):
        return self._str(0, 32)

    @property
    def base_model(self):
        return self._str(32, 32)

    @property
    def num_skins(self):
        return struct.unpack_from("<b", self.raw, 229)[0]

    @property
    def available_skins(self):
        n = max(0, self.num_skins)
        return [b for b in struct.unpack_from("<10b", self.raw, 1348)[:n]]

    @property
    def default_skin(self):
        return struct.unpack_from("<i", self.raw, 1364)[0]

    def wheels(self):
        """[(x, y, z, radius, width)] for FL, FR, RR, RL."""
        return [struct.unpack_from("<5f", self.raw, 288 + 32 * i) for i in range(4)]


def car_type_records(buf):
    """[CarType] of GLOBALB's 0x34600 chunk (the packer's 0x11 filler in front of the records is skipped)."""
    for cid, off, size in core.chunks(buf):
        if cid != CAR_TYPES:
            continue
        p, end = off + 8, off + 8 + size
        while p < end and buf[p] == core.FILLER and (p & 15):
            p += 1
        out = []
        for i in range((end - p) // CAR_TYPE_SIZE):
            o = p + i * CAR_TYPE_SIZE
            out.append(CarType(i, o, bytes(buf[o:o + CAR_TYPE_SIZE])))
        return out
    return []


def car_type(records, car):
    """The record whose geometry is CARS\\<car>: the one named so, else the first whose base model is the car."""
    car = car.upper()
    for r in records:
        if r.name.upper() == car:
            return r
    for r in records:
        if r.base_model.upper() == car:
            return r
    return None


# ---- the placed parts --------------------------------------------------------------------------------------------------------

@dataclass
class Placed:
    label: str                      # object name in the whole car's OBJ
    solid: object                   # core.Solid
    matrix: tuple                   # 3x3 rows, then the offset: (r0, r1, r2, t)
    mirrored: bool = False          # the matrix flips the winding
    skin_parts: bool = True         # skin replacement applies


IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0))


def _solid(geo, name):
    for s in geo.solids():
        if s.full_name == name or s.name == name:
            return s
    return None


def _lod_solid(geo, base, lod):
    """<base>_<lod>, falling back towards A (a part with fewer levels than the body)."""
    for l in LODS[LODS.index(lod)::-1]:
        s = _solid(geo, "%s_%s" % (base, l))
        if s is not None:
            return s
    return None


def assemble(geo, car, ctype, lod="A"):
    """[Placed] of the car as it stands: the body at `lod`, mirrors and plates, four tyres and four brakes."""
    car = car.upper()
    out = []
    body = _solid(geo, "%s_%s" % (car, lod)) or _lod_solid(geo, car, lod)
    if body is not None:
        out.append(Placed(body.full_name, body, IDENTITY))
    for end in ("SIDE_MIRROR_LEFT", "SIDE_MIRROR_RIGHT", "LICENSE_PLATE_FRONT", "LICENSE_PLATE_REAR"):
        s = _solid(geo, "%s_%s" % (car, end))
        if s is not None:
            out.append(Placed(s.full_name, s, IDENTITY))
    if ctype is None:
        return out
    tire_lod = lod if lod in "ABC" else "C"
    for i, (x, y, z, radius, width) in enumerate(ctype.wheels()):
        front = i in (0, 1)
        left = i in (0, 3)
        tire = (_lod_solid(geo, "%s_TIRE_%s" % (car, "FRONT" if front else "REAR"), tire_lod)
                or _lod_solid(geo, "%s_TIRE_FRONT" % car, tire_lod))
        brake = _solid(geo, "%s_BRAKE_%s" % (car, "FRONT" if front else "REAR")) or _solid(geo, "%s_BRAKE_FRONT" % car)
        if tire is not None:
            # the left tyres are the right tyres turned round
            m = ((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (x, y, z)) if left else \
                ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (x, y, z))
            out.append(Placed("WHEEL_%s__%s" % (WHEEL_NAMES[i], tire.full_name), tire, m))
        if brake is not None:
            # the left brakes are the right brakes mirrored in y
            m = ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, 1.0), (x, y, z)) if left else \
                ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (x, y, z))
            out.append(Placed("BRAKE_%s__%s" % (WHEEL_NAMES[i], brake.full_name), brake, m, mirrored=left))
    return out


def transform(m, p):
    r0, r1, r2, t = m
    x, y, z = p
    return (r0[0] * x + r0[1] * y + r0[2] * z + t[0],
            r1[0] * x + r1[1] * y + r1[2] * z + t[1],
            r2[0] * x + r2[1] * y + r2[2] * z + t[2])


def rotate(m, n):
    r0, r1, r2, _ = m
    x, y, z = n
    return (r0[0] * x + r0[1] * y + r0[2] * z, r1[0] * x + r1[1] * y + r1[2] * z, r2[0] * x + r2[1] * y + r2[2] * z)


# ---- skins -------------------------------------------------------------------------------------------------------------------

def skins(car, texture_names):
    """The skin numbers whose <CAR>_SKINn picture is in the packs, in order."""
    pat = re.compile(r"^%s_SKIN(\d+)$" % re.escape(car.upper()))
    out = set()
    for n in texture_names:
        m = pat.match(n.upper())
        if m:
            out.add(int(m.group(1)))
    return sorted(out)


def skin_label(label, car, skin):
    """The texture a skin draws in the place of `label`."""
    if not skin or skin == 1:
        return label
    car = car.upper()
    if label.upper() == car + "_SKIN1":
        return "%s_SKIN%d" % (car, skin)
    if label.upper() == car + "_SKIN1B":
        return "%s_SKIN%dB" % (car, skin)
    return label
