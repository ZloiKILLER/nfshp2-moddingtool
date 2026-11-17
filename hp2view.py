"""The car viewer: the car put together as the game draws it, in an OpenGL window inside Tk (PyOpenGL and pyopengltk).

Left drag turns the car, right drag or the wheel zooms, middle drag moves it. The light is an approximation of the game's:
the strips with normals are lit by a sun and a fill light and darkened by their vertex colour, the others take their vertex
colour; there are no reflections. The pictures, the skins, the slots the game fills at run time and the levels of detail are
the game's.
"""

import math
import tkinter as tk
from tkinter import ttk

import numpy as np

import hp2car as carinfo
import hp2core as core
import hp2model as model

try:
    from OpenGL import GL, GLU
    from pyopengltk import OpenGLFrame
    HAVE_GL = True
    try:
        # pyopengltk asks Windows for a 16-bit depth buffer: over a track's kilometres the road and the ground beside it
        # then fight for the same depth and show through each other in the distance. 24 bits, as games have.
        import pyopengltk.win32 as _w32
        _w32.pfd.cDepthBits = 24
    except (ImportError, AttributeError):
        pass
except ImportError:          # the window says so instead of the view
    HAVE_GL = False
    OpenGLFrame = tk.Frame

SUN = np.array([0.45, 0.35, 0.82], np.float32)
SUN /= np.linalg.norm(SUN)
FILL = np.array([-0.5, -0.6, 0.3], np.float32)
FILL /= np.linalg.norm(FILL)


class Batch:
    """Triangles of one picture: positions (n,3), uv (n,2), colours (n,4) float32; rgba the picture or None."""

    def __init__(self, key, rgba, blend):
        self.key, self.rgba, self.blend = key, rgba, blend
        self.pos, self.uv, self.col = [], [], []

    def done(self):
        self.pos = np.asarray(self.pos, np.float32).reshape(-1, 3)
        self.uv = np.asarray(self.uv, np.float32).reshape(-1, 2)
        self.col = np.asarray(self.col, np.float32).reshape(-1, 4)
        return self


def build_scene(placed, names, rgba_of, car, skin):
    """[Batch] of the placed parts. rgba_of(label) gives the picture a material shows (skin and slots resolved) or None."""
    batches = {}
    pictures = {}
    tris = 0
    for p in placed:
        s, m = p.solid, p.matrix
        for e, st in zip(s.entries, s.strips):
            h = s.textures[e.texture] if 0 <= e.texture < len(s.textures) else None
            label = carinfo.skin_label(model.texture_label(h, names), car, skin)
            if label not in pictures:
                pictures[label] = rgba_of(label)
            rgba = pictures[label]
            blend = rgba is not None and int(rgba[..., 3].min()) < 250
            b = batches.get(label)
            if b is None:
                b = batches[label] = Batch(label, rgba, blend)
            lit = st.verts[0].normal is not None
            vp, vc, vt = [], [], []
            for v in st.verts:
                vp.append(carinfo.transform(m, v.pos))
                vt.append(v.st)
                c = np.array([v.rgba & 31, v.rgba >> 5 & 31, v.rgba >> 10 & 31], np.float32) * (8 / 128.0)
                if lit:
                    n = np.array(carinfo.rotate(m, v.normal), np.float32)
                    ln = float(np.linalg.norm(n))
                    if ln > 0:
                        n /= ln
                        light = 0.38 + 0.62 * max(0.0, float(n @ SUN)) + 0.18 * max(0.0, float(n @ FILL))
                    else:
                        light = 0.8
                    shade = 0.45 + 0.55 * min(1.0, float(c.mean()))
                    c = np.full(3, light * shade, np.float32)
                vc.append((*np.minimum(c, 1.0), 1.0))
            for a, bb, cc in st.triangles():
                order = (a, cc, bb) if p.mirrored else (a, bb, cc)
                for i in order:
                    b.pos.append(vp[i])
                    b.uv.append(vt[i])
                    b.col.append(vc[i])
                tris += 1
    out = [b.done() for b in batches.values() if b.pos]
    return out, tris


