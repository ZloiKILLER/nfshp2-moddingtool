"""More tabs: every file of the install (and whether the game uses it), and the track viewer."""

import os
import tkinter as tk
from tkinter import ttk


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
            if flt and flt not in e.rel.upper():
                continue
            folder, _, name = e.rel.rpartition("/")
            parent = ""
            if folder:
                if folder not in folders:
                    folders[folder] = self.tree.insert("", "end", text=folder + "/", open=False)
                parent = folders[folder]
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
