"""The mod manager's other tabs: tracks, car physics, texts, menu screens, sound and movies. Each takes the App (hp2assets_gui)
for its game folder, its log and its jobs."""

import os
import struct
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import hp2assets as cli


def _tree(parent, columns, widths, height=20, show_tree=True):
    f = ttk.Frame(parent)
    t = ttk.Treeview(f, columns=[c for c, _ in columns], height=height, selectmode="extended",
                     show="tree headings" if show_tree else "headings")
    for (c, title), w in zip(columns, widths[1:]):
        t.heading(c, text=title)
        t.column(c, width=w, anchor="w")
    if show_tree:
        t.column("#0", width=widths[0])
    sb = ttk.Scrollbar(f, command=t.yview)
    t.configure(yscrollcommand=sb.set)
    t.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return f, t


def _ask_dir(app, title):
    d = filedialog.askdirectory(title=title, initialdir=app.settings.get("out"))
    if d:
        app.settings["out"] = d
        app.save()
    return d


# ---- tracks -------------------------------------------------------------------------------------------------------------

class TracksTab:
    def __init__(self, app, nb):
        self.app = app
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Tracks")
        left = ttk.Frame(f)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Tracks (* changed)").pack(anchor="w")
        self.list = tk.Listbox(left, width=22, exportselection=False)
        self.list.pack(fill="y", expand=True)
        mid = ttk.Frame(f, padding=(10, 0))
        mid.pack(side="left", fill="both", expand=True)
        ttk.Label(mid, justify="left", text=(
            "A track is TRACKS\\TRACKB<nn>.BUN: ten lists of solids (the same format as the cars) placed by scenery\n"
            "sections, and its pictures in TEX<nn>TRACK.tex and TEX<nn>LOCATION.tex (the Textures tab changes those).\n\n"
            "Export writes <TRACK>.obj, every solid in its own space (the road and the ground are in world space),\n"
            "which is the file to edit and import back, and <TRACK>_world.obj, the whole track put together, to look\n"
            "at. A solid used by several instances changes all of them.\n\n"
            "Import rebuilds the solids the OBJ names and makes the culling boxes follow. The collision, the AI's\n"
            "routes and the cameras stay as they are: cars drive on the old ground, so move the road only a little.")
                  ).pack(anchor="w")
        btns = ttk.Frame(f)
        btns.pack(side="left", fill="y")
        ttk.Button(btns, text="View the track", command=self.view).pack(fill="x", pady=2)
        ttk.Button(btns, text="Export OBJ…", command=lambda: self.export(False)).pack(fill="x", pady=(16, 2))
        ttk.Button(btns, text="Export mesh only…", command=lambda: self.export(True)).pack(fill="x", pady=2)
        ttk.Button(btns, text="Import OBJ…", command=self.import_obj).pack(fill="x", pady=(16, 2))
        ttk.Button(btns, text="Restore the disc's", command=self.restore).pack(fill="x", pady=(16, 2))

    def load(self):
        import hp2track as trk
        self.list.delete(0, "end")
        for name, p in trk.track_files(self.app.data()):
            self.list.insert("end", name + ("  *" if os.path.exists(p + ".orig") else ""))

    def track(self):
        s = self.list.curselection()
        return self.list.get(s[0]).split()[0] if s else None

    def view(self):
        import hp2tabs2
        t = self.track()
        if not t:
            return self.app.say("choose a track")
        hp2tabs2.view_track(self.app, t)

    def export(self, bare):
        t = self.track()
        if not t:
            return self.app.say("choose a track")
        out = _ask_dir(self.app, "Export %s into" % t)
        if out:
            data = self.app.data()
            self.app.run("export %s" % t, lambda: cli.export_track(data, t, out, bare))

    def import_obj(self):
        t = self.track()
        if not t:
            return self.app.say("choose a track")
        obj = filedialog.askopenfilename(title="OBJ for %s" % t, filetypes=[("Wavefront OBJ", "*.obj")],
                                         initialdir=self.app.settings.get("out"))
        if not obj:
            return
        data = self.app.data()

        def ask(res):
            if not res:
                return
            path, old, new = res
            if messagebox.askyesno("Import", "Write the rebuilt %s into the game?\nThe disc's file is kept as .orig." % t):
                self.app.run("write %s" % t, lambda: cli.replace_file(path, new), lambda _: self.load())
        self.app.run("check %s" % os.path.basename(obj), lambda: cli.rebuild_track(data, t, obj), ask)

    def restore(self):
        import hp2track as trk
        t = self.track()
        if t and messagebox.askyesno("Restore", "Put the disc's %s back?" % t):
            p = dict(trk.track_files(self.app.data()))[t]
            self.app.run("restore %s" % t, lambda: cli.restore_file(p), lambda _: self.load())


# ---- physics ------------------------------------------------------------------------------------------------------------