class GLView(OpenGLFrame):
    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.batches = []
        self.textures = {}
        self.stale = []
        self.yaw, self.pitch, self.dist = 35.0, 18.0, 7.0
        self.target = [0.0, 0.0, 0.5]
        self.wire = False
        self.width, self.height = 640, 480
        # first person (a track's driver's seat): the eye and where it looks, instead of the orbit round the target
        self.fp = False
        self.eye = [0.0, 0.0, 0.0]
        self.fyaw, self.fpitch = 0.0, 0.0
        self.exclude = 0            # batches whose excl shares a bit with it are not drawn (a track's other direction)
        self.bind("<ButtonPress>", self.press)
        self.bind("<B1-Motion>", lambda e: self.drag(e, "turn"))
        self.bind("<B2-Motion>", lambda e: self.drag(e, "move"))
        self.bind("<B3-Motion>", lambda e: self.drag(e, "zoom"))
        self.bind("<MouseWheel>", self.wheel)
        self.bind("<KeyPress>", self.key)
        self.last = (0, 0)

    def set_batches(self, batches, keep_camera=False):
        self.stale += list(self.textures.values())
        self.textures = {}
        for b in getattr(self, "batches", []):
            if getattr(b, "vbo", None):
                self.stale_vbo = getattr(self, "stale_vbo", []) + list(b.vbo)
                b.vbo = None
        self.batches = batches
        if batches:
            lo = np.min([b.pos.min(0) for b in batches], 0)
            hi = np.max([b.pos.max(0) for b in batches], 0)
            self.extent = float(np.linalg.norm(hi - lo))
            if not keep_camera:
                self.target = list((lo + hi) / 2)
                self.dist = max(2.0, self.extent * 1.15)
        self.show()

    def key(self, e):
        """Flying: W/S forward and back along the view, A/D aside, Q/E down and up; shift goes ten times faster."""
        if self.fp:
            return                  # the window that put the view in first person moves it
        step = max(0.05, self.dist * 0.04) * (10 if e.state & 1 else 1)
        yr, pr = math.radians(self.yaw), math.radians(self.pitch)
        fwd = (-math.cos(pr) * math.cos(yr), -math.cos(pr) * math.sin(yr), -math.sin(pr))
        side = (-math.sin(yr), math.cos(yr), 0.0)
        d = {"w": fwd, "s": tuple(-x for x in fwd), "a": tuple(-x for x in side), "d": side, "e": (0, 0, 1),
             "q": (0, 0, -1)}.get(e.keysym.lower())
        if d is None:
            return
        self.target = [t + step * x for t, x in zip(self.target, d)]
        self.show()

    def show(self):
        if self.winfo_ismapped():
            self._display()

    def press(self, e):
        self.focus_set()
        self.last = (e.x, e.y)

    def drag(self, e, how):
        dx, dy = e.x - self.last[0], e.y - self.last[1]
        self.last = (e.x, e.y)
        if self.fp:
            if how == "turn":
                self.fyaw -= dx * 0.3
                self.fpitch = max(-85, min(85, self.fpitch - dy * 0.3))
                self.show()
            return
        if how == "turn":
            self.yaw -= dx * 0.5
            self.pitch = max(-89, min(89, self.pitch + dy * 0.5))
        elif how == "zoom":
            self.dist = max(0.5, self.dist * (1 + dy * 0.01))
        else:
            k = self.dist * 0.0015
            yr = math.radians(self.yaw)
            self.target[0] += (-math.sin(yr) * dx) * k
            self.target[1] += (math.cos(yr) * dx) * k
            self.target[2] += dy * k
        self.show()

    def wheel(self, e):
        if self.fp:
            return
        self.dist = max(0.5, self.dist * (0.9 if e.delta > 0 else 1.1))
        self.show()

    def initgl(self):
        GL.glClearColor(0.23, 0.25, 0.28, 1)
        GL.glEnable(GL.GL_DEPTH_TEST)

    def texture(self, b):
        t = self.textures.get(b.key)
        if t is None and b.rgba is not None:
            t = GL.glGenTextures(1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, t)
            img = np.ascontiguousarray(b.rgba, np.uint8)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
            GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, img.shape[1], img.shape[0], 0, GL.GL_RGBA,
                            GL.GL_UNSIGNED_BYTE, img)
            self.textures[b.key] = t
        return t

    def redraw(self):
        if getattr(self, "stale_vbo", None):
            GL.glDeleteBuffers(len(self.stale_vbo), self.stale_vbo)
            self.stale_vbo = []
        if self.stale:
            GL.glDeleteTextures(self.stale)
            self.stale = []
        w, h = max(1, self.winfo_width()), max(1, self.winfo_height())
        GL.glViewport(0, 0, w, h)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        ext = getattr(self, "extent", 10.0)
        if self.fp:
            # a driver's eye: 0.25 m to the far side of the track; 24-bit depth keeps the road and the verge apart
            GLU.gluPerspective(60, w / h, 0.25, max(2000.0, ext * 1.2))
        else:
            GLU.gluPerspective(40, w / h, max(0.05, self.dist * 0.002), max(200.0, self.dist * 4 + ext))
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()
        if self.fp:
            yr, pr = math.radians(self.fyaw), math.radians(self.fpitch)
            ex, ey, ez = self.eye
            GLU.gluLookAt(ex, ey, ez, ex + math.cos(pr) * math.cos(yr), ey + math.cos(pr) * math.sin(yr),
                          ez + math.sin(pr), 0, 0, 1)
        else:
            yr, pr = math.radians(self.yaw), math.radians(self.pitch)
            tx, ty, tz = self.target
            ex = tx + self.dist * math.cos(pr) * math.cos(yr)
            ey = ty + self.dist * math.cos(pr) * math.sin(yr)
            ez = tz + self.dist * math.sin(pr)
            GLU.gluLookAt(ex, ey, ez, tx, ty, tz, 0, 0, 1)
            self.ground()
        GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_LINE if self.wire else GL.GL_FILL)
        GL.glEnableClientState(GL.GL_VERTEX_ARRAY)
        GL.glEnableClientState(GL.GL_COLOR_ARRAY)
        GL.glEnableClientState(GL.GL_TEXTURE_COORD_ARRAY)
        GL.glTexEnvi(GL.GL_TEXTURE_ENV, GL.GL_TEXTURE_ENV_MODE, GL.GL_MODULATE)
        for blend in (False, True):
            if blend:
                GL.glEnable(GL.GL_BLEND)
                GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
                GL.glDepthMask(GL.GL_FALSE)
                # see-through layers lie on what they cover (road lines, skid marks, shadows): drawn a hair nearer
                GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
                GL.glPolygonOffset(-1.0, -2.0)
            else:
                GL.glEnable(GL.GL_ALPHA_TEST)
                GL.glAlphaFunc(GL.GL_GREATER, 0.02)
            cut_now = None
            for b in self.batches:
                if b.blend != blend or getattr(b, "excl", 0) & self.exclude:
                    continue
                cut = getattr(b, "cut", None)
                if not blend and cut != cut_now:
                    # the game's alpha test: a texel of 48 of 128 or less is left out; a solid strip keeps them all
                    if cut is None:
                        GL.glEnable(GL.GL_ALPHA_TEST)
                        GL.glAlphaFunc(GL.GL_GREATER, 0.02)
                    elif cut:
                        GL.glEnable(GL.GL_ALPHA_TEST)
                        GL.glAlphaFunc(GL.GL_GREATER, 48 / 128.0)
                    else:
                        GL.glDisable(GL.GL_ALPHA_TEST)
                    cut_now = cut
                if blend:
                    GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE if getattr(b, "add", False) else GL.GL_ONE_MINUS_SRC_ALPHA)
                t = None if self.wire else self.texture(b)
                if t:
                    GL.glEnable(GL.GL_TEXTURE_2D)
                    GL.glBindTexture(GL.GL_TEXTURE_2D, t)
                else:
                    GL.glDisable(GL.GL_TEXTURE_2D)
                if getattr(b, "vbo", None) is None:
                    # the arrays go to the card once; a track has a million vertices
                    b.vbo = list(GL.glGenBuffers(3))
                    for buf, arr in zip(b.vbo, (b.pos, b.col, b.uv)):
                        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, buf)
                        GL.glBufferData(GL.GL_ARRAY_BUFFER, np.ascontiguousarray(arr, np.float32),
                                        GL.GL_STATIC_DRAW)
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, b.vbo[0])
                GL.glVertexPointer(3, GL.GL_FLOAT, 0, None)
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, b.vbo[1])
                GL.glColorPointer(4, GL.GL_FLOAT, 0, None)
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, b.vbo[2])
                GL.glTexCoordPointer(2, GL.GL_FLOAT, 0, None)
                GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
                GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(b.pos))
            GL.glDisable(GL.GL_BLEND)
            GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
            GL.glDisable(GL.GL_ALPHA_TEST)
            GL.glDepthMask(GL.GL_TRUE)
        GL.glDisableClientState(GL.GL_VERTEX_ARRAY)
        GL.glDisableClientState(GL.GL_COLOR_ARRAY)
        GL.glDisableClientState(GL.GL_TEXTURE_COORD_ARRAY)
        GL.glDisable(GL.GL_TEXTURE_2D)
        GL.glPolygonMode(GL.GL_FRONT_AND_BACK, GL.GL_FILL)

    def ground(self):
        """A grid on the road, where the tyres stand."""
        z = self.ground_z if hasattr(self, "ground_z") else 0.0
        GL.glDisable(GL.GL_TEXTURE_2D)
        GL.glColor3f(0.36, 0.38, 0.42)
        GL.glBegin(GL.GL_LINES)
        for i in range(-6, 7):
            GL.glVertex3f(i * 0.5, -3, z)
            GL.glVertex3f(i * 0.5, 3, z)
            GL.glVertex3f(-3, i * 0.5, z)
            GL.glVertex3f(3, i * 0.5, z)
        GL.glEnd()


