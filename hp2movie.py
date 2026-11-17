"""The game's movies (data\\MOVIES\\*.AVI, video MV30) out to a normal AVI and in from any video.

Export: every frame decoded (key and inter frames), written as an MJPEG AVI with the sound as 16-bit PCM beside it in the
same file, so any player shows it and any editor opens it.

Import: a user's video (anything OpenCV reads: MP4, AVI, MKV, ...) is scaled to the movie's own size, taken at 30 frames
a second, and written as MV30 key frames with the original's layout (JUNK up to the data at 0x800, idx1 after it). A movie
with sound (the INTRO ones) takes a WAV for its sound, or keeps silence of the new length; the sound is the SPU's ADPCM,
stereo, in 0x8000-byte blocks left then right, at 43,617 Hz, as the originals. The size of the file is free: the port
builds its archive from the files as they are at start.
"""

import ctypes
import os
import struct
import sys
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SOUND_RATE = 43617                 # the SPU pitch the player asks for (0xAA66)
BLOCK = 0x8000                     # a channel's block in the stereo stream
_lib = None


def lib():
    global _lib
    if _lib is None:
        for d in (getattr(sys, "_MEIPASS", None), os.path.join(HERE, "codec"), HERE):
            if d and os.path.isfile(os.path.join(d, "hp2codec.dll")):
                _lib = ctypes.CDLL(os.path.join(d, "hp2codec.dll"))
                break
        else:
            raise SystemExit("hp2codec.dll is missing (build it with codec/build.sh)")
        _lib.mv3_decoder_new.restype = ctypes.c_void_p
        _lib.mv3_decoder_new.argtypes = [ctypes.c_int, ctypes.c_int]
        _lib.mv3_decoder_free.argtypes = [ctypes.c_void_p]
        _lib.mv3_decode.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
        _lib.mv3_encode_key.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                        ctypes.c_int]
        _lib.adpcm_decode.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
        _lib.adpcm_encode.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
    return _lib


# ---- ADPCM (shared with the sound tool) ---------------------------------------------------------------------------------

class Adpcm:
    """A channel's decoder or encoder; the history goes on from call to call."""

    def __init__(self):
        self.hist = (ctypes.c_int * 2)(0, 0)

    def decode(self, data):
        n = len(data) // 16
        out = np.zeros(n * 28, np.int16)
        lib().adpcm_decode(bytes(data[:n * 16]), n, out.ctypes.data, self.hist)
        return out

    def encode(self, samples):
        s = np.ascontiguousarray(samples, np.int16)
        n = len(s) // 28
        out = np.zeros(n * 16, np.uint8)
        lib().adpcm_encode(s.ctypes.data, n * 28, out.ctypes.data, self.hist)
        return out.tobytes()


# ---- AVI ----------------------------------------------------------------------------------------------------------------

class Avi:
    """The game's AVI: size, frame rate, and the chunks of 'movi' in order: (tag, offset, size)."""

    def __init__(self, path):
        self.path = path
        b = self.buf = open(path, "rb").read()
        if b[:4] != b"RIFF" or b[8:12] != b"AVI ":
            raise ValueError("%s: not an AVI" % path)
        self.width = self.height = 0
        self.scale, self.rate = 1, 30
        self.fourcc = b""
        self.has_sound = False
        self.chunks = []
        self.movi = None
        self._walk(12, len(b))

    def _walk(self, off, end):
        b = self.buf
        stream = None
        while off + 8 <= end:
            tag, size = b[off:off + 4], struct.unpack_from("<I", b, off + 4)[0]
            body = off + 8
            if tag == b"LIST":
                kind = b[body:body + 4]
                if kind == b"movi":
                    self.movi = off
                    p, e = body + 4, min(body + size, len(b))
                    while p + 8 <= e:
                        t, s = b[p:p + 4], struct.unpack_from("<I", b, p + 4)[0]
                        if t == b"LIST":
                            p += 12
                            continue
                        self.chunks.append((t, p + 8, s))
                        p += 8 + s + (s & 1)
                else:
                    self._walk(body + 4, body + size)
            elif tag == b"strh":
                stream = b[body:body + 4]
                if stream == b"vids":
                    self.fourcc = b[body + 4:body + 8]
                    self.scale, self.rate = struct.unpack_from("<II", b, body + 20)
                elif stream == b"auds":
                    self.has_sound = True
            elif tag == b"strf" and stream == b"vids":
                self.width, self.height = struct.unpack_from("<ii", b, body + 4)
                self.height = abs(self.height)
            off = body + size + (size & 1)

    @property
    def fps(self):
        return self.rate / self.scale if self.scale else 30.0

    def frames(self):
        return [(t, o, s) for t, o, s in self.chunks if t[2:] in (b"db", b"dc")]

    def sound_bytes(self):
        return b"".join(self.buf[o:o + s] for t, o, s in self.chunks if t[2:] == b"wb")


