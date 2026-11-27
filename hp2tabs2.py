"""More tabs: every file of the install (and whether the game uses it), and the track viewer."""

import os
import tkinter as tk
from tkinter import ttk


class ModelsTab:
    """The models outside the cars and the tracks (hp2models): the cars' dashboards, the menus' and the race's models, the
    cut-scenes' people. View them, export them as OBJ with their pictures, import an OBJ back."""

    def __init__(self, app, nb):
        import hp2models as mdl
        self.app, self.mdl = app, mdl
        self.track = None
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Models")
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Label(row, text="File:").pack(side="left")
        self.file = ttk.Combobox(row, state="readonly", width=34)
        self.file.pack(side="left", padx=4)
        self.file.bind("<<ComboboxSelected>>", lambda e: self.open_file())
        self.what = ttk.Label(row, text="")
        self.what.pack(side="left", padx=8)
        main = ttk.Frame(f)
        main.pack(fill="both", expand=True, pady=6)
        cols = (("tris", "triangles"), ("verts", "vertices"), ("pics", "pictures"))
        self.tree = ttk.Treeview(main, columns=[c for c, _ in cols], selectmode="extended")
        self.tree.heading("#0", text="model")
        self.tree.column("#0", width=260)
        for (c, t), w in zip(cols, (90, 90, 420)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="e" if c != "pics" else "w")
        sb = ttk.Scrollbar(main, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.view())
        btns = ttk.Frame(main, padding=(8, 0))
        btns.pack(side="left", fill="y")
        ttk.Button(btns, text="View", command=self.view).pack(fill="x", pady=2)
        ttk.Button(btns, text="Export OBJ…", command=self.export).pack(fill="x", pady=(16, 2))
        ttk.Button(btns, text="Import OBJ…", command=self.import_obj).pack(fill="x", pady=2)
        ttk.Button(btns, text="Restore the disc's", command=self.restore).pack(fill="x", pady=(16, 2))
        ttk.Label(f, justify="left", foreground="#666", text=(
            "View shows the chosen models (all when none is chosen). Export writes the file's models as one OBJ, each its "
            "own object, with its .mtl and pictures;\nimport it back after editing: the models it names are rebuilt, any "
            "shape, the others stay byte for byte. The pictures are in the Textures tab.")).pack(anchor="w")

    def load(self):
        try:
            data = self.app.data()
        except SystemExit:
            return
        self.files = self.mdl.files(data)
        self.file["values"] = [rel + ("  *" if os.path.exists(os.path.join(data, rel) + ".orig") else "")
                               for rel, _ in self.files]
        if self.files and not self.file.get():
            self.file.current(0)
        self.open_file()

    def rel(self):
        return self.file.get().rstrip(" *")

    def open_file(self):
        rel = self.rel()
        if not rel:
            return
        data = self.app.data()
        self.what.configure(text=dict(self.files).get(rel, ""))
        self.track = self.mdl.load(data, rel)
        self.names, self.packs = self.mdl.pictures(data, rel)
        self.tree.delete(*self.tree.get_children())
        for s in self.track.solids():
            tris = sum(len(st.triangles()) for st in s.strips)
            verts = sum(len(st.verts) for st in s.strips)
            pics = sorted({self.names.get(h, "H%08X" % h) for h in s.textures})
            self.tree.insert("", "end", iid=s.full_name, text=s.full_name, values=(tris, verts, ", ".join(pics)))

    def chosen(self):
        sel = set(self.tree.selection())
        return [s for s in self.track.solids() if not sel or s.full_name in sel] if self.track else []

    def _batches(self, solids):
        import hp2view as view
        rgba_of, bits_of = self.mdl.rgba_lookup(self.packs)
        return view.placed_batches([(s.full_name, s, None, False) for s in solids], rgba_of, bits_of)

    def view(self, scenes=None, actions=()):
        import hp2assets_gui as g
        import hp2view as view
        if scenes is None:
            solids = self.chosen()
            if not solids:
                return
            scenes = [(", ".join(s.full_name for s in solids[:3]) + (" ..." if len(solids) > 3 else ""),
                       self._batches(solids))]
        view.MeshViewer(self.app, "%s (models)" % self.rel(), scenes, icon=g.ICON, actions=actions)

    def export(self):
        from tkinter import filedialog
        rel = self.rel()
        if not rel:
            return
        out = filedialog.askdirectory(title="Export %s into" % rel, initialdir=self.app.settings.get("out"))
        if not out:
            return
        self.app.settings["out"] = out
        self.app.save()
        data = self.app.data()
        sel = list(self.tree.selection())
        self.app.run("export %s" % rel, lambda: self.mdl.export(data, rel, out, only=sel or None, log=print))

    def import_obj(self):
        from tkinter import filedialog
        import hp2assets as cli
        import hp2track as trk
        rel = self.rel()
        if not rel:
            return
        obj = filedialog.askopenfilename(title="An OBJ for %s" % rel, filetypes=[("Wavefront OBJ", "*.obj")],
                                         initialdir=self.app.settings.get("out"))
        if not obj:
            return
        data = self.app.data()

        def work():
            return self.mdl.rebuild(data, rel, obj, log=print)

        def shown(res):
            if not res:
                return
            path, old, new, changed = res
            if not changed:
                return self.app.say("the OBJ changes none of the models")
            before = [s for s in trk.Track(old).solids() if s.full_name in changed]
            after = [s for s in trk.Track(new).solids() if s.full_name in changed]

            def write():
                self.app.run("write %s" % rel, lambda: cli.replace_file(path, new), lambda _: self.load())
            self.view([("in the game now", self._batches(before)), ("after the import", self._batches(after))],
                      actions=[("Write into the game", write)])
            self.app.say("%d models changed: %s; Write into the game puts them in" % (len(changed),
                                                                                     ", ".join(changed[:6])))
        self.app.run("import %s" % os.path.basename(obj), work, shown)

    def restore(self):
        from tkinter import messagebox
        import hp2assets as cli
        rel = self.rel()
        if rel and messagebox.askyesno("Restore", "Put the disc's %s back?" % rel, parent=self.app):
            p = os.path.join(self.app.data(), rel)
            self.app.run("restore %s" % rel, lambda: cli.restore_file(p), lambda _: self.load())