class CarViewer(tk.Toplevel):
    """A window with the car. scenes: [(title, geo)] (one, or the game's and the import's to compare);
    names {hash: label}; rgba_of(label) the picture of a label; ctype the CarTypeInfo record or None."""

    def __init__(self, master, car, scenes, names, rgba_of, ctype, skins, skin=None, icon=None, actions=(),
                 scene_pictures=None):
        self.scene_pictures = scene_pictures      # [(rgba_of, ctype)] a scene: its own pictures and wheels
        super().__init__(master)
        self.title("%s — viewer" % car)
        self.geometry("1000x700")
        if icon:
            try:
                self.iconbitmap(icon)
            except tk.TclError:
                pass
        self.car, self.scenes, self.names, self.rgba_of, self.ctype = car, scenes, names, rgba_of, ctype
        bar = ttk.Frame(self, padding=4)
        bar.pack(fill="x")
        self.which = tk.IntVar(value=len(scenes) - 1)
        if len(scenes) > 1:
            for i, (title, _) in enumerate(scenes):
                ttk.Radiobutton(bar, text=title, variable=self.which, value=i, command=self.rebuild).pack(side="left")
            ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(bar, text="Level of detail:").pack(side="left")
        self.lod = ttk.Combobox(bar, values=list(carinfo.LODS), width=3, state="readonly")
        self.lod.set("A")
        self.lod.pack(side="left", padx=4)
        self.lod.bind("<<ComboboxSelected>>", lambda e: self.rebuild())
        ttk.Label(bar, text="Skin:").pack(side="left", padx=(10, 0))
        avail = set(ctype.available_skins) if ctype else set()
        self.skin_values = ["%d%s" % (k, "" if not avail or k in avail else " (not in game)") for k in skins] or ["1"]
        self.skin = ttk.Combobox(bar, values=self.skin_values, width=14, state="readonly")
        start = skin if skin in skins else (skins[0] if skins else 1)
        self.skin.set(self.skin_values[skins.index(start)] if start in skins else self.skin_values[0])
        self.skin.pack(side="left", padx=4)
        self.skin.bind("<<ComboboxSelected>>", lambda e: self.rebuild())
        self.wire = tk.BooleanVar()
        ttk.Checkbutton(bar, text="Wireframe", variable=self.wire, command=self.toggle_wire).pack(side="left", padx=10)
        self.info = ttk.Label(bar, text="")
        self.info.pack(side="right")
        if not HAVE_GL:
            ttk.Label(self, text="This build has no OpenGL (PyOpenGL and pyopengltk).", padding=20).pack()
            return
        bottom = ttk.Frame(self, padding=4)
        bottom.pack(side="bottom", fill="x")
        ttk.Label(bottom, text="Left drag: turn   right drag or wheel: zoom   middle drag: move").pack(side="left")
        for text, fn in reversed(actions):
            ttk.Button(bottom, text=text, command=lambda fn=fn: (fn(), self.destroy())).pack(side="right", padx=4)
        self.view = GLView(self)
        self.view.pack(fill="both", expand=True)
        self.after(50, self.rebuild)

    def toggle_wire(self):
        self.view.wire = self.wire.get()
        self.view.show()

    def rebuild(self):
        title, geo = self.scenes[self.which.get()]
        if self.scene_pictures:
            self.rgba_of, self.ctype = self.scene_pictures[self.which.get()]
        skin = int(self.skin.get().split()[0])
        lod = self.lod.get()
        placed = carinfo.assemble(geo, self.car, self.ctype, lod)
        batches, tris = build_scene(placed, self.names, self.rgba_of, self.car, skin)
        if self.ctype:
            self.view.ground_z = min(w[2] - w[3] for w in self.ctype.wheels())
        self.view.set_batches(batches)
        body = next((p.solid for p in placed if not p.label.startswith(("WHEEL_", "BRAKE_"))), None)
        nb = sum(len(st.triangles()) for st in body.strips) if body else 0
        self.info.configure(text="%s: %d triangles (body %d)" % (title, tris, nb))