def decode_frames(avi):
    """Yields each frame as an (h, w, 3) RGB array."""
    if avi.fourcc.lower() != b"mv30":
        raise SystemExit("%s: video %r, not MV30" % (avi.path, avi.fourcc))
    L = lib()
    d = L.mv3_decoder_new(avi.width, avi.height)
    try:
        rgb = np.zeros((avi.height, avi.width, 3), np.uint8)
        for t, o, s in avi.frames():
            if L.mv3_decode(d, avi.buf[o:o + s], s, rgb.ctypes.data) != 0:
                raise SystemExit("%s: a frame at 0x%x does not decode" % (avi.path, o))
            yield rgb.copy()
    finally:
        L.mv3_decoder_free(d)


def decode_sound(data):
    """The movie's stereo stream -> (n, 2) int16 at SOUND_RATE."""
    pairs = len(data) // (2 * BLOCK)
    left, right = Adpcm(), Adpcm()
    ls, rs = [], []
    for i in range(pairs):
        p = i * 2 * BLOCK
        ls.append(left.decode(data[p:p + BLOCK]))
        rs.append(right.decode(data[p + BLOCK:p + 2 * BLOCK]))
    if not ls:
        return np.zeros((0, 2), np.int16)
    return np.stack([np.concatenate(ls), np.concatenate(rs)], 1)


