"""Car physics: the CarTypeInfo records of GLOBAL\\GLOBALB.BUN (chunk 0x34600, 64 records of 1376 bytes), field by field.

Fields from NFSHP2-3DS's docs/formats/car-type-info.md (the .mdebug layout) and reNFSHP2's carinfo.cpp (github.com/Romalu86/reNFSHP2), checked against the disc. Only the numbers the
physics reads are offered for editing; names, paths, the type number and the skins stay as they are. The body's inertia
tensor is made again from the mass and the size when either changes (on the disc it is exactly Ixx = m(Y²+Z²)/12,
Iyy = m(X²+Z²)/12, Izz = 2m(X²+Y²)/12). The menus' spec lines (0-60, top speed, BHP) are texts, in the language files.
"""

import json
import struct

import hp2car as carinfo

# (offset, struct format, name, group, note)
FIELDS = []


def _f(off, fmt, name, group, note=""):
    FIELDS.append((off, fmt, name, group, note))


_f(228, "b", "HighPerformance", "General", "1 on the HP versions")
_f(230, "b", "CarClass", "General", "class 0..9")
for i, w in enumerate(("FL", "FR", "RR", "RL")):
    base = 288 + 32 * i
    _f(base, "f", "Wheel%s.X" % w, "Wheels", "forward, m")
    _f(base + 4, "f", "Wheel%s.Y" % w, "Wheels", "left, m")
    _f(base + 8, "f", "Wheel%s.Z" % w, "Wheels", "up, m")
    _f(base + 12, "f", "Wheel%s.Radius" % w, "Wheels", "m")
    _f(base + 16, "f", "Wheel%s.Width" % w, "Wheels", "m")
_f(272, "f", "CenterOfGravity.X", "Body", "m")
_f(276, "f", "CenterOfGravity.Y", "Body", "m")
_f(280, "f", "CenterOfGravity.Z", "Body", "m")
_f(480, "f", "Mass", "Body", "tonnes")
_f(484, "f", "LengthX", "Body", "m, the box the physics uses")
_f(488, "f", "WidthY", "Body", "m")
_f(492, "f", "HeightZ", "Body", "m")
for i, end in enumerate(("Front", "Rear")):
    base = 416 + 32 * i
    _f(base, "f", "Tire%s.MaxSlipAngle" % end, "Tyres", "degrees")
    _f(base + 4, "f", "Tire%s.MaxLoad" % end, "Tyres")
    _f(base + 8, "f", "Tire%s.ForceScale" % end, "Tyres")
    _f(base + 12, "f", "Tire%s.StaticFriction" % end, "Tyres", "grip")
    _f(base + 16, "f", "Tire%s.DynamicFriction" % end, "Tyres", "grip when sliding")
for i, end in enumerate(("Front", "Rear")):
    base = 560 + 32 * i
    _f(base, "f", "Susp%s.Progression" % end, "Suspension")
    _f(base + 4, "f", "Susp%s.Stiffness" % end, "Suspension")
    _f(base + 8, "f", "Susp%s.DampingRebound" % end, "Suspension")
    _f(base + 12, "f", "Susp%s.DampingCompression" % end, "Suspension")
    _f(base + 16, "f", "Susp%s.SwayBar" % end, "Suspension")
    _f(base + 20, "f", "Susp%s.BumpStopUp" % end, "Suspension", "m")
    _f(base + 24, "f", "Susp%s.BumpStopDown" % end, "Suspension", "m")
    _f(base + 28, "f", "Susp%s.MaxRenderingCompression" % end, "Suspension", "m, the wheel drawn")
_f(624, "f", "ShiftUpPoint", "Gearbox", "part of the red line")
_f(628, "f", "ShiftDownRPM", "Gearbox")
_f(632, "f", "FinalDriveFront", "Gearbox")
_f(636, "f", "FinalDriveRear", "Gearbox")
_f(640, "f", "TorqueSplit", "Gearbox", "rear's share: 1 rear drive, 0 front, between: four wheel")
_f(644, "f", "ClutchStiffness", "Gearbox")
_f(648, "i", "NumGears", "Gearbox", "1..6")
_f(652, "f", "ShiftSpeed", "Gearbox")
for i, g in enumerate(("Reverse", "Neutral", "1", "2", "3", "4", "5", "6")):
    _f(656 + 4 * i, "f", "Gear%s" % g, "Gearbox", "ratio")