def mesh_batches(meshes):
    """[Batch] of plain meshes: each (pos (n,3), normal (n,3) or None, uv (n,2), colour (n,4) or None,
    [(key, rgba or None, triangle indices)]); lit with the viewer's sun when there are normals."""
    batches = {}
    tris = 0
    for pos, normal, uv, colour, mats in meshes:
        pos = np.asarray(pos, np.float32)
        if normal is not None:
            n = np.asarray(normal, np.float32)
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            n = n / np.maximum(ln, 1e-6)
            light = 0.38 + 0.62 * np.maximum(0, n @ SUN) + 0.18 * np.maximum(0, n @ FILL)
            shade = np.repeat(light[:, None], 3, 1)
        else:
            shade = np.ones((len(pos), 3), np.float32)
        if colour is not None:
            shade = shade * np.clip(np.asarray(colour, np.float32)[:, :3] * 2.0, 0, 1)
        col = np.concatenate([np.clip(shade, 0, 1), np.ones((len(pos), 1), np.float32)], 1)
        for key, rgba, idx in mats:
            idx = np.asarray(idx, np.int64)
            idx = idx[:len(idx) // 3 * 3]
            if not len(idx):
                continue
            blend = rgba is not None and int(rgba[..., 3].min()) < 250
            b = batches.get(key)
            if b is None:
                b = batches[key] = Batch(key, rgba, blend)
                b.pos, b.uv, b.col = [], [], []
            b.pos.append(pos[idx])
            b.uv.append(np.asarray(uv, np.float32)[idx] if uv is not None else np.zeros((len(idx), 2), np.float32))
            b.col.append(col[idx])
            tris += len(idx) // 3
    out = []
    for b in batches.values():
        b.pos, b.uv, b.col = np.concatenate(b.pos), np.concatenate(b.uv), np.concatenate(b.col)
        out.append(b)
    return out, tris


class MeshViewer(tk.Toplevel):
    """A window with prepared batches: scenes [(title, (batches, triangles))], switched by buttons."""

    def __init__(self, master, title, scenes, icon=None, actions=(), ground_z=None, camera=None):
        self.camera = camera            # (target, distance, pitch) to start from
        super().__init__(master)
        self.title(title)
        self.geometry("1000x700")
        if icon:
            try:
                self.iconbitmap(icon)
            except tk.TclError:
                pass
        self.scenes = scenes
        bar = ttk.Frame(self, padding=4)
        bar.pack(fill="x")
        self.which = tk.IntVar(value=len(scenes) - 1)
        if len(scenes) > 1:
            for i, (t, _) in enumerate(scenes):
                ttk.Radiobutton(bar, text=t, variable=self.which, value=i, command=self.rebuild).pack(side="left")
        self.wire = tk.BooleanVar()
        ttk.Checkbutton(bar, text="Wireframe", variable=self.wire, command=self.toggle_wire).pack(side="left", padx=10)
        self.info = ttk.Label(bar, text="")
        self.info.pack(side="right")
        if not HAVE_GL:
            ttk.Label(self, text="This build has no OpenGL.", padding=20).pack()
            return
        bottom = ttk.Frame(self, padding=4)
        bottom.pack(side="bottom", fill="x")
        ttk.Label(bottom, text="Left drag: turn   right drag or wheel: zoom   middle drag: move").pack(side="left")
        for text, fn in reversed(actions):
            ttk.Button(bottom, text=text, command=lambda fn=fn: (fn(), self.destroy())).pack(side="right", padx=4)
        self.view = GLView(self)
        if ground_z is not None:
            self.view.ground_z = ground_z
        self.view.pack(fill="both", expand=True)
        self.after(50, self.rebuild)

    def toggle_wire(self):
        self.view.wire = self.wire.get()
        self.view.show()

    def rebuild(self):
        t, (batches, tris) = self.scenes[self.which.get()]
        self.view.set_batches(batches)
        if self.camera:
            self.view.target, self.view.dist, self.view.pitch = list(self.camera[0]), self.camera[1], self.camera[2]
            self.view.show()
        self.info.configure(text="%s: %d triangles" % (t, tris))


class TrackViewer(tk.Toplevel):
    """A track: the overview (orbit and fly), a direction (the game hides the other direction's objects), a car's place
    on the starting grid with the eye where a driver's is, and driving on the track's own collision surface.

    batches carry excl: their instances' direction bits (0, 0x04 or 0x08); ground is an hp2track.Ground; places
    {direction: [(x, y, heading)]}."""

    EYE = 1.15                  # a driver's eye over the road, in metres
    STEP = 1.2                  # the highest kerb or step a car climbs

    def __init__(self, master, title, batches, tris, camera, ground, places, directions, icon=None):
        super().__init__(master)
        self.title(title)
        self.geometry("1100x760")
        if icon:
            try:
                self.iconbitmap(icon)
            except tk.TclError:
                pass
        self.batches, self.tris, self.camera = batches, tris, camera
        self.ground, self.places, self.directions = ground, places, directions
        bar = ttk.Frame(self, padding=4)
        bar.pack(fill="x")
        ttk.Label(bar, text="Direction:").pack(side="left")
        self.direction = tk.StringVar(value="forward")
        for d in ("forward", "backward"):
            ttk.Radiobutton(bar, text=d.capitalize(), variable=self.direction, value=d,
                            command=self.set_direction).pack(side="left")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Label(bar, text="Start place:").pack(side="left")
        self.place = ttk.Combobox(bar, width=4, state="readonly")
        self.place.pack(side="left", padx=(2, 4))
        ttk.Button(bar, text="Take the car's place", command=self.take_place).pack(side="left")
        self.collide = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Collision (drive on the road)", variable=self.collide,
                        command=self.set_collision).pack(side="left", padx=8)
        ttk.Button(bar, text="Overview", command=self.overview).pack(side="left")
        self.wire = tk.BooleanVar()
        ttk.Checkbutton(bar, text="Wireframe", variable=self.wire, command=self.toggle_wire).pack(side="left", padx=8)
        self.info = ttk.Label(bar, text="")
        self.info.pack(side="right")
        if not HAVE_GL:
            ttk.Label(self, text="This build has no OpenGL.", padding=20).pack()
            return
        bottom = ttk.Frame(self, padding=4)
        bottom.pack(side="bottom", fill="x")
        self.help = ttk.Label(bottom, text="")
        self.help.pack(side="left")
        self.status = ttk.Label(bottom, text="")
        self.status.pack(side="right")
        self.view = GLView(self)
        self.view.pack(fill="both", expand=True)
        self.keys = set()
        self.view.bind("<KeyPress>", self.key_down, add="+")
        self.view.bind("<KeyRelease>", self.key_up)
        self.view.bind("<FocusOut>", lambda e: self.keys.clear())
        self.speed, self.feet, self.ticking, self.last = 0.0, None, False, None
        self.after(50, self.start)

    # -- the scene
    def start(self):
        self.view.set_batches(self.batches)
        self.overview()
        self.set_direction()
        if not self.ground.n:
            self.collide.set(False)

    def set_direction(self):
        d = self.direction.get()
        self.view.exclude = self.directions[d]
        n = len(self.places.get(d, []))
        self.place.configure(values=[str(i + 1) for i in range(n)])
        self.place.set("1" if n else "")
        self.info.configure(text="%d triangles, %s" % (self.tris, d))
        self.view.show()

    def toggle_wire(self):
        self.view.wire = self.wire.get()
        self.view.show()

    def overview(self):
        v = self.view
        v.fp = False
        self.ticking = False
        v.target, v.dist, v.pitch = list(self.camera[0]), self.camera[1], self.camera[2]
        self.help.configure(text="Left drag: turn   wheel or right drag: zoom   middle drag: move   "
                                 "click the view, then W A S D Q E: fly (Shift faster)")
        self.status.configure(text="")
        v.show()

    # -- the driver's seat
    def take_place(self):
        d = self.direction.get()
        pl = self.places.get(d, [])
        if not pl:
            self.status.configure(text="this track has no %s starting grid" % d)
            return
        x, y, h = pl[max(0, int(self.place.get() or 1) - 1)]
        z, _ = self.ground.elevation(x, y) if self.ground.n else (None, None)
        if z is None:
            z = self.view_ground_guess(x, y)
        v = self.view
        v.fp = True
        v.eye = [x, y, z + self.EYE]
        v.fyaw, v.fpitch = math.degrees(h), -4.0
        self.feet, self.speed = z, 0.0
        self.set_collision()
        v.focus_set()
        if not self.ticking:
            self.ticking = True
            self.last = None
            self.after(16, self.tick)
        v.show()

    def view_ground_guess(self, x, y):
        """No collision surface under the place: the lowest drawn point near it."""
        best = None
        for b in self.batches:
            p = b.pos
            m = (np.abs(p[:, 0] - x) < 3) & (np.abs(p[:, 1] - y) < 3)
            if m.any():
                z = float(p[m, 2].min())
                best = z if best is None else min(best, z)
        return best if best is not None else 0.0

    def set_collision(self):
        if not self.view.fp:
            return
        if self.collide.get():
            ex, ey, ez = self.view.eye
            z, _ = self.ground.elevation(ex, ey, below=ez) if self.ground.n else (None, None)
            if z is None:
                self.collide.set(False)
                self.status.configure(text="no road under the eye here: collision is off")
            else:
                self.feet = z
                self.view.eye[2] = z + self.EYE
            self.help.configure(text="W: faster   S: brake and reverse   A D: steer   Shift: more power   "
                                     "left drag: look round")
        else:
            self.speed = 0.0
            self.help.configure(text="W S A D: move   Q E: down and up   Shift: faster   left drag: look round")
        self.view.show()

    def key_down(self, e):
        self.keys.add(e.keysym.lower())

    def key_up(self, e):
        self.keys.discard(e.keysym.lower())

    def tick(self):
        if not self.ticking or not self.winfo_exists():
            return
        import time
        now = time.perf_counter()
        dt = 0.016 if self.last is None else min(0.05, now - self.last)
        self.last = now
        k = self.keys
        fast = "shift_l" in k or "shift_r" in k
        v = self.view
        moved = False
        if self.collide.get() and self.feet is not None:
            moved = self.drive(dt, k, fast)
        else:
            step = (60.0 if fast else 15.0) * dt
            yr, pr = math.radians(v.fyaw), math.radians(v.fpitch)
            fwd = (math.cos(pr) * math.cos(yr), math.cos(pr) * math.sin(yr), math.sin(pr))
            side = (math.sin(yr), -math.cos(yr), 0.0)
            for key, d, s in (("w", fwd, 1), ("s", fwd, -1), ("d", side, 1), ("a", side, -1),
                              ("e", (0, 0, 1), 1), ("q", (0, 0, 1), -1)):
                if key in k:
                    v.eye = [a + s * step * b for a, b in zip(v.eye, d)]
                    moved = True
            if moved:
                self.status.configure(text="x %.0f  y %.0f  z %.1f" % tuple(v.eye))
        if moved:
            v.show()
        self.after(16, self.tick)

    def drive(self, dt, k, fast):
        """A simple car on the track's collision surface: it climbs kerbs up to STEP, stays under bridges, slides
        along the walls and stops where the surface ends."""
        v, g = self.view, self.ground
        top = 70.0 if fast else 45.0
        if "w" in k:
            self.speed = min(top, self.speed + (16.0 if fast else 9.0) * dt)
        elif "s" in k:
            self.speed = self.speed - (25.0 if self.speed > 0 else 6.0) * dt
            self.speed = max(-12.0, self.speed)
        else:
            self.speed *= max(0.0, 1.0 - 0.5 * dt)
            if abs(self.speed) < 0.05:
                self.speed = 0.0
        if self.speed > top:
            self.speed = max(top, self.speed - 20.0 * dt)
        turn = 0.0
        if "a" in k:
            turn += 1
        if "d" in k:
            turn -= 1
        if turn and abs(self.speed) > 0.3:
            rate = 95.0 / (1.0 + abs(self.speed) / 18.0)
            v.fyaw += turn * rate * dt * (1 if self.speed > 0 else -1)
        if self.speed == 0.0:
            return bool(turn)
        x, y, _ = v.eye
        h = math.radians(v.fyaw)
        dx, dy = math.cos(h) * self.speed * dt, math.sin(h) * self.speed * dt
        nx, ny = x + dx, y + dy
        wall = g.wall_hit(x, y, nx, ny, self.feet + 0.3, self.feet + 1.6)
        if wall is not None:
            # along the wall with what is left of the move, a little off it; half the speed is lost
            along = dx * wall[0] + dy * wall[1]
            nx, ny = x + along * wall[0], y + along * wall[1]
            self.speed *= 0.5
            if g.wall_hit(x, y, nx, ny, self.feet + 0.3, self.feet + 1.6) is not None:
                nx, ny = x, y
                self.speed = 0.0
        z, terrain = g.elevation(nx, ny, below=self.feet + self.STEP)
        if z is None:
            self.speed = 0.0
            self.status.configure(text="the end of the road surface")
            return True
        self.feet = z
        v.eye = [nx, ny, z + self.EYE]
        self.status.configure(text="%d km/h   x %.0f  y %.0f  z %.1f   terrain %d" % (
            round(abs(self.speed) * 3.6), nx, ny, z, terrain))
        return True