class PhysicsTab:
    def __init__(self, app, nb):
        import hp2physics as ph
        self.ph = ph
        self.app = app
        self.pending = {}           # car -> {field: value}
        self.buf = b""
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Car physics")
        left = ttk.Frame(f)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Car types (+ edited)").pack(anchor="w")
        self.list = tk.Listbox(left, width=22, exportselection=False)
        self.list.pack(fill="y", expand=True)
        self.list.bind("<<ListboxSelect>>", lambda e: self.show())
        mid = ttk.Frame(f, padding=(8, 0))
        mid.pack(side="left", fill="both", expand=True)
        ttk.Label(mid, text="Double click a value to change it. HP versions (…HP) are their own records.").pack(anchor="w")
        tf, self.tree = _tree(mid, [("value", "value"), ("disc", "on the disc"), ("note", "")], [230, 110, 110, 300], 24)
        tf.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self.edit)
        btns = ttk.Frame(f)
        btns.pack(side="left", fill="y")
        ttk.Button(btns, text="Write into the game", command=self.write).pack(fill="x", pady=2)
        ttk.Button(btns, text="Discard edits", command=self.discard).pack(fill="x", pady=2)
        ttk.Button(btns, text="Export all (JSON)…", command=self.export).pack(fill="x", pady=(16, 2))
        ttk.Button(btns, text="Import JSON…", command=self.import_json).pack(fill="x", pady=2)
        ttk.Button(btns, text="Restore GLOBALB…", command=self.restore).pack(fill="x", pady=(16, 2))
        ttk.Label(btns, justify="left", text="The mass and the size make\nthe inertia again.\n\nThe menus' specs (0-60,\n"
                  "top speed, BHP) are texts:\nthe Texts tab.").pack(pady=8)

    def path(self):
        return os.path.join(self.app.data(), "GLOBAL", "GLOBALB.BUN")

    def load(self):
        self.buf = open(self.path(), "rb").read()
        orig = self.path() + ".orig"
        self.disc = open(orig, "rb").read() if os.path.exists(orig) else self.buf
        self.records = {r.name: r for r in self.ph.records(self.buf)}
        self.disc_records = {r.name: r for r in self.ph.records(self.disc)}
        self.list.delete(0, "end")
        for n in self.records:
            self.list.insert("end", n + ("  +" if n in self.pending else ""))

    def car(self):
        s = self.list.curselection()
        return self.list.get(s[0]).split()[0] if s else None

    def show(self):
        car = self.car()
        self.tree.delete(*self.tree.get_children())
        if not car:
            return
        vals = self.ph.read_values(self.records[car].raw)
        disc = self.ph.read_values(self.disc_records[car].raw) if car in self.disc_records else vals
        vals.update(self.pending.get(car, {}))
        for g in self.ph.GROUPS:
            gid = self.tree.insert("", "end", text=g, open=True)
            for off, fmt, name, gg, note in self.ph.FIELDS:
                if gg == g:
                    v = vals[name]
                    mark = "" if abs(float(v) - float(disc[name])) < 1e-6 else " *"
                    self.tree.insert(gid, "end", iid=name, text=name, values=("%g%s" % (v, mark), "%g" % disc[name],
                                                                             note))

    def edit(self, e):
        car = self.car()
        item = self.tree.focus()
        if not car or item not in self.ph.BY_NAME:
            return
        cur = self.tree.item(item, "values")[0].split()[0]
        v = simpledialog.askstring(car, "%s (%s):" % (item, self.ph.BY_NAME[item][4] or "number"), initialvalue=cur,
                                   parent=self.tree)
        if v is None:
            return
        try:
            num = int(v) if self.ph.BY_NAME[item][1] in "ib" else float(v)
        except ValueError:
            return self.app.say("%s: not a number" % v)
        self.pending.setdefault(car, {})[item] = num
        self.show()
        self.load_marks()

    def load_marks(self):
        sel = self.list.curselection()
        names = list(self.records)
        self.list.delete(0, "end")
        for n in names:
            self.list.insert("end", n + ("  +" if n in self.pending else ""))
        if sel:
            self.list.selection_set(sel[0])

    def write(self):
        if not self.pending:
            return self.app.say("nothing edited")
        try:
            new, lines = self.ph.apply(self.buf, self.pending)
        except ValueError as e:
            return self.app.say("error: %s" % e)
        for l in lines:
            self.app.say(l)
        cli.replace_file(self.path(), new)
        self.app.say("written %s (the disc's is GLOBALB.BUN.orig)" % self.path())
        self.pending = {}
        self.load()
        self.show()

    def discard(self):
        self.pending = {}
        self.load_marks()
        self.show()

    def export(self):
        p = filedialog.asksaveasfilename(title="Car physics", defaultextension=".json", initialfile="physics.json",
                                         filetypes=[("JSON", "*.json")], initialdir=self.app.settings.get("out"))
        if p:
            n = self.ph.export_json(self.buf, p)
            self.app.say("%d car types -> %s" % (n, p))

    def import_json(self):
        import json
        p = filedialog.askopenfilename(title="Car physics", filetypes=[("JSON", "*.json")],
                                       initialdir=self.app.settings.get("out"))
        if not p:
            return
        try:
            data = json.load(open(p, encoding="utf-8"))
        except ValueError as e:
            return self.app.say("%s: %s" % (p, e))
        for car, groups in data.items():
            flat = {}
            for k, v in groups.items():
                flat.update(v if isinstance(v, dict) else {k: v})
            if car in self.records:
                vals = self.ph.read_values(self.records[car].raw)
                diff = {k: v for k, v in flat.items() if k in vals and abs(float(v) - float(vals[k])) > 1e-6}
                if diff:
                    self.pending.setdefault(car, {}).update(diff)
        self.app.say("%s: %d car types with changes; Write puts them into the game" % (p, len(self.pending)))
        self.load_marks()
        self.show()

    def restore(self):
        if messagebox.askyesno("Restore", "Put the disc's GLOBALB.BUN back?\n\nIt also holds menu pictures and screens: "
                               "their changes go too."):
            cli.restore_file(self.path())
            self.pending = {}
            self.load()
            self.show()


# ---- texts --------------------------------------------------------------------------------------------------------------

