#!/usr/bin/env python3
"""The mod manager's window: the same commands as hp2assets.py, for an installed game. ModManager.exe starts it.

    pythonw hp2assets_gui.py [GAME]
"""

import contextlib
import glob
import io
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import numpy  # noqa: F401
    import PIL  # noqa: F401
except ImportError as e:      # started by a double click there is no console to say it in
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("NFSHP2 Modding suite", "Python is missing a package: %s\n\nInstall them with:\n\n"
                         "    pip install numpy pillow" % e.name)
    sys.exit(1)

import hp2about as about  # noqa: E402
import hp2theme as theme  # noqa: E402
import hp2assets as cli  # noqa: E402
import hp2car as carinfo  # noqa: E402
import hp2core as core  # noqa: E402
import hp2tex as tex  # noqa: E402
import hp2exp as exp  # noqa: E402
import hp2tabs as tabs  # noqa: E402
import hp2tabs2 as tabs2  # noqa: E402
import hp2view as view  # noqa: E402

SETTINGS = os.path.join(os.path.expanduser("~"), ".hp2assets.json")
ICON = os.path.join(getattr(sys, "_MEIPASS", HERE), "modmanager.ico")     # _MEIPASS: inside ModManager.exe (PyInstaller)


def installed_game():
    """Where the port's installer put the game (setup.cpp keeps it under HKCU), or ""."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\NFSHP2Port") as k:
            return winreg.QueryValueEx(k, "InstallDir")[0]
    except (ImportError, OSError):
        return ""
TEXTURE_FILE_GLOBS = ("CARS/TEXTURES.tex", "GLOBAL/*.tex", "GLOBAL/*.BUN", "FRONTEND/*.tex", "FRONTEND/*.BUN", "TRACKS/*.tex",
                      "TRACKS/*.BUN")


def load_settings():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(s):
    try:
        with open(SETTINGS, "w") as f:
            json.dump(s, f)
    except OSError:
        pass


class LogWriter(io.TextIOBase):
    def __init__(self, q):
        self.q = q

    def write(self, s):
        self.q.put(s)
        return len(s)


class App(tk.Tk):
    def __init__(self, game=None):
        super().__init__()
        self.title("%s %s" % (about.NAME, about.VERSION))
        self.geometry("1280x820")
        try:
            self.iconbitmap(ICON)
        except tk.TclError:
            pass
        self.settings = load_settings()
        self.q = queue.Queue()
        self.busy = False
        self.textures = []
        self.tex_buf = b""
        self.preview_img = None
        self.theme = theme.Theme(self, self.settings.get("theme", "system"))

        about.header(self, self)
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Game folder:").pack(side="left")
        self.game = tk.StringVar(value=game or self.settings.get("game") or installed_game())
        ttk.Entry(top, textvariable=self.game).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(top, text="Browse…", command=self.browse_game).pack(side="left")
        ttk.Button(top, text="Open", command=self.load_game).pack(side="left", padx=4)

        body = ttk.PanedWindow(self, orient="vertical")
        body.pack(fill="both", expand=True, padx=6)
        nb = ttk.Notebook(body)
        body.add(nb, weight=4)
        self.build_cars(nb)
        self.build_textures(nb)
        self.tabs = []
        for cls in (tabs.TracksTab, tabs.PhysicsTab, tabs.TextsTab, tabs.ScreensTab, tabs.SoundTab, tabs.MoviesTab, exp.ExperimentalTab,
                    tabs2.FilesTab):
            self.tabs.append(cls(self, nb))
        logf = ttk.Frame(body)
        body.add(logf, weight=1)
        self.log = tk.Text(logf, height=10, wrap="word", state="disabled")
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.theme.apply()
        self.after(3000, self.follow_system)
        self.after(100, self.pump)
        if self.game.get():
            self.after(200, self.load_game)

    def toggle_theme(self):
        """System -> Light -> Dark -> System; kept in the settings."""
        self.settings["theme"] = self.theme.next_mode()
        save_settings(self.settings)
        self.theme_text.set(self.theme.label())
        self.theme.apply()

    def follow_system(self):
        """In System, the window follows Windows when its setting for apps changes."""
        if self.theme.mode == "system" and self.theme.resolve() != self.theme.dark:
            self.theme.apply()
        self.after(3000, self.follow_system)

    # ---- plumbing ------------------------------------------------------------------------------------------------------------

    def pump(self):
        try:
            while True:
                s = self.q.get_nowait()
                if callable(s):
                    s()
                    continue
                self.log.configure(state="normal")
                self.log.insert("end", s)
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self.pump)

    def say(self, s):
        self.q.put(s + "\n")

    def run(self, what, fn, then=None):
        """fn() in a thread with its prints in the log; then(result) back on the window's thread."""
        if self.busy:
            self.say("busy, wait for the last job")
            return
        self.busy = True
        self.say("— " + what)

        def work():
            res = None
            try:
                with contextlib.redirect_stdout(LogWriter(self.q)):
                    res = fn()
            except SystemExit as e:
                self.say(str(e))
            except Exception as e:     # a job's failure goes to the log, the window stays
                self.say("error: %s" % e)
            self.busy = False
            if then:
                self.q.put(lambda: then(res))
        threading.Thread(target=work, daemon=True).start()

    def data(self):
        return cli.data_dir(self.game.get())

    def save(self):
        save_settings(self.settings)

    def browse_game(self):
        d = filedialog.askdirectory(title="The installed game (the folder with speed.exe)")
        if d:
            self.game.set(d)
            self.load_game()

    def load_game(self):
        try:
            data = self.data()
        except SystemExit as e:
            self.say(str(e))
            return
        self.settings["game"] = self.game.get()
        save_settings(self.settings)
        self.cars.delete(0, "end")
        for p in sorted(glob.glob(os.path.join(data, "CARS", "*", "GEOMETRY.geo"))):
            car = os.path.basename(os.path.dirname(p))
            self.cars.insert("end", car + ("  *" if os.path.exists(p + ".orig") else ""))
        files = []
        for g in TEXTURE_FILE_GLOBS:
            files += sorted(os.path.relpath(p, data).replace("\\", "/") for p in glob.glob(os.path.join(data, g)))
        self.tex_file["values"] = files
        if files and not self.tex_file.get():
            self.tex_file.set(files[0])
            self.load_texture_file()
        for t in self.tabs:
            try:
                t.load()
            except Exception as e:      # one part of the game that will not read leaves the others working
                self.say("%s: %s" % (type(t).__name__, e))
        self.say("game: %s (%d cars, %d texture files)" % (data, self.cars.size(), len(files)))

    # ---- cars ----------------------------------------------------------------------------------------------------------------

    def build_cars(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Cars")
        left = ttk.Frame(f)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Cars (* changed)").pack(anchor="w")
        self.cars = tk.Listbox(left, width=24, exportselection=False)
        self.cars.pack(fill="y", expand=True)
        self.cars.bind("<<ListboxSelect>>", lambda e: self.show_parts())
        mid = ttk.Frame(f)
        mid.pack(side="left", fill="both", expand=True, padx=8)
        ttk.Label(mid, text="Parts").pack(anchor="w")
        self.parts = ttk.Treeview(mid, columns=("tris", "strips", "verts"), selectmode="extended")
        self.parts.heading("#0", text="name")
        for c, t in (("tris", "triangles"), ("strips", "strips"), ("verts", "strip vertices")):
            self.parts.heading(c, text=t)
            self.parts.column(c, width=90, anchor="e")
        self.parts.pack(fill="both", expand=True)
        btns = ttk.Frame(f)
        btns.pack(side="left", fill="y")
        ttk.Button(btns, text="View the car", command=self.view_car).pack(fill="x", pady=2)
        ttk.Button(btns, text="Export OBJ…", command=self.export_car).pack(fill="x", pady=(16, 2))
        ttk.Button(btns, text="Export selected parts…", command=lambda: self.export_car(True)).pack(fill="x", pady=2)
        ttk.Button(btns, text="Import OBJ…", command=self.import_car).pack(fill="x", pady=(16, 2))
        ttk.Button(btns, text="Restore the disc's", command=self.restore_car).pack(fill="x", pady=(16, 2))
        ttk.Label(btns, text="An OBJ replaces the parts\nwhose objects it has, by name;\nthe rest stay as they are.\n\n"
                  "The import shows the car\nbefore and after, and writes\nonly when you say so.",
                  justify="left").pack(pady=12)

    def car(self):
        sel = self.cars.curselection()
        return self.cars.get(sel[0]).split()[0] if sel else None

    def show_parts(self):
        self.parts.delete(*self.parts.get_children())
        car = self.car()
        if not car:
            return
        geo = core.read_geometry(open(cli.car_file(self.data(), car), "rb").read())
        for s in geo.solids():
            _, _, ns, npol, nv, _ = s.counts()
            self.parts.insert("", "end", text=s.full_name, values=(npol, ns, nv))

    def car_viewer(self, car, scenes, actions=()):
        data = self.data()
        names, rgba_of = cli.car_pictures(data, car)
        ctype = cli.car_type_of(data, car)
        skins = carinfo.skins(car, names.values())
        view.CarViewer(self, car, scenes, names, rgba_of, ctype, skins, ctype.default_skin if ctype else None,
                       icon=ICON, actions=actions)

    def view_car(self):
        car = self.car()
        if not car:
            return self.say("choose a car")
        geo = core.read_geometry(open(cli.car_file(self.data(), car), "rb").read())
        self.car_viewer(car, [("in the game", geo)])

    def export_car(self, selected=False):
        car = self.car()
        if not car:
            return self.say("choose a car")
        solids = None
        if selected:
            solids = [self.parts.item(i, "text") for i in self.parts.selection()]
            if not solids:
                return self.say("choose parts")
        data = self.data()
        names, _, _ = cli.texture_names(data)
        ctype = cli.car_type_of(data, car)
        opts = ExportDialog(self, car, carinfo.skins(car, names.values()), ctype).result
        if not opts:
            return
        out = filedialog.askdirectory(title="Export %s into" % car, initialdir=self.settings.get("out"))
        if not out:
            return
        self.settings["out"] = out
        save_settings(self.settings)
        bare, skins, lod = opts
        self.run("export %s" % car, lambda: cli.export_car(data, car, out, set(solids) if solids else None, bare=bare,
                                                           skins=skins, lod=lod))

    def import_car(self):
        car = self.car()
        if not car:
            return self.say("choose a car")
        obj = filedialog.askopenfilename(title="OBJ for %s" % car, filetypes=[("Wavefront OBJ", "*.obj")],
                                         initialdir=self.settings.get("out"))
        if not obj:
            return
        data = self.data()

        def shown(res):
            if not res:
                return
            path, buf, out, after = res
            before = core.read_geometry(buf)

            def write():
                self.run("import %s" % car, lambda: cli.write_car(path, out),
                         lambda _: (self.load_game(), self.show_parts()))
            self.say("the viewer shows %s before and after; Write puts it into the game" % car)
            self.car_viewer(car, [("in the game now", before), ("after the import", after)],
                            actions=[("Write into the game", write), ("Cancel", lambda: self.say("import cancelled"))])
        self.run("check %s" % os.path.basename(obj), lambda: cli.rebuild_car(data, car, obj), shown)

    def restore_car(self):
        car = self.car()
        if car and messagebox.askyesno("Restore", "Put the disc's %s back?" % car):
            a = SimpleNamespace(game=self.game.get(), what=car)
            self.run("restore %s" % car, lambda: cli.cmd_restore(a), lambda _: self.load_game())

    # ---- textures ------------------------------------------------------------------------------------------------------------

    def build_textures(self, nb):
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Textures")
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Label(row, text="File:").pack(side="left")
        self.tex_file = ttk.Combobox(row, width=40, state="readonly")
        self.tex_file.pack(side="left", padx=4)
        self.tex_file.bind("<<ComboboxSelected>>", lambda e: self.load_texture_file())
        ttk.Label(row, text="Filter:").pack(side="left", padx=(12, 0))
        self.tex_filter = tk.StringVar()
        e = ttk.Entry(row, textvariable=self.tex_filter, width=20)
        e.pack(side="left", padx=4)
        e.bind("<KeyRelease>", lambda ev: self.fill_textures())
        main = ttk.Frame(f)
        main.pack(fill="both", expand=True, pady=6)
        self.tex_list = ttk.Treeview(main, columns=("size", "bpp", "note"), selectmode="extended")
        self.tex_list.heading("#0", text="name")
        for c, t, w in (("size", "size", 90), ("bpp", "bits", 50), ("note", "", 160)):
            self.tex_list.heading(c, text=t)
            self.tex_list.column(c, width=w)
        self.tex_list.pack(side="left", fill="both", expand=True)
        self.tex_list.bind("<<TreeviewSelect>>", lambda e: self.preview())
        right = ttk.Frame(main)
        right.pack(side="left", fill="y", padx=8)
        self.canvas = tk.Label(right, text="", width=48, height=20, relief="sunken")
        self.canvas.pack()
        ttk.Button(right, text="Export all…", command=self.export_textures).pack(fill="x", pady=(10, 2))
        ttk.Button(right, text="Export selected…", command=lambda: self.export_textures(True)).pack(fill="x", pady=2)
        ttk.Button(right, text="Import PNGs…", command=self.import_textures).pack(fill="x", pady=(16, 2))
        ttk.Button(right, text="Restore the disc's", command=self.restore_textures).pack(fill="x", pady=(16, 2))
        ttk.Label(right, text="A PNG goes back by its name,\nthe same size as the texture.", justify="left").pack(pady=8)

    def load_texture_file(self):
        rel = self.tex_file.get()
        if not rel:
            return
        self.tex_buf = open(os.path.join(self.data(), rel), "rb").read()
        self.textures = tex.read_textures(self.tex_buf)
        self.fill_textures()

    def fill_textures(self):
        self.tex_list.delete(*self.tex_list.get_children())
        flt = self.tex_filter.get().upper()
        for i, t in enumerate(self.textures):
            if flt and flt not in t.name.upper():
                continue
            note = "uses another's pixels" if t.parent else ""
            self.tex_list.insert("", "end", iid=str(i), text=t.name, values=("%dx%d" % (t.width, t.height), t.bpp, note))

    def preview(self):
        sel = self.tex_list.selection()
        if not sel:
            return
        t = self.textures[int(sel[0])]
        rgba = tex.decode(t, self.tex_buf)
        if rgba is None:
            self.canvas.configure(image="", text="(no pixels of its own)")
            return
        from PIL import Image, ImageTk
        img = Image.fromarray(rgba, "RGBA")
        img.thumbnail((360, 360))
        bg = Image.new("RGBA", img.size, (128, 128, 128, 255))
        bg.alpha_composite(img)
        self.preview_img = ImageTk.PhotoImage(bg)
        self.canvas.configure(image=self.preview_img, text="", width=img.width, height=img.height)

    def export_textures(self, selected=False):
        rel = self.tex_file.get()
        if not rel:
            return
        out = filedialog.askdirectory(title="Export textures of %s into" % rel, initialdir=self.settings.get("out"))
        if not out:
            return
        self.settings["out"] = out
        save_settings(self.settings)
        if not selected:
            a = SimpleNamespace(game=self.game.get(), file=rel, out=out)
            self.run("export %s" % rel, lambda: cli.cmd_export_textures(a))
            return
        picks = [self.textures[int(i)] for i in self.tex_list.selection()]

        def work():
            for t in picks:
                rgba = tex.decode(t, self.tex_buf)
                if rgba is not None:
                    tex.write_png(os.path.join(out, t.name + ".png"), rgba)
                    print(t.name)
        self.run("export %d textures" % len(picks), work)

    def import_textures(self):
        rel = self.tex_file.get()
        if not rel:
            return
        pngs = filedialog.askopenfilenames(title="PNGs for %s" % rel, filetypes=[("PNG", "*.png")],
                                           initialdir=self.settings.get("out"))
        if not pngs:
            return
        a = SimpleNamespace(game=self.game.get(), file=rel, png=list(pngs), dry_run=False)
        self.run("import %d PNGs into %s" % (len(pngs), rel), lambda: cli.cmd_import_textures(a),
                 lambda _: self.load_texture_file())

    def restore_textures(self):
        rel = self.tex_file.get()
        if rel and messagebox.askyesno("Restore", "Put the disc's %s back?" % rel):
            a = SimpleNamespace(game=self.game.get(), what=rel)
            self.run("restore %s" % rel, lambda: cli.cmd_restore(a), lambda _: self.load_texture_file())


class ExportDialog(tk.Toplevel):
    """Asks how to export a car: mesh only or with pictures, which skins, and the whole car's level of detail.
    result: (bare, skins, lod) or None; skins is None (the default), "all" or a list."""

    def __init__(self, master, car, skins, ctype):
        super().__init__(master)
        self.title("Export %s" % car)
        self.transient(master)
        self.resizable(False, False)
        self.result = None
        f = ttk.Frame(self, padding=10)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Every part goes to %s.obj (the file to edit and import back),\nand the car put together "
                          "to %s_whole.obj." % (car, car), justify="left").pack(anchor="w", pady=(0, 8))
        self.mode = tk.StringVar(value="tex")
        ttk.Radiobutton(f, text="Mesh only: UV, normals and material names, no pictures", variable=self.mode,
                        value="bare", command=self.update_state).pack(anchor="w")
        ttk.Radiobutton(f, text="With textures", variable=self.mode, value="tex",
                        command=self.update_state).pack(anchor="w")
        self.which = tk.StringVar(value="default")
        sk = ttk.Frame(f, padding=(20, 2, 0, 2))
        sk.pack(anchor="w")
        default = ctype.default_skin if ctype else (skins[0] if skins else 1)
        avail = set(ctype.available_skins) if ctype else set()
        self.radios = [ttk.Radiobutton(sk, text="the default skin (%d)" % default, variable=self.which,
                                       value="default", command=self.update_state),
                       ttk.Radiobutton(sk, text="these skins:", variable=self.which, value="some",
                                       command=self.update_state),
                       ttk.Radiobutton(sk, text="all skins (%d), a folder each" % len(skins), variable=self.which,
                                       value="all", command=self.update_state)]
        self.radios[0].pack(anchor="w")
        self.radios[1].pack(anchor="w")
        boxes = ttk.Frame(sk, padding=(20, 0, 0, 0))
        boxes.pack(anchor="w")
        self.skin_vars = {}
        self.checks = []
        for i, k in enumerate(skins):
            v = tk.BooleanVar(value=k == default)
            c = ttk.Checkbutton(boxes, text="%d%s" % (k, "" if not avail or k in avail else " (not in game)"),
                                variable=v)
            c.grid(row=i // 5, column=i % 5, sticky="w", padx=(0, 8))
            self.skin_vars[k] = v
            self.checks.append(c)
        self.radios[2].pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(anchor="w", pady=(8, 0))
        ttk.Label(row, text="Whole car's level of detail:").pack(side="left")
        self.lod = ttk.Combobox(row, values=list(carinfo.LODS), width=3, state="readonly")
        self.lod.set("A")
        self.lod.pack(side="left", padx=4)
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(12, 0))
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(b, text="Export…", command=self.ok).pack(side="right", padx=6)
        self.update_state()
        self.grab_set()
        self.wait_window()

    def update_state(self):
        bare = self.mode.get() == "bare"
        for r in self.radios:
            r.configure(state="disabled" if bare else "normal")
        some = not bare and self.which.get() == "some"
        for c in self.checks:
            c.configure(state="normal" if some else "disabled")

    def ok(self):
        bare = self.mode.get() == "bare"
        skins = None
        if not bare:
            if self.which.get() == "all":
                skins = "all"
            elif self.which.get() == "some":
                skins = [k for k, v in self.skin_vars.items() if v.get()]
                if not skins:
                    messagebox.showinfo("Export", "Tick at least one skin.", parent=self)
                    return
        self.result = (bare, skins, self.lod.get())
        self.destroy()