SOLID_STRIP = 0x4000           # a strip drawn whole: its picture's alpha cuts nothing (the road's edges into the verge)


def solid_arrays(s):
    """{(texture hash, solid): (pos, uv, colour, normal) per triangle corner} of an HP2 solid, as numpy arrays (normal 0:
    none); solid is whether the strips have SOLID_STRIP."""
    out = {}
    for e, st in zip(s.entries, s.strips):
        h = s.textures[e.texture] if 0 <= e.texture < len(s.textures) else None
        h = (h, bool(e.flags & SOLID_STRIP))
        tri = st.triangles()
        if not tri:
            continue
        idx = np.array(tri, np.int64).reshape(-1)
        pos = np.array([v.pos for v in st.verts], np.float32)[idx]
        uv = np.array([v.st for v in st.verts], np.float32)[idx]
        rgba = np.array([v.rgba for v in st.verts], np.int64)[idx]
        col = np.stack([rgba & 31, rgba >> 5 & 31, rgba >> 10 & 31], 1).astype(np.float32) * (8 / 128.0)
        if st.verts[0].normal is not None:
            nrm = np.array([v.normal or (0, 0, 0) for v in st.verts], np.float32)[idx] / 127.0
        else:
            nrm = np.zeros_like(pos)
        a = out.setdefault(h, [[], [], [], []])
        for k, x in enumerate((pos, uv, col, nrm)):
            a[k].append(x)
    return {h: tuple(np.concatenate(x) for x in v) for h, v in out.items()}