class TextsTab:
    def __init__(self, app, nb):
        import hp2text as tx
        self.tx = tx
        self.app = app
        self.files = {}
        self.pending = {}           # (lang, id) -> text
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Texts")
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Label(row, text="Filter:").pack(side="left")
        self.filter = tk.StringVar()
        e = ttk.Entry(row, textvariable=self.filter, width=30)
        e.pack(side="left", padx=4)
        e.bind("<KeyRelease>", lambda ev: self.fill())
        self.with_port = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="With the port's texts (data/lang)", variable=self.with_port,
                        command=self.fill).pack(side="left", padx=8)
        ttk.Label(row, text="   Double click a line to change it.  @ is a new line in the game, \\x80.. the pad's "
                  "buttons, %s %d are filled in.").pack(side="left")
        main = ttk.Frame(f)
        main.pack(fill="both", expand=True, pady=6)
        cols = [(l, l.title()) for l in tx.TABLES]
        tf, self.tree = _tree(main, cols, [70] + [200] * 6, 24)
        self.tree.heading("#0", text="id")
        tf.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self.edit)
        btns = ttk.Frame(main)
        btns.pack(side="left", fill="y", padx=6)
        ttk.Button(btns, text="Write into the game", command=self.write).pack(fill="x", pady=2)
        ttk.Button(btns, text="Discard edits", command=self.discard).pack(fill="x", pady=2)
        ttk.Button(btns, text="Export table…", command=self.export).pack(fill="x", pady=(16, 2))
        ttk.Button(btns, text="Import table…", command=self.import_tsv).pack(fill="x", pady=2)
        ttk.Button(btns, text="Restore the disc's", command=self.restore).pack(fill="x", pady=(16, 2))
        ttk.Label(btns, justify="left", text="The table is tab-separated\nUTF-8: Excel, LibreOffice\nor any editor.\n\n"
                  "Only characters of the\ngame's fonts show.").pack(pady=8)

    def load(self):
        self.files = self.tx.load_all(self.app.data(), self.tx.TABLES)
        self.port = self.tx.port_texts(self.app.data())
        self.fill()

    def port_text(self, lang, i):
        if not self.with_port.get():
            return None
        return getattr(self, "port", {}).get(lang, ({}, {}))[0].get(i)

    def text(self, lang, i):
        if (lang, i) in self.pending:
            return self.pending[(lang, i)]
        p = self.port_text(lang, i)
        if p is not None:
            return p
        lf = self.files.get(lang)
        return self.tx.to_text(lf.texts.get(i, b""), lf.cyrillic) if lf else ""

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        if not self.files:
            return
        flt = self.filter.get().lower()
        first = next(iter(self.files.values()))
        n = 0
        for i in sorted(first.texts):
            row = [self.text(l, i) for l in self.tx.TABLES]
            if flt and flt not in str(i) and not any(flt in r.lower() for r in row):
                continue
            mark = " *" if any((l, i) in self.pending for l in self.tx.TABLES) else ""
            if any(self.port_text(l, i) is not None for l in self.tx.TABLES):
                mark += " port"
            self.tree.insert("", "end", iid=str(i), text="%d%s" % (i, mark), values=row)
            n += 1
            if n >= 3000:
                break
        if self.with_port.get():
            # the port's own strings: its menus, in English and the translations of data/lang
            own = {}
            for lang, (_, strings) in getattr(self, "port", {}).items():
                for en, t in strings.items():
                    own.setdefault(en, {})[lang] = t
            for k, (en, tr) in enumerate(sorted(own.items())):
                row = [tr.get(l, en if l == "ENGLISH" else "") for l in self.tx.TABLES]
                if flt and not any(flt in r.lower() for r in row):
                    continue
                self.tree.insert("", "end", iid="p:%d" % k, text="port", values=row)

    def edit(self, e):
        item = self.tree.focus()
        if not item:
            return
        if item.startswith("p:"):
            return self.app.say("the port's own strings are in data/lang/<LANGUAGE>.txt (nfshp2-port-win, tools/recomp/make_lang.py)")
        i = int(item)
        d = tk.Toplevel(self.tree)
        d.title("Text %d" % i)
        d.transient(self.tree.winfo_toplevel())
        vars_ = {}
        for r, l in enumerate(self.tx.TABLES):
            ttk.Label(d, text=l.title()).grid(row=r, column=0, sticky="w", padx=6, pady=2)
            v = tk.StringVar(value=self.text(l, i))
            ttk.Entry(d, textvariable=v, width=90).grid(row=r, column=1, padx=6, pady=2)
            vars_[l] = v

        def ok():
            for l, v in vars_.items():
                s = v.get()
                try:
                    self.tx.from_text(s, bool(self.files.get(l) and self.files[l].cyrillic))
                except ValueError as ex:
                    messagebox.showerror("Text", str(ex), parent=d)
                    return
                if s != self.text(l, i):
                    self.pending[(l, i)] = s
            d.destroy()
            self.fill()
            if self.tree.exists(item):
                self.tree.see(item)
        b = ttk.Frame(d)
        b.grid(row=len(self.tx.TABLES), column=0, columnspan=2, pady=6)
        ttk.Button(b, text="OK", command=ok).pack(side="left", padx=4)
        ttk.Button(b, text="Cancel", command=d.destroy).pack(side="left")

    def write(self):
        if not self.pending:
            return self.app.say("nothing edited")
        table = {}
        for (l, i), s in self.pending.items():
            table.setdefault(l, {})[i] = s
        changed, lines = self.tx.apply(self.files, table)
        for l in lines:
            self.app.say(l)
        for lang in changed:
            p = self.tx.lang_path(self.app.data(), lang)
            cli.replace_file(p, self.files[lang].build())
            self.app.say("written %s" % p)
        self.pending = {}
        self.load()

    def discard(self):
        self.pending = {}
        self.fill()

    def export(self):
        p = filedialog.asksaveasfilename(title="Texts", defaultextension=".tsv", initialfile="texts.tsv",
                                         filetypes=[("Tab-separated", "*.tsv *.txt")],
                                         initialdir=self.app.settings.get("out"))
        if p:
            n = self.tx.export_tsv(self.app.data(), p)
            self.app.say("%d texts in %d languages -> %s" % (n, len(self.files), p))

    def import_tsv(self):
        p = filedialog.askopenfilename(title="Texts", filetypes=[("Tab-separated", "*.tsv *.txt")],
                                       initialdir=self.app.settings.get("out"))
        if not p:
            return
        try:
            table = self.tx.read_tsv(p)
        except (ValueError, IndexError) as e:
            return self.app.say("%s: %s" % (p, e))
        n = 0
        for l, texts in table.items():
            for i, s in texts.items():
                if l in self.files and i in self.files[l].texts and s != self.text(l, i):
                    self.pending[(l, i)] = s
                    n += 1
        self.app.say("%s: %d texts differ; Write puts them into the game" % (p, n))
        self.fill()

    def restore(self):
        if messagebox.askyesno("Restore", "Put the disc's texts of all languages back?"):
            for lang in self.tx.TABLES:
                p = self.tx.lang_path(self.app.data(), lang)
                if os.path.exists(p + ".orig"):
                    cli.restore_file(p)
            self.pending = {}
            self.load()


# ---- menu screens -------------------------------------------------------------------------------------------------------