class FilesTab:
    """Every file under data\\: its size, what it is, which tab changes it, and whether the game uses it."""

    def __init__(self, app, nb):
        self.app = app
        self.entries = []
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="All files")
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Button(row, text="Look at every file", command=self.survey).pack(side="left")
        ttk.Label(row, text="  Show:").pack(side="left")
        self.show = ttk.Combobox(row, state="readonly", width=28, values=[
            "all", "used", "not used or not seen", "the port's and backups", "empty"])
        self.show.set("all")
        self.show.pack(side="left", padx=4)
        self.show.bind("<<ComboboxSelected>>", lambda e: self.fill())
        ttk.Label(row, text="  Filter:").pack(side="left")
        self.flt = tk.StringVar()
        e = ttk.Entry(row, textvariable=self.flt, width=20)
        e.pack(side="left", padx=4)
        e.bind("<KeyRelease>", lambda ev: self.fill())
        self.summary = ttk.Label(row, text="")
        self.summary.pack(side="left", padx=10)
        main = ttk.Frame(f)
        main.pack(fill="both", expand=True, pady=6)
        cols = (("size", "size"), ("kind", "what it is"), ("tab", "tab"), ("status", "the game"))
        self.tree = ttk.Treeview(main, columns=[c for c, _ in cols], selectmode="browse")
        self.tree.heading("#0", text="file")
        self.tree.column("#0", width=330)
        for (c, t), w in zip(cols, (90, 170, 90, 430)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="e" if c == "size" else "w")
        sb = ttk.Scrollbar(main, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        ttk.Label(f, justify="left", foreground="#666", text=(
            "Used: the game's program names the file (its hash is the one data\\index.txt gives it), or the port read it "
            "in its test runs (the five recorded demos),\nor a file of the same numbered family was read. Unused: no name "
            "the game builds hashes to it. Files beside the index are the port's own.")).pack(anchor="w")

    def load(self):
        self.tree.delete(*self.tree.get_children())
        self.entries = []
        self.summary.configure(text="Look at every file: about a second")

    def survey(self):
        import hp2files as hf
        data = self.app.data()

        def done(es):
            if es is None:
                return
            self.entries = es
            used = sum(1 for e in es if e.status.startswith("used"))
            unused = sum(1 for e in es if e.status.startswith("unused") or e.status.startswith("not seen"))
            self.summary.configure(text="%d files: %d used, %d unused or not seen" % (len(es), used, unused))
            self.fill()
        self.app.run("look at every file", lambda: hf.survey(data, print), done)

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        show, flt = self.show.get(), self.flt.get().upper()
        folders = {}
        for e in self.entries:
            st = e.status
            if show == "used" and not st.startswith("used"):
                continue
            if show == "not used or not seen" and not (st.startswith("unused") or st.startswith("not seen")):
                continue
            if show == "the port's and backups" and not (st.startswith("the port") or st.startswith("backup")
                                                         or st.startswith("written")):
                continue
            if show == "empty" and not st.startswith("empty"):
                continue
            real = getattr(e, "real", None)
            if flt and flt not in e.rel.upper() and not (real and flt in real.upper()):
                continue
            folder, _, name = e.rel.rpartition("/")
            parent = ""
            if folder:
                if folder not in folders:
                    folders[folder] = self.tree.insert("", "end", text=folder + "/", open=False)
                parent = folders[folder]
            if real:
                name += "   = %s" % real.rpartition("/")[2]
            self.tree.insert(parent, "end", text=name, values=("{:,}".format(e.size), e.kind, e.tab, st))


def view_track(app, track):
    """The track put together (every instance at its place), with its own and the shared pictures."""
    import hp2assets as cli
    import hp2assets_gui as g
    import hp2tex as tex
    import hp2track as trk
    import hp2view as view
    data = app.data()

    def work():
        path = dict(trk.track_files(data))[track]
        buf = open(path, "rb").read()
        t = trk.Track(buf)
        names, packs = cli.track_pictures(data, track)
        cache = {}

        def rgba_of(h):
            if h in cache:
                return cache[h]
            img = None
            hit = packs.get(h)
            if hit is not None:
                tt, buf = hit
                if tt.parent and tt.parent in packs:
                    tt, buf = packs[tt.parent]
                img = tex.decode(tt, buf)
            cache[h] = img
            return img

        def bits_of(h):
            """The picture's AlphaBits (its record's byte 0x76: GS ALPHA's low byte), or None."""
            hit = packs.get(h)
            return hit[1][hit[0].rec_at + 0x76] if hit is not None else None
        # the instances both directions draw, and those only one does (the game hides the other's: hp2track.DIRECTIONS)
        batches, tris, placed = [], 0, []
        for only in (0, 0x04, 0x08, 0x0C):
            pl = t.placed(only=only)
            if not pl:
                continue
            bs, n = view.placed_batches(pl, rgba_of, bits_of)
            for b in bs:
                b.excl = only
            batches += bs
            tris += n
            placed += pl
        ground = trk.Ground(buf)
        markers = trk.read_markers(buf)
        places = {d: trk.start_places(markers, d) for d in trk.DIRECTIONS}
        print("%s: %d instances, %d triangles, %d batches; collision %d polygons; start places %s" % (
            track, len(placed), tris, len(batches), ground.n, {d: len(p) for d, p in places.items()}))
        # the camera over the track, not outside its sky
        import numpy as np
        pts = np.array([m[3] for label, s, m, _ in placed if "SKY" not in s.full_name.upper()] or [[0, 0, 0]], float)
        lo, hi = pts.min(0), pts.max(0)
        cam = ((lo + hi) / 2, float(np.linalg.norm(hi - lo)) * 0.6, 35)
        return batches, tris, cam, ground, places

    def shown(res):
        if not res:
            return
        batches, tris, cam, ground, places = res
        view.TrackViewer(app, track, batches, tris, cam, ground, places, trk.DIRECTIONS, icon=g.ICON)
        app.say("the track viewer: Take the car's place puts you on the starting grid; with Collision you drive on "
                "the road (click the view first)")
    app.run("put %s together" % track, work, shown)