def see_through(rgba):
    """Whether a picture is drawn blended (shadows, road paint, glass) rather than solid with its cut-outs kept by the
    alpha test (leaves, fences). The game's alpha is 0..128 for 0..1, and solid pictures are not all 128: the asphalt
    is 112..127. Taken as see-through, a road went without depth and showed through or under what stands on it in the
    distance. A picture is see-through when a good part of it is neither clear nor nearly solid."""
    if rgba is None:
        return False
    a = rgba[..., 3]
    return float(((a > 24) & (a < 200)).mean()) > 0.04


def placed_batches(placed, rgba_of_hash, bits_of_hash=None):
    """[Batch] of placed solids [(label, solid, matrix rows + offset or None, mirrored)]: a track, or any scene.

    As the game draws them: the picture's AlphaBits (GS ALPHA's low byte, bits_of_hash) give the blending, 10 none, 68
    over what is behind, 72 added to it (the sun, glows); without them it is guessed from the alpha. The strips with
    SOLID_STRIP are drawn whole, the others cut where the picture's alpha is 48 of 128 or less, as the game's alpha
    test does (leaves, fences)."""
    cache, groups = {}, {}
    for label, s, m, mirrored in placed:
        arr = cache.get(id(s))
        if arr is None:
            arr = cache[id(s)] = solid_arrays(s)
        for h, (pos, uv, col, nrm) in arr.items():
            if m is not None:
                R = np.array(m[:3], np.float32)
                p = pos @ R.T + np.array(m[3], np.float32)
                n = nrm @ R.T
            else:
                p, n = pos, nrm
            shade = np.clip(col, 0, 1)
            lit = np.abs(n).sum(1) > 0
            if lit.any():
                nn = n[lit] / np.maximum(np.linalg.norm(n[lit], axis=1, keepdims=True), 1e-6)
                light = 0.38 + 0.62 * np.maximum(0, nn @ SUN) + 0.18 * np.maximum(0, nn @ FILL)
                shade[lit] = np.repeat(light[:, None], 3, 1)
            g = groups.setdefault(h, ([], [], []))
            g[0].append(p)
            g[1].append(uv)
            g[2].append(np.concatenate([shade, np.ones((len(p), 1), np.float32)], 1))
    out, tris = [], 0
    for (h, solid), (ps, uvs, cols) in groups.items():
        rgba = rgba_of_hash(h)
        bits = bits_of_hash(h) if bits_of_hash else None
        if bits is None:
            blend = see_through(rgba)
        else:
            blend = (bits >> 6 & 3) == 1 and (bits & 3) != (bits >> 2 & 3)      # D = Cd, A != B: a blend
        b = Batch(h, rgba, blend)
        b.add = bits is not None and blend and (bits >> 2 & 3) == 2              # (Cs - 0) As + Cd
        b.cut = not solid
        b.pos, b.uv, b.col = np.concatenate(ps), np.concatenate(uvs), np.concatenate(cols)
        tris += len(b.pos) // 3
        out.append(b)
    return out, tris