class ScreensTab:
    def __init__(self, app, nb):
        import hp2screens as sc
        self.sc = sc
        self.app = app
        self.lib = None
        self.bufs = {}
        self.dirty = set()
        self.screen = None
        self.img = None
        self.scale = 1.0
        self.drag = None
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Menu screens")
        left = ttk.Frame(f)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="File").pack(anchor="w")
        self.file = ttk.Combobox(left, values=list(sc.FILES), state="readonly", width=24)
        self.file.pack(anchor="w")
        self.file.bind("<<ComboboxSelected>>", lambda e: self.fill_screens())
        self.source = tk.StringVar(value="files")
        src = ttk.Frame(left)
        src.pack(anchor="w", pady=(6, 0))
        ttk.Radiobutton(src, text="The files", variable=self.source, value="files",
                        command=self.fill_screens).pack(side="left")
        ttk.Radiobutton(src, text="As the port draws them", variable=self.source, value="port",
                        command=self.fill_screens).pack(side="left")
        pb = ttk.Frame(left)
        pb.pack(anchor="w")
        ttk.Button(pb, text="Read the port's menus…", command=self.capture).pack(side="left")
        ttk.Button(pb, text="Open a dump…", command=self.open_dump).pack(side="left", padx=4)
        ttk.Label(left, text="Screens").pack(anchor="w", pady=(6, 0))
        self.screens = tk.Listbox(left, width=28, height=12, exportselection=False)
        self.screens.pack(fill="x")
        self.screens.bind("<<ListboxSelect>>", lambda e: self.show_screen())
        ttk.Label(left, text="Objects").pack(anchor="w", pady=(6, 0))
        of, self.objs = _tree(left, [("kind", "kind")], [170, 50], 14)
        of.pack(fill="both", expand=True)
        self.objs.bind("<<TreeviewSelect>>", lambda e: self.pick())
        mid = ttk.Frame(f, padding=(8, 0))
        mid.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(mid, width=640, height=480, bg="black", highlightthickness=0)
        self.canvas.pack(anchor="nw")
        self.canvas.bind("<ButtonPress-1>", self.press)
        self.canvas.bind("<B1-Motion>", self.motion)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.show_hidden = tk.BooleanVar()
        ttk.Checkbutton(mid, text="Show hidden objects", variable=self.show_hidden,
                        command=self.redraw).pack(anchor="w")
        ttk.Label(mid, justify="left", text="Drag an object to move it. The preview draws what the data says; the game's "
                  "code moves some objects\n(slides, the scrolling blurb, the car list) and fills the texts it prints.").pack(
            anchor="w")
        right = ttk.Frame(f)
        right.pack(side="left", fill="y")
        self.fields = {}
        for key, label in (("x", "X"), ("y", "Y"), ("scale_x", "Scale X"), ("scale_y", "Scale Y"), ("layer", "Layer 0..28"),
                           ("visible", "Visible 0/1"), ("colour", "Colour RGBA hex"), ("text", "Text"),
                           ("text_id", "Text id (0: the text)"), ("texture", "Picture")):
            ttk.Label(right, text=label).pack(anchor="w")
            v = tk.StringVar()
            ttk.Entry(right, textvariable=v, width=26).pack(anchor="w")
            self.fields[key] = v
        ttk.Button(right, text="Apply", command=self.apply_fields).pack(fill="x", pady=(8, 2))
        ttk.Button(right, text="Write into the game", command=self.write).pack(fill="x", pady=(16, 2))
        ttk.Button(right, text="Discard edits", command=self.load).pack(fill="x", pady=2)
        ttk.Button(right, text="Save preview PNG…", command=self.save_png).pack(fill="x", pady=(16, 2))
        ttk.Button(right, text="Restore the disc's", command=self.restore).pack(fill="x", pady=(16, 2))

    def load(self):
        data = self.app.data()
        self.lib = self.sc.Library(data)
        saved = self.app.settings.get("port_dump")
        if getattr(self, "dump", None) is None and saved and os.path.isfile(saved):
            try:
                self.dump = self.sc.read_dump(self.app.settings["port_dump"])
            except (OSError, ValueError):
                self.dump = None
        self.bufs = {}
        self.dirty = set()
        for rel in self.sc.FILES:
            p = os.path.join(data, rel)
            if os.path.isfile(p):
                self.bufs[rel] = bytearray(open(p, "rb").read())
        if not self.file.get():
            self.file.set(self.sc.FILES[0])
        self.fill_screens()

    def port_mode(self):
        return self.source.get() == "port"

    def fill_screens(self):
        rel = self.file.get()
        self.screen_list = self.sc.read_screens(rel, self.bufs[rel]) if rel in self.bufs else []
        if self.port_mode():
            dump = getattr(self, "dump", None) or {}
            if not dump:
                self.app.say("no dump of the port's menus yet: Read the port's menus, or Open a dump")
            files = self.screen_list
            self.screen_list = dump.get(rel, [])
            self.sc.mark_port_objects(self.screen_list, files)
        self.screens.delete(0, "end")
        for s in self.screen_list:
            self.screens.insert("end", "%s (%d)" % (s.name, len(s.objects)))
        self.screen = None
        self.objs.delete(*self.objs.get_children())
        self.canvas.delete("all")

    def show_screen(self):
        sel = self.screens.curselection()
        if not sel:
            return
        self.screen = self.screen_list[sel[0]]
        self.objs.delete(*self.objs.get_children())
        for k, o in enumerate(self.screen.objects):
            mark = getattr(o, "port", "")
            self.objs.insert("", "end", iid=str(k), text=(o.name or "NONAME") + (" [port: %s]" % mark if mark else ""),
                             values=("text" if o.is_text else "picture") + ("" if o.visible else " (hidden)"))
        self.redraw()

    def current(self):
        sel = self.objs.selection()
        return self.screen.objects[int(sel[0])] if sel and self.screen else None

    def redraw(self):
        if not self.screen:
            return
        from PIL import ImageTk
        img = self.sc.render(self.screen, self.lib, self.scale, hidden=self.show_hidden.get())
        self.img = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.img, anchor="nw")
        o = self.current()
        if o is not None:
            x0, y0, x1, y1 = self.sc.object_box(o, self.lib)
            self.canvas.create_rectangle(x0 * self.scale, y0 * self.scale, x1 * self.scale, y1 * self.scale,
                                         outline="#ffcc00", tags="sel")

    def pick(self):
        o = self.current()
        if o is None:
            return
        if self.port_mode():
            self.redraw()
            return
        f = self.fields
        f["x"].set("%g" % o.x)
        f["y"].set("%g" % o.y)
        f["scale_x"].set("%g" % o.scale_x)
        f["scale_y"].set("%g" % o.scale_y)
        f["layer"].set(str(o.layer))
        f["visible"].set(str(o.visible))
        if o.is_text:
            f["colour"].set("%08X" % self._rgba_word(o.colour))
            f["text"].set(o.inline.decode("latin-1"))
            f["text_id"].set(str(o.text_id))
            f["texture"].set("")
        else:
            f["colour"].set("%08X" % self._rgba_word(o.colours()[0]))
            f["text"].set("")
            f["text_id"].set("")
            f["texture"].set(self.lib.names.get(o.texture, "%08X" % o.texture))
        self.redraw()

    @staticmethod
    def _rgba_word(c):
        """The stored word (A<<24|B<<16|G<<8|R) shown as RRGGBBAA, and back (the same swap)."""
        return ((c & 255) << 24) | ((c >> 8 & 255) << 16) | ((c >> 16 & 255) << 8) | (c >> 24 & 255)

    def apply_fields(self):
        o = self.current()
        if o is None:
            return
        if self.port_mode():
            return self.app.say("the port's view is read only: change the files")
        f = self.fields
        try:
            o.x, o.y = float(f["x"].get()), float(f["y"].get())
            o.scale_x, o.scale_y = float(f["scale_x"].get()), float(f["scale_y"].get())
            o.layer = int(f["layer"].get())
            o.visible = int(f["visible"].get())
            col = self._rgba_word(int(f["colour"].get(), 16))
            if o.is_text:
                o.colour = col
                o.text_id = int(f["text_id"].get() or 0)
                o.set_inline(f["text"].get().encode("latin-1"))
            else:
                o.set_colours([col] * 4)
                name = f["texture"].get().strip()
                h = next((k for k, n in self.lib.names.items() if n.upper() == name.upper()), None)
                if h is None:
                    try:
                        h = int(name, 16)
                    except ValueError:
                        raise ValueError("no picture %s" % name)
                o.texture = h
        except (ValueError, UnicodeEncodeError) as e:
            return self.app.say("error: %s" % e)
        self.dirty.add(self.file.get())
        self.redraw()

    def press(self, e):
        o = self.current()
        if o is None or self.port_mode():
            return
        self.drag = (e.x, e.y, o.x, o.y)

    def motion(self, e):
        o = self.current()
        if o is None or not self.drag:
            return
        x0, y0, ox, oy = self.drag
        dx, dy = (e.x - x0) / self.scale, (e.y - y0) / self.scale
        self.canvas.delete("sel")
        bx0, by0, bx1, by1 = self.sc.object_box(o, self.lib)
        self.canvas.create_rectangle((bx0 + dx) * self.scale, (by0 + dy) * self.scale, (bx1 + dx) * self.scale,
                                     (by1 + dy) * self.scale, outline="#ffcc00", tags="sel")

    def release(self, e):
        o = self.current()
        if o is None or not self.drag:
            return
        x0, y0, ox, oy = self.drag
        self.drag = None
        dx, dy = (e.x - x0) / self.scale, (e.y - y0) / self.scale
        if abs(dx) < 1 and abs(dy) < 1:
            return
        o.x, o.y = round(ox + dx), round(oy + dy)
        self.dirty.add(self.file.get())
        self.pick()

    def open_dump(self):
        p = filedialog.askopenfilename(title="A dump of HP2_FLDUMP", initialdir=self.app.settings.get("out"))
        if p:
            self.load_dump(p)

    def load_dump(self, p):
        try:
            self.dump = self.sc.read_dump(p)
        except (OSError, ValueError) as e:
            return self.app.say("%s: %s" % (p, e))
        self.app.settings["port_dump"] = p
        self.app.save()
        n = sum(len(v) for v in self.dump.values())
        self.app.say("the port's menus: %d screens from %s" % (n, p))
        self.source.set("port")
        self.fill_screens()

    def capture(self):
        """Starts the game with HP2_FLDUMP, waits for the menus' project, closes it, and reads what the port made."""
        import subprocess
        import time
        game = self.app.game.get()
        exe = os.path.join(game, "speed.exe")
        if not os.path.isfile(exe):
            return self.app.say("%s: no speed.exe" % game)
        if not messagebox.askyesno("The port's menus", "The game starts for a few seconds, until its menus are "
                                   "loaded, and closes by itself. Go on?"):
            return
        dump = os.path.join(tempfile.gettempdir(), "hp2mm_fldump.txt")

        def work():
            if os.path.exists(dump):
                os.remove(dump)
            env = dict(os.environ, HP2_FLDUMP=dump)
            p = subprocess.Popen([exe], cwd=game, env=env)
            t0 = time.time()
            try:
                while time.time() - t0 < 90:
                    time.sleep(1)
                    if p.poll() is not None:
                        break
                    if os.path.exists(dump) and "project 255842fd" in open(dump, encoding="latin-1").read():
                        time.sleep(2)
                        break
            finally:
                if p.poll() is None:
                    p.terminate()
            if not os.path.exists(dump):
                raise SystemExit("the game wrote no dump (an older speed.exe? HP2_FLDUMP came with 2026-11-14's)")
            return dump
        self.app.run("read the port's menus", work, lambda d: d and self.load_dump(d))

    def write(self):
        if not self.dirty:
            return self.app.say("nothing edited")
        for rel in sorted(self.dirty):
            p = os.path.join(self.app.data(), rel)
            cli.replace_file(p, bytes(self.bufs[rel]))
            self.app.say("written %s (the disc's is %s.orig)" % (p, os.path.basename(p)))
        self.dirty = set()

    def save_png(self):
        if not self.screen:
            return
        p = filedialog.asksaveasfilename(title="Preview", defaultextension=".png", initialfile=self.screen.name + ".png",
                                         filetypes=[("PNG", "*.png")], initialdir=self.app.settings.get("out"))
        if p:
            self.sc.render(self.screen, self.lib, 1.0, self.show_hidden.get()).save(p)

    def restore(self):
        rel = self.file.get()
        if rel and messagebox.askyesno("Restore", "Put the disc's %s back?\n\nIt also holds pictures%s." % (
                rel, " and the car physics" if "GLOBALB" in rel else "")):
            cli.restore_file(os.path.join(self.app.data(), rel))
            self.load()