def _viewer_shot(data, png):
    """Opens the viewer on the Vanquish for two seconds and keeps what OpenGL drew."""
    import numpy as np
    from OpenGL import GL
    from PIL import Image
    root = tk.Tk()
    root.withdraw()
    names, rgba_of = cli.car_pictures(data, "VANQUISH")
    ctype = cli.car_type_of(data, "VANQUISH")
    geo = core.read_geometry(open(cli.car_file(data, "VANQUISH"), "rb").read())
    v = view.CarViewer(root, "VANQUISH", [("in the game", geo)], names, rgba_of, ctype,
                       carinfo.skins("VANQUISH", names.values()), ctype.default_skin if ctype else None)

    def grab():
        g = v.view
        g.tkMakeCurrent()
        g.redraw()
        w, h = g.winfo_width(), g.winfo_height()
        px = GL.glReadPixels(0, 0, w, h, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE)
        img = np.frombuffer(px, np.uint8).reshape(h, w, 4)[::-1]
        Image.fromarray(img, "RGBA").convert("RGB").save(png)
        print("viewer: %s, %s" % (v.info.cget("text"), png))
        root.destroy()
    root.after(2500, grab)
    root.mainloop()


def selftest(game, out):
    """ModManager.exe --selftest GAME OUT: the commands through the frozen code, nothing written to the game; OUT/selftest.log."""
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "selftest.log"), "w") as log, contextlib.redirect_stdout(log):
        try:
            data = cli.data_dir(game)
            cli.export_car(data, "VANQUISH", out, skins="all")
            cli.export_car(data, "MUSTANG", out, bare=True)
            names, rgba_of = cli.car_pictures(data, "VANQUISH")
            geo = core.read_geometry(open(cli.car_file(data, "VANQUISH"), "rb").read())
            batches, tris = view.build_scene(carinfo.assemble(geo, "VANQUISH", cli.car_type_of(data, "VANQUISH")),
                                             names, rgba_of, "VANQUISH", 2)
            print("viewer scene: %d pictures, %d triangles, OpenGL %s" % (len(batches), tris, view.HAVE_GL))
            obj = os.path.join(out, "VANQUISH", "skin1", "VANQUISH.obj")
            cli.cmd_import_car(SimpleNamespace(game=game, car="VANQUISH", obj=obj, solids=None, dry_run=True))
            cli.cmd_export_textures(SimpleNamespace(game=game, file="GLOBAL/HUDTEX.tex", out=os.path.join(out, "HUDTEX")))
            # the other parts, nothing written to the game: each file read and made again as it was
            import hp2movie
            import hp2physics
            import hp2screens
            import hp2sound
            import hp2text
            import hp2track
            hp2movie.export_movie(os.path.join(data, "MOVIES", "INTRO", "EALOGO_EN.AVI"), os.path.join(out, "ealogo.avi"))
            for lang, lf in hp2text.load_all(data).items():
                assert lf.build() == open(hp2text.lang_path(data, lang), "rb").read(), lang
            print("texts: the six languages rebuild byte for byte")
            bank = hp2sound.load_bank(data, "FRONTEND")
            msh, msb = hp2sound.bank_paths(data)["FRONTEND"]
            assert bank.build() == (open(msh, "rb").read(), open(msb, "rb").read())
            print("sound: FRONTEND rebuilds byte for byte, %d sounds" % len(bank.sounds()))
            gb = open(os.path.join(data, "GLOBAL", "GLOBALB.BUN"), "rb").read()
            print("physics: %d car types" % len(hp2physics.records(gb)))
            lib = hp2screens.Library(data)
            fb = bytearray(open(os.path.join(data, "FRONTEND", "FRONTB.BUN"), "rb").read())
            scr = hp2screens.read_screens("FRONTEND/FRONTB.BUN", fb)
            hp2screens.render(scr[0], lib).save(os.path.join(out, "screen0.png"))
            print("screens: %d in FRONTB" % len(scr))
            name, p = hp2track.track_files(data)[0]
            tb = open(p, "rb").read()
            assert hp2track.Track(tb).build() == tb
            print("tracks: %s rebuilds byte for byte" % name)
            import hp2files
            from collections import Counter
            es = hp2files.survey(data)
            print("files: %s" % dict(Counter(e.status.split(":")[0] for e in es)))
            print("the port's texts: %s" % {k: (len(a), len(b)) for k, (a, b) in hp2text.port_texts(data).items()})
            bt, tri = view.placed_batches(hp2track.Track(tb).placed()[:500], lambda h: None)
            print("track viewer: %d triangles of the first 500 instances" % tri)
            ground, places = hp2track.Ground(tb), hp2track.start_places(hp2track.read_markers(tb), "forward")
            if places:
                print("track ground: %d polygons; start place 1 at %.1f %.1f, ground %s" % (
                    ground.n, places[0][0], places[0][1], ground.elevation(places[0][0], places[0][1])))
            import ctypes
            try:
                ctypes.windll.comctl32.TaskDialog
                td = "Windows' task dialog"
            except AttributeError:
                td = "a message box (no task dialog in this comctl32)"
            print("about: %s %s, shown in %s; help icons: %s" % (
                about.NAME, about.VERSION, td,
                all(os.path.isfile(os.path.join(about.BASE, "icons", "%s_16.png" % n)) for n in ("help", "about"))))
            if view.HAVE_GL:
                _viewer_shot(data, os.path.join(out, "viewer.png"))
            print("selftest: ok")
        except Exception as e:      # the log says what broke
            import traceback
            traceback.print_exc(file=log)
            print("selftest: FAILED %s" % e)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2], sys.argv[3])
    else:
        App(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()