def encode_sound(pcm):
    """(n, 2) int16 at SOUND_RATE -> the stereo stream, padded with silence to whole pairs of blocks."""
    per_block = BLOCK // 16 * 28
    n = len(pcm)
    pairs = max(1, -(-n // per_block))
    full = np.zeros((pairs * per_block, 2), np.int16)
    full[:n] = pcm
    left, right = Adpcm(), Adpcm()
    out = bytearray()
    for i in range(pairs):
        seg = full[i * per_block:(i + 1) * per_block]
        out += left.encode(seg[:, 0])
        out += right.encode(seg[:, 1])
    return bytes(out)


def read_wav(path, rate=SOUND_RATE):
    """A WAV as (n, 2) int16 at `rate` (8/16-bit PCM, mono or stereo, any rate; linear resampling)."""
    with wave.open(path, "rb") as w:
        ch, width, r, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        a = np.frombuffer(raw, "<i2").astype(np.float64)
    elif width == 1:
        a = (np.frombuffer(raw, np.uint8).astype(np.float64) - 128) * 256
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        a = ((b[:, 0].astype(np.int32) | b[:, 1].astype(np.int32) << 8 | b[:, 2].astype(np.int32) << 16) << 8 >> 16
             ).astype(np.float64)
    elif width == 4:
        a = np.frombuffer(raw, "<i4").astype(np.float64) / 65536
    else:
        raise SystemExit("%s: %d-byte samples are not supported" % (path, width))
    a = a.reshape(-1, ch)
    if ch == 1:
        a = np.repeat(a, 2, 1)
    a = a[:, :2]
    if r != rate and len(a):
        t = np.arange(int(len(a) * rate / r)) * (r / rate)
        a = np.stack([np.interp(t, np.arange(len(a)), a[:, c]) for c in range(2)], 1)
    return np.clip(np.round(a), -32768, 32767).astype(np.int16)


def write_wav(path, pcm, rate):
    with wave.open(path, "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.ascontiguousarray(pcm, "<i2").tobytes())


# ---- writing AVIs -------------------------------------------------------------------------------------------------------

def _chunk(tag, body):
    return tag + struct.pack("<I", len(body)) + body + (b"\0" if len(body) & 1 else b"")


def _list(kind, *parts):
    body = kind + b"".join(parts)
    return b"LIST" + struct.pack("<I", len(body)) + body


def _strh(kind, handler, scale, rate, length, suggested=0, sample_size=0, w=0, h=0):
    return _chunk(b"strh", kind + handler + struct.pack("<IHHIIIIIIIIhhhh", 0, 0, 0, 0, scale, rate, 0, length,
                                                         suggested, 0xFFFFFFFF, sample_size, 0, 0, w, h))


def _bih(w, h, comp, bits):
    return struct.pack("<IiiHH4sIiiII", 40, w, h, 1, bits, comp, w * h * bits // 8, 0, 0, 0, 0)


class AviWriter:
    """Streams a RIFF AVI to disk: video (and optional sound) chunks, then idx1."""

    def __init__(self, path, w, h, fourcc, fps_scale, fps_rate, nframes, bits=24, sound_strf=None, sound_scale=1,
                 sound_rate=1, sound_length=0, data_at=0x800):
        self.f = open(path, "wb")
        self.index = []
        streams = [_list(b"strl", _strh(b"vids", fourcc.lower() if fourcc == b"MV30" else fourcc, fps_scale, fps_rate,
                                        nframes, 0x40000, 0, w, h),
                         _chunk(b"strf", _bih(w, h, fourcc, bits)))]
        if sound_strf is not None:
            streams.append(_list(b"strl", _strh(b"auds", b"\0\0\0\0", sound_scale, sound_rate, sound_length, 0x10000,
                                                struct.unpack_from("<H", sound_strf, 12)[0]),
                                 _chunk(b"strf", sound_strf)))
        us = int(1e6 * fps_scale / fps_rate)
        avih = _chunk(b"avih", struct.pack("<IIIIIIIIIIIIII", us, 0, 0, 0x10, nframes, 0, len(streams), 0x40000, w, h,
                                           0, 0, 0, 0))
        hdrl = _list(b"hdrl", avih, *streams)
        head = b"RIFF\0\0\0\0AVI " + hdrl
        # JUNK so that the movi list's data starts at data_at
        movi_head = 12
        pad = data_at - (len(head) + 8 + movi_head)
        if pad < 0:
            pad = (-(len(head) + 8 + movi_head)) % 2048
        head += b"JUNK" + struct.pack("<I", pad) + b"\0" * pad
        self.movi_at = len(head)
        self.f.write(head + b"LIST\0\0\0\0movi")
        self.pos = self.movi_at + 12

    def chunk(self, tag, data, key=True):
        self.index.append((tag, 0x10 if key else 0, self.pos - (self.movi_at + 8), len(data)))
        self.f.write(tag + struct.pack("<I", len(data)) + data + (b"\0" if len(data) & 1 else b""))
        self.pos += 8 + len(data) + (len(data) & 1)

    def close(self):
        movi_size = self.pos - (self.movi_at + 8)
        idx = b"".join(t + struct.pack("<III", fl, o, s) for t, fl, o, s in self.index)
        self.f.write(b"idx1" + struct.pack("<I", len(idx)) + idx)
        end = self.f.tell()
        self.f.seek(4)
        self.f.write(struct.pack("<I", end - 8))
        self.f.seek(self.movi_at + 4)
        self.f.write(struct.pack("<I", movi_size))
        self.f.close()


def pcm_strf(rate, channels=2):
    return struct.pack("<HHIIHH", 1, channels, rate, rate * channels * 2, channels * 2, 16)


# ---- export -------------------------------------------------------------------------------------------------------------

def export_movie(src, out_avi, quality=90, log=print):
    """The game's movie -> an MJPEG AVI (and its sound as PCM in the same file)."""
    from PIL import Image
    import io
    avi, nframes, source = frames_any(src)
    frames = range(nframes)
    pcm = decode_sound(avi.sound_bytes()) if avi.has_sound else None
    sound_strf = pcm_strf(SOUND_RATE) if pcm is not None else None
    wr = AviWriter(out_avi, avi.width, avi.height, b"MJPG", avi.scale, avi.rate, len(frames),
                   sound_strf=sound_strf, sound_scale=4, sound_rate=SOUND_RATE * 4,
                   sound_length=len(pcm) if pcm is not None else 0)
    per_frame = SOUND_RATE * avi.scale / avi.rate
    done = 0
    for i, rgb in enumerate(source):
        if pcm is not None:
            upto = int(round((i + 1) * per_frame)) if i < len(frames) - 1 else len(pcm)
            if upto > done:
                wr.chunk(b"01wb", pcm[done:upto].tobytes())
                done = upto
        buf = io.BytesIO()
        Image.fromarray(rgb, "RGB").save(buf, "JPEG", quality=quality)
        wr.chunk(b"00dc", buf.getvalue())
    wr.close()
    log("%s: %d frames %dx%d at %.3f fps%s -> %s" % (os.path.basename(src), len(frames), avi.width, avi.height, avi.fps,
                                                     ", sound %.1f s" % (len(pcm) / SOUND_RATE) if pcm is not None
                                                     else "", out_avi))


# ---- import -------------------------------------------------------------------------------------------------------------

def read_video(path, w, h, fps=30.0, log=print):
    """Frames of any video OpenCV reads, scaled to w x h and taken at fps (nearest frame in time)."""
    try:
        import cv2
    except ImportError:
        raise SystemExit("reading videos needs OpenCV (pip install opencv-python)")
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit("%s: OpenCV cannot open it" % path)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or fps
    frames, t_next, i = [], 0.0, 0
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        t = i / src_fps
        i += 1
        while t + 0.5 / src_fps >= t_next:
            frames.append(cv2.resize(bgr, (w, h), interpolation=cv2.INTER_AREA)[:, :, ::-1].copy())
            t_next += 1.0 / fps
            if t + 0.5 / src_fps < t_next:
                break
    cap.release()
    log("%s: %d frames at %.2f fps -> %d frames at %g fps, %dx%d" % (os.path.basename(path), i, src_fps,
                                                                     len(frames), fps, w, h))
    return frames


def encode_frame(rgb, quality):
    h, w = rgb.shape[:2]
    rgb = np.ascontiguousarray(rgb, np.uint8)
    cap = w * h * 4 + 4096
    out = np.zeros(cap, np.uint8)
    n = lib().mv3_encode_key(rgb.ctypes.data, w, h, quality, out.ctypes.data, cap)
    if n < 0:
        raise SystemExit("a frame does not fit (%d bytes)" % -n)
    return out[:n].tobytes()


def import_movie(target, video, out_path, wav=None, quality=88, log=print):
    """Write out_path: the game's movie `target` (its size, rate and sound layout) with the pictures of `video`."""
    old = Avi(target)
    w, h = old.width, old.height
    if w % 16 or h % 16:
        raise SystemExit("%s: %dx%d is not in macroblocks" % (target, w, h))
    fps = old.fps or 30.0
    frames = read_video(video, w, h, fps, log)
    if not frames:
        raise SystemExit("%s: no frames" % video)
    stream = None
    if old.has_sound:
        if wav:
            pcm = read_wav(wav)
        else:
            pcm = np.zeros((int(len(frames) / fps * SOUND_RATE), 2), np.int16)
            log("no WAV given: the movie's sound is silence")
        stream = encode_sound(pcm)
    old_strf = None
    if old.has_sound:
        # the originals' audio strf, as they have it (it says PCM, mono, 8-bit; the player ignores it)
        b = old.buf
        p = b.find(b"auds")
        q = b.find(b"strf", p)
        old_strf = b[q + 8:q + 8 + struct.unpack_from("<I", b, q + 4)[0]]
    wr = AviWriter(out_path + ".new", w, h, b"MV30", old.scale, old.rate, len(frames), bits=24,
                   sound_strf=old_strf, sound_scale=1, sound_rate=max(1, len(stream or b"") * old.rate //
                                                                          max(1, len(frames) * old.scale)),
                   sound_length=len(stream or b""))
    sp = 0
    if stream:
        first = min(len(stream), 3 * 2 * BLOCK)         # the originals preload about three pairs before frame 0
        wr.chunk(b"01wb", stream[:first])
        sp = first
    per_frame = 0 if not stream else -(-max(0, len(stream) - sp) // len(frames))
    per_frame = (per_frame + 15) & ~15
    total = 0
    for i, rgb in enumerate(frames):
        data = encode_frame(rgb, quality)
        total += len(data)
        wr.chunk(b"00db", data)
        if stream and sp < len(stream):
            n = len(stream) - sp if i == len(frames) - 1 else min(per_frame, len(stream) - sp)
            wr.chunk(b"01wb", stream[sp:sp + n])
            sp += n
    wr.close()
    os.replace(out_path + ".new", out_path)
    log("%s: %d key frames, %.1f MB of picture%s" % (os.path.basename(out_path), len(frames), total / 1048576,
                                                    ", sound %.1f s" % (len(stream) / 32 * 28 / SOUND_RATE)
                                                    if stream else ""))


def frames_any(path):
    """(Avi, frame count, a generator of (h, w, 3) RGB frames) for MV30 (the game's codec, decoded here) or any other
    codec OpenCV's FFmpeg knows (the disc's one MVDV movie is MidiVid VQ)."""
    avi = Avi(path)
    if avi.fourcc.lower() == b"mv30":
        return avi, len(avi.frames()), decode_frames(avi)
    try:
        import cv2
    except ImportError:
        raise SystemExit("%s: %r needs OpenCV" % (path, avi.fourcc))
    cap = cv2.VideoCapture(path, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        raise SystemExit("%s: %r is a codec this build cannot decode" % (path, avi.fourcc))

    def gen():
        try:
            while True:
                ok, bgr = cap.read()
                if not ok:
                    break
                yield bgr[:, :, ::-1].copy()
        finally:
            cap.release()
    return avi, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or len(avi.frames()), gen()