# ---- sound --------------------------------------------------------------------------------------------------------------

class SoundTab:
    def __init__(self, app, nb):
        import hp2sound as so
        self.so = so
        self.app = app
        self.obj = None             # Bank, Jukebox or Speech
        self.kind = None
        self.dirty = False
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Sound")
        row = ttk.Frame(f)
        row.pack(fill="x")
        ttk.Label(row, text="Source:").pack(side="left")
        self.source = ttk.Combobox(row, state="readonly", width=40)
        self.source.pack(side="left", padx=4)
        self.source.bind("<<ComboboxSelected>>", lambda e: self.open_source())
        self.info = ttk.Label(row, text="")
        self.info.pack(side="left", padx=10)
        main = ttk.Frame(f)
        main.pack(fill="both", expand=True, pady=6)
        tf, self.tree = _tree(main, [("len", "seconds"), ("rate", "Hz"), ("kind", "")], [320, 80, 70, 160], 24)
        tf.pack(side="left", fill="both", expand=True)
        btns = ttk.Frame(main)
        btns.pack(side="left", fill="y", padx=6)
        for text, cmd in (("Play", self.play), ("Stop", self.stop),
                          ("Export selected (WAV)…", lambda: self.export(True)),
                          ("Export all (WAV)…", lambda: self.export(False)),
                          ("Replace with a WAV…", self.replace),
                          ("Import a folder of WAVs…", self.import_folder),
                          ("Write into the game", self.write),
                          ("Discard edits", self.open_source),
                          ("Export all (WAV tree)…", self.export_tree),
                          ("Import a WAV tree…", self.import_tree),
                          ("BAN & DAT Rewrite…", self.speech_anew),
                          ("Restore the disc's", self.restore)):
            ttk.Button(btns, text=text, command=cmd).pack(fill="x", pady=1)

    def load(self):
        data = self.app.data()
        vals = ["Effects: %s" % b for b in self.so.bank_paths(data)]
        if os.path.isfile(os.path.join(data, self.so.MUSIC)):
            vals.insert(0, "Music: JUKEBOXM.JBC")
        vals += ["Speech: %s" % l for l in self.so.speech_languages(data)]
        self.source["values"] = vals
        if vals and not self.source.get():
            self.source.set(vals[0])
            self.open_source()

    def files(self):
        data = self.app.data()
        kind, name = self.source.get().split(": ", 1)
        if kind == "Effects":
            return list(self.so.bank_paths(data)[name])
        if kind == "Music":
            return [os.path.join(data, self.so.MUSIC)]
        return list(self.so.speech_paths(data, name))

    def open_source(self):
        src = self.source.get()
        if not src:
            return
        kind, name = src.split(": ", 1)
        self.kind = kind
        self.dirty = False
        self.tree.delete(*self.tree.get_children())
        fs = self.files()
        if kind == "Effects":
            self.obj = self.so.Bank(open(fs[0], "rb").read(), open(fs[1], "rb").read())
            for k, (n, idx) in enumerate(self.obj.sounds()):
                p = self.obj.patches[idx[0]]
                secs = (len(self.obj.audio[idx[0]]) // 16 - 1) * 28 / max(1, p.rate)
                kinds = ("stereo" if len(idx) > 1 else "mono") + (", loops" if p.loops else "")
                self.tree.insert("", "end", iid=str(k), text=n, values=("%.2f" % secs, p.rate, kinds))
        elif kind == "Music":
            self.obj = self.so.Jukebox(open(fs[0], "rb").read())
            for i, t in enumerate(self.obj.tunes):
                secs = (len(t[2]) - 48) / 2 / 16 * 28 / self.so.MUSIC_RATE
                self.tree.insert("", "end", iid=str(i), text=self.obj.name(i), values=("%.0f" % secs,
                                                                                       self.so.MUSIC_RATE, "stereo"))
        else:
            self.obj = self.so.Speech(open(fs[0], "rb").read(), open(fs[1], "rb").read())
            for b, bk in enumerate(self.obj.banks):
                gid = self.tree.insert("", "end", iid="b%d" % b, text=("bank %d  %s" % (b, self.obj.name(b))).strip(),
                                       values=("", "", "%d clips" % bk.count))
                for i in range(bk.count):
                    s, e = self.obj.clip_range(b, i)
                    secs = max(0, e - s - 48) / 16 * 28 / self.so.SPEECH_RATE
                    self.tree.insert(gid, "end", iid="%d:%d" % (b, i), text="clip %d" % i,
                                     values=("%.2f" % secs, self.so.SPEECH_RATE, "mono"))
        text = ", ".join(os.path.basename(p) for p in fs)
        if kind == "Effects":
            cars = self.so.engine_banks(self.app.data()).get(name.upper())
            if cars:
                text += "  (the engine of %s)" % ", ".join(cars)
            if name in self.so.BANK_ALIASES:
                text = "%s: %s" % (name, text)
        self.info.configure(text=text)

    def _items(self, selected):
        if selected:
            ids = [i for i in self.tree.selection() if not i.startswith("b")]
        elif self.kind == "Speech":
            ids = ["%d:%d" % (b, i) for b, bk in enumerate(self.obj.banks) for i in range(bk.count)]
        else:
            ids = list(self.tree.get_children())
        return ids

    def pcm(self, iid):
        """(pcm (n, ch), rate, name) of an item."""
        if self.kind == "Effects":
            n, idx = self.obj.sounds()[int(iid)]
            return self.obj.pcm(idx), self.obj.patches[idx[0]].rate, n
        if self.kind == "Music":
            i = int(iid)
            return self.obj.pcm(i), self.so.MUSIC_RATE, "%02d %s" % (i, self.obj.name(i).split("-")[1]
                                                                    if "-" in self.obj.name(i) else self.obj.name(i))
        b, i = map(int, iid.split(":"))
        return self.obj.pcm(b, i)[:, None], self.so.SPEECH_RATE, "bank%04d_clip%02d" % (b, i)

    def play(self):
        import hp2movie as mv
        sel = [i for i in self.tree.selection() if not i.startswith("b")]
        if not sel:
            return
        pcm, rate, _ = self.pcm(sel[0])
        p = os.path.join(tempfile.gettempdir(), "hp2mm_play.wav")
        self.stop()
        mv.write_wav(p, pcm, rate)
        try:
            import winsound
            winsound.PlaySound(p, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except (ImportError, RuntimeError) as e:
            self.app.say("cannot play: %s" % e)

    def stop(self):
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except ImportError:
            pass

    def export(self, selected):
        import hp2movie as mv
        ids = self._items(selected)
        if not ids:
            return self.app.say("choose sounds")
        out = _ask_dir(self.app, "Export sounds into")
        if not out:
            return

        keys = {self._key(i) for i in ids}
        kind, obj = self.kind, self.obj

        def work():
            # the names Import a folder reads back (hp2sound.items)
            n = self.so.export_source(kind, obj, out, keys)
            print("%d WAVs -> %s" % (n, out))
        self.app.run("export sounds", work)

    def _key(self, iid):
        """The item's key in hp2sound.items: an effect's patch indices, a tune's number, (bank, clip)."""
        if self.kind == "Effects":
            return tuple(self.obj.sounds()[int(iid)][1])
        if self.kind == "Music":
            return int(iid)
        return tuple(map(int, iid.split(":")))

    def _iid(self, key):
        if self.kind == "Effects":
            return str(next(k for k, (_, idx) in enumerate(self.obj.sounds()) if tuple(idx) == key))
        if self.kind == "Music":
            return str(key)
        return "%d:%d" % key

    def import_folder(self):
        """A folder of WAVs into the open source, by the names Export gives them; Write puts them into the game."""
        folder = _ask_dir(self.app, "A folder of WAVs for %s" % self.source.get())
        if not folder:
            return
        kind, obj = self.kind, self.obj

        def work():
            rep = self.so.import_folder(kind, obj, folder)
            for f in rep["unknown"]:
                print("%s: no sound of that name here" % f)
            for f, why in rep["bad"]:
                print("%s: %s" % (f, why))
            print("%d replaced, %d as they were, %d not matched" % (len(rep["changed"]), len(rep["same"]),
                                                                    len(rep["unknown"]) + len(rep["bad"])))
            return rep

        def done(rep):
            if not rep or not rep["changed"]:
                return self.app.say("nothing replaced")
            self.dirty = True
            by_stem = {stem: key for key, stem, _ in self.so.items(kind, obj)}
            for stem in rep["changed"]:
                iid = self._iid(by_stem[stem])
                if self.tree.exists(iid):
                    self.tree.item(iid, text=self.tree.item(iid, "text").rstrip(" *") + " *")
            self.app.say("%d sounds replaced; Write puts them into the game" % len(rep["changed"]))
        self.app.run("import a folder into %s" % self.source.get(), work, done)

    def export_tree(self):
        out = _ask_dir(self.app, "Export all the game's sound into")
        if not out:
            return
        data = self.app.data()
        self.app.run("export all sound", lambda: self.so.export_all(data, out))

    def import_tree(self):
        folder = _ask_dir(self.app, "A WAV tree (Effects, Music, Speech) to put in")
        if not folder:
            return
        if not messagebox.askyesno(
                "Import a WAV tree", "Every WAV under %s goes into the game by its folder and name, as Export all "
                "writes them: Effects\\<BANK>, Music, Speech\\<LANGUAGE>. A part of the tree is enough.\n\nWAVs that "
                "are the sound as it is are left alone. The files changed keep the disc's copy (.orig).\n\nClose the "
                "game first. Go on?" % folder, parent=self.app):
            return
        data = self.app.data()
        self.dirty = False
        self.app.run("import a WAV tree", lambda: self.so.import_tree(data, folder, cli.replace_file),
                     lambda _: self.open_source())

    def speech_anew(self):
        """One step: the disc's speech, the folder's WAVs in at their own length, written into the game."""
        lang = self.source.get().split(": ", 1)[1] if self.kind == "Speech" else None
        folder = _ask_dir(self.app, "Speech WAVs: a folder of them%s, or a tree with Speech\\<LANGUAGE>"
                          % (" (for %s)" % lang if lang else ""))
        if not folder:
            return
        data = self.app.data()
        pairs = self.so.speech_folders(data, folder, lang)
        if not pairs:
            return messagebox.showinfo(
                "BAN & DAT Rewrite", "No speech WAVs in %s.\n\nThey go by the names Export gives them "
                "(bank0003_19AddPrime_clip00.wav), in the folder itself with a Speech source chosen above, or in "
                "Speech\\<LANGUAGE> folders." % folder, parent=self.app)
        if not messagebox.askyesno(
                "BAN & DAT Rewrite", "%s\n\nFor each: the speech as it came from the disc, with these WAVs in, every "
                "clip at its own length, written into the game. What earlier imports put in is replaced: a clip that is "
                "not in the folder is the disc's again.\n\nClose the game first. Go on?"
                % "\n".join("%s: %s" % p for p in pairs), parent=self.app):
            return
        self.dirty = False
        self.app.run("BAN & DAT Rewrite", lambda: self.so.import_speech_anew(data, folder, cli.replace_file, lang),
                     lambda _: self.open_source())

    def replace(self):
        sel = [i for i in self.tree.selection() if not i.startswith("b")]
        if len(sel) != 1:
            return self.app.say("choose one sound")
        wav = filedialog.askopenfilename(title="WAV", filetypes=[("WAV", "*.wav")],
                                         initialdir=self.app.settings.get("out"))
        if not wav:
            return
        iid = sel[0]

        def work():
            pcm, rate = self.so.read_wav_any(wav)
            if self.kind == "Effects":
                n, idx = self.obj.sounds()[int(iid)]
                self.obj.replace(idx, pcm, rate)
                return "%s replaced" % n
            if self.kind == "Music":
                self.obj.replace(int(iid), pcm, rate)
                return "tune %s replaced" % iid
            b, i = map(int, iid.split(":"))
            how = self.obj.replace(b, i, pcm, rate)
            return "bank %d clip %d replaced (%s)" % (b, i, how)

        def done(msg):
            if msg:
                self.dirty = True
                self.app.say(msg + "; Write puts it into the game")
                self.tree.item(iid, text=self.tree.item(iid, "text").rstrip(" *") + " *")
        self.app.run("replace with %s" % os.path.basename(wav), work, done)

    def write(self):
        if not self.dirty:
            return self.app.say("nothing replaced")
        fs = self.files()
        obj, kind = self.obj, self.kind

        def work():
            if kind == "Effects":
                msh, msb = obj.build()
                cli.replace_file(fs[0], msh)
                cli.replace_file(fs[1], msb)
            elif kind == "Music":
                cli.replace_file(fs[0], obj.build())
            else:
                cli.replace_file(fs[0], bytes(obj.ban))
                cli.replace_file(fs[1], bytes(obj.dat))
            print("written %s (the disc's kept as .orig)" % ", ".join(os.path.basename(p) for p in fs))
        self.dirty = False
        self.app.run("write sound", work, lambda _: self.open_source())

    def restore(self):
        if messagebox.askyesno("Restore", "Put the disc's %s back?" % self.source.get()):
            for p in self.files():
                cli.restore_file(p)
            self.open_source()


# ---- movies -------------------------------------------------------------------------------------------------------------

class MoviesTab:
    def __init__(self, app, nb):
        self.app = app
        self.preview_img = None
        f = ttk.Frame(nb, padding=6)
        nb.add(f, text="Movies")
        tf, self.tree = _tree(f, [("size", "size"), ("frames", "frames"), ("sound", "sound")], [260, 90, 70, 70], 20)
        tf.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.preview())
        right = ttk.Frame(f, padding=(8, 0))
        right.pack(side="left", fill="y")
        self.pic = tk.Label(right, text="", relief="sunken", width=64, height=16)
        self.pic.pack()
        ttk.Button(right, text="Play", command=self.play).pack(fill="x", pady=(10, 2))
        ttk.Button(right, text="Export as AVI…", command=lambda: self.export(True)).pack(fill="x", pady=2)
        ttk.Button(right, text="Export all…", command=lambda: self.export(False)).pack(fill="x", pady=2)
        ttk.Button(right, text="Replace with a video…", command=self.replace).pack(fill="x", pady=(16, 2))
        ttk.Button(right, text="Restore the disc's", command=self.restore).pack(fill="x", pady=(16, 2))
        ttk.Label(right, justify="left", text=(
            "Export: an MJPEG AVI with its sound, for any player or editor.\n\n"
            "Replace: any video OpenCV reads (MP4, AVI, MKV...), scaled to the movie's\n"
            "size and taken at 30 frames a second. The menu movies are 256x384 and\n"
            "shown stretched to the panel; the intro ones are 512x256 with sound,\n"
            "which comes from a WAV (or is silence).")).pack(anchor="w", pady=8)

    def movies(self):
        d = os.path.join(self.app.data(), "MOVIES")
        out = []
        for root, _, files in os.walk(d):
            for fn in sorted(files):
                if fn.upper().endswith(".AVI"):
                    out.append(os.path.relpath(os.path.join(root, fn), self.app.data()).replace("\\", "/"))
        return out

    def load(self):
        import hp2movie as mv
        self.tree.delete(*self.tree.get_children())
        for rel in self.movies():
            p = os.path.join(self.app.data(), rel)
            try:
                a = mv.Avi(p)
                vals = ("%dx%d" % (a.width, a.height), len(a.frames()), "yes" if a.has_sound else "")
                if a.fourcc.lower() != b"mv30":
                    vals = (vals[0], "(%s)" % a.fourcc.decode("latin-1"), vals[2])
            except (ValueError, OSError, struct.error):
                vals = ("?", "", "")
            mark = "  *" if os.path.exists(p + ".orig") else ""
            self.tree.insert("", "end", iid=rel, text=rel[7:] + mark, values=vals)

    def preview(self):
        import hp2movie as mv
        sel = self.tree.selection()
        if not sel:
            return
        try:
            a, n, frames = mv.frames_any(os.path.join(self.app.data(), sel[0]))
            frame = None
            for k, rgb in enumerate(frames):
                frame = rgb
                if k >= min(n - 1, 45):
                    break
        except SystemExit as e:
            self.pic.configure(image="", text=str(e))
            return
        if frame is None:
            return
        from PIL import Image, ImageTk
        img = Image.fromarray(frame)
        img.thumbnail((448, 300))
        self.preview_img = ImageTk.PhotoImage(img)
        self.pic.configure(image=self.preview_img, text="", width=img.width, height=img.height)

    def export(self, selected):
        import hp2movie as mv
        ids = list(self.tree.selection()) if selected else list(self.tree.get_children())
        if not ids:
            return self.app.say("choose movies")
        out = _ask_dir(self.app, "Export movies into")
        if not out:
            return
        data = self.app.data()

        def work():
            for rel in ids:
                dst = os.path.join(out, rel[7:].replace("/", "_"))
                mv.export_movie(os.path.join(data, rel), dst)
        self.app.run("export %d movies" % len(ids), work)

    def play(self):
        sel = self.tree.selection()
        if sel:
            MoviePlayer(self.app, os.path.join(self.app.data(), sel[0]))

    def replace(self):
        import hp2movie as mv
        sel = self.tree.selection()
        if len(sel) != 1:
            return self.app.say("choose one movie")
        rel = sel[0]
        p = os.path.join(self.app.data(), rel)
        video = filedialog.askopenfilename(title="Video for %s" % rel,
                                           filetypes=[("Video", "*.mp4 *.avi *.mkv *.mov *.wmv *.webm *.mpg"),
                                                      ("All", "*.*")], initialdir=self.app.settings.get("out"))
        if not video:
            return
        wav = None
        if mv.Avi(p).has_sound:
            if messagebox.askyesno("Sound", "This movie has sound. Choose a WAV for it?\n(No: silence)"):
                wav = filedialog.askopenfilename(title="Sound for %s" % rel, filetypes=[("WAV", "*.wav")]) or None
        q = simpledialog.askinteger("Quality", "Picture quality, 50 to 95 (higher: larger file):", initialvalue=88,
                                    minvalue=50, maxvalue=95)
        if not q:
            return

        def work():
            cli.backup(p)
            mv.import_movie(p + ".orig", video, p, wav=wav, quality=q)
            print("written %s (the disc's is %s.orig)" % (rel, os.path.basename(p)))
        self.app.run("replace %s" % rel, work, lambda _: self.load())

    def restore(self):
        sel = self.tree.selection()
        if sel and messagebox.askyesno("Restore", "Put the disc's %s back?" % ", ".join(sel)):
            for rel in sel:
                cli.restore_file(os.path.join(self.app.data(), rel))
            self.load()


class MoviePlayer(tk.Toplevel):
    """Plays a movie of the disc: its frames at its rate (frames are dropped to keep time), its sound with winsound."""

    def __init__(self, app, path):
        import time
        import hp2movie as mv
        super().__init__(app)
        self.title(os.path.basename(path))
        self.app = app
        try:
            self.avi, self.n, self.frames = mv.frames_any(path)
        except SystemExit as e:
            self.destroy()
            app.say(str(e))
            return
        self.fps = self.avi.fps or 30.0
        self.label = tk.Label(self, bg="black")
        self.label.pack(fill="both", expand=True)
        self.info = ttk.Label(self, text="")
        self.info.pack(anchor="w")
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.k = -1
        self.img = None
        self.wav = None
        if self.avi.has_sound:
            try:
                pcm = mv.decode_sound(self.avi.sound_bytes())
                self.wav = os.path.join(tempfile.gettempdir(), "hp2mm_movie.wav")
                mv.write_wav(self.wav, pcm, mv.SOUND_RATE)
                import winsound
                winsound.PlaySound(self.wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception as e:      # no sound is still a movie
                app.say("sound: %s" % e)
        self.t0 = time.time()
        self.after(1, self.tick)

    def tick(self):
        import time
        from PIL import Image, ImageTk
        if not self.winfo_exists():
            return
        want = int((time.time() - self.t0) * self.fps)
        frame = None
        while self.k < want:
            try:
                frame = next(self.frames)
            except StopIteration:
                self.info.configure(text="end (%d frames)" % self.n)
                return
            self.k += 1
        if frame is not None:
            img = Image.fromarray(frame)
            if img.width < 400:
                img = img.resize((img.width * 2, img.height * 2))
            self.img = ImageTk.PhotoImage(img)
            self.label.configure(image=self.img)
            self.info.configure(text="frame %d of %d, %.1f s" % (self.k + 1, self.n, (self.k + 1) / self.fps))
        self.after(max(1, int(1000 / self.fps / 2)), self.tick)

    def close(self):
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except ImportError:
            pass
        self.destroy()