_f(688, "f", "IdleRPM", "Engine")
_f(692, "f", "RedLineRPM", "Engine")
_f(696, "f", "MaxRPM", "Engine", "the limiter starts 100 below")
_f(700, "f", "MomentOfInertia", "Engine")
for i in range(9):
    _f(704 + 4 * i, "f", "Torque%d" % i, "Engine", "torque curve, idle to max RPM evenly")
for i in range(3):
    _f(740 + 4 * i, "f", "EngineBraking%d" % i, "Engine")
_f(752, "f", "Drag", "Aero")
_f(756, "f", "FrontDownforce", "Aero")
_f(760, "f", "RearDownforce", "Aero")
_f(764, "f", "AutoBalanceDownforce", "Aero")
_f(768, "f", "Steering", "Control")
_f(772, "f", "Brake", "Control")
_f(776, "f", "EBrake", "Control", "hand brake")
_f(780, "f", "BrakeBias", "Control", "front's share")
_f(784, "f", "YawControl", "Control")
_f(788, "f", "YawControlNFS", "Control")
_f(792, "f", "MaxZMomentAcc", "Control")
_f(796, "f", "MaxZMomentAccExtreme", "Control")
_f(800, "f", "SpeedLimiter", "Control", "top speed, mph")

GROUPS = []
for _, _, _, g, _ in FIELDS:
    if g not in GROUPS:
        GROUPS.append(g)
BY_NAME = {f[2]: f for f in FIELDS}


def read_values(rec):
    """{name: value} of a CarType record's raw bytes."""
    out = {}
    for off, fmt, name, _, _ in FIELDS:
        v = struct.unpack_from("<" + fmt, rec, off)[0]
        out[name] = round(v, 7) if fmt == "f" else v
    return out


def write_values(rec, values):
    """The record with these {name: value} put in; the inertia made again if the mass or the size changed."""
    b = bytearray(rec)
    old = read_values(rec)
    for name, v in values.items():
        if name not in BY_NAME:
            raise ValueError("no field %s" % name)
        off, fmt, _, _, _ = BY_NAME[name]
        if fmt == "f":
            struct.pack_into("<f", b, off, float(v))
        else:
            v = int(v)
            if name == "NumGears" and not 1 <= v <= 6:
                raise ValueError("NumGears must be 1 to 6")
            struct.pack_into("<" + fmt, b, off, v)
    new = read_values(bytes(b))
    if any(abs(new[k] - old[k]) > 1e-9 for k in ("Mass", "LengthX", "WidthY", "HeightZ")):
        m, x, y, z = new["Mass"], new["LengthX"], new["WidthY"], new["HeightZ"]
        struct.pack_into("<f", b, 496, m * (y * y + z * z) / 12)
        struct.pack_into("<f", b, 496 + 20, m * (x * x + z * z) / 12)
        struct.pack_into("<f", b, 496 + 40, 2 * m * (x * x + y * y) / 12)
    return bytes(b)


def records(buf):
    return [r for r in carinfo.car_type_records(buf) if r.name]


def export_json(buf, path, cars=None):
    """{car: {group: {field: value}}} for the cars (all by default)."""
    out = {}
    for r in records(buf):
        if cars and r.name.upper() not in cars:
            continue
        vals = read_values(r.raw)
        out[r.name] = {g: {n: vals[n] for _, _, n, gg, _ in FIELDS if gg == g} for g in GROUPS}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    return len(out)


def apply(buf, changes):
    """changes {car: {field: value}} (groups may nest them) -> (the new GLOBALB, [lines of what changed])."""
    b = bytearray(buf)
    lines = []
    recs = {r.name.upper(): r for r in records(buf)}
    for car, fields in changes.items():
        r = recs.get(car.upper())
        if r is None:
            lines.append("%s: no such car type, skipped" % car)
            continue
        flat = {}
        for k, v in fields.items():
            if isinstance(v, dict):
                flat.update(v)
            else:
                flat[k] = v
        old = read_values(r.raw)
        diff = {k: v for k, v in flat.items() if k in old and abs(float(v) - float(old[k])) > 1e-6}
        unknown = [k for k in flat if k not in old]
        for k in unknown:
            lines.append("%s: no field %s, skipped" % (car, k))
        if not diff:
            continue
        b[r.offset:r.offset + len(r.raw)] = write_values(r.raw, diff)
        for k, v in diff.items():
            lines.append("%s.%s: %s -> %s" % (r.name, k, old[k], v))
    return bytes(b), lines
