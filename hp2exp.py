"""The Experimental tab: a car of a later game (Underground 1 for now) put in the place of an HP2 car (the game has exactly
64 car types and no free one), and a car's characteristics as the menus show them, with the physics behind them."""

import glob
import os
import tkinter as tk
from tkinter import filedialog, ttk

import hp2assets as cli


class ExperimentalTab:
    SAFE = "BMWM5"

    def __init__(self, app, nb):
        self.app = app
        self.donor_root = None
        self.stats = None
        outer = ttk.Frame(nb, padding=6)
        nb.add(outer, text="Experimental")
        inner = ttk.Notebook(outer)
        inner.pack(fill="both", expand=True)
        left = ttk.Frame(inner, padding=8)
        inner.add(left, text="Car from Underground 1")
        ttk.Label(left, text="A car of another game in the place of an HP2 car (the game has 64 car types and no "
                             "free one).", foreground="#666").pack(anchor="w", pady=(0, 6))
        f = inner
        row = ttk.Frame(left)
        row.pack(fill="x")
        ttk.Label(row, text="Game folder:").pack(side="left")
        self.donor_dir = tk.StringVar(value=app.settings.get("donor", ""))
        ttk.Entry(row, textvariable=self.donor_dir).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row, text="Browse…", command=self.browse).pack(side="left")
        ttk.Button(row, text="Open", command=self.open_donor).pack(side="left", padx=4)
        self.donor_info = ttk.Label(left, text="Underground 1 for now; the later games come as their files are tried.")
        self.donor_info.pack(anchor="w", pady=4)
        mid = ttk.Frame(left)
        mid.pack(fill="both", expand=True)
        lf = ttk.Frame(mid)
        lf.pack(side="left", fill="y")
        ttk.Label(lf, text="Its cars").pack(anchor="w")
        self.donor_cars = tk.Listbox(lf, width=18, height=16, exportselection=False)
        self.donor_cars.pack(fill="y", expand=True)
        opts = ttk.Frame(mid, padding=(10, 0))
        opts.pack(side="left", fill="both", expand=True)
        ttk.Label(opts, text="In the place of (HP2 car):").pack(anchor="w")
        self.target = ttk.Combobox(opts, state="readonly", width=20)
        self.target.pack(anchor="w")
        ttk.Label(opts, justify="left", foreground="#666", text=(
            "BMWM5 is the safest: its own folder, no reward or cheat\nunlocks it, nothing in the code names it. A car "
            "and its HP\nversion share one folder: both change.")).pack(anchor="w", pady=(2, 8))
        self.fit = tk.StringVar(value="real")
        ttk.Radiobutton(opts, text="Real size: the HP2 car's wheels move to the new body", variable=self.fit,
                        value="real").pack(anchor="w")
        ttk.Radiobutton(opts, text="Fit: the body is scaled to the HP2 car's wheels (physics unchanged)",
                        variable=self.fit, value="fit").pack(anchor="w")
        self.wheels = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Its wheels and tyre picture", variable=self.wheels).pack(anchor="w", pady=(6, 0))
        self.lights = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Its lamps (headlights and brake lights: off, on, broken)",
                        variable=self.lights).pack(anchor="w")
        b = ttk.Frame(opts)
        b.pack(anchor="w", pady=10)
        ttk.Button(b, text="View it as it is", command=self.view_donor).pack(side="left")
        ttk.Button(b, text="Convert and compare…", command=self.convert).pack(side="left", padx=6)
        ttk.Label(opts, justify="left", foreground="#666", text=(
            "The skins become colours: the new body's own pictures (badges,\ngrilles) go into the skin beside colour "
            "swatches. The collision,\nthe engine sound, the wipers and the scuffs stay the HP2 car's.\nRestore: the "
            "Cars tab (geometry), Textures (CARS/TEXTURES.tex),\nCar physics (GLOBALB).")).pack(anchor="w")

        right = ttk.Frame(inner, padding=8)
        inner.add(right, text="Car stats")
        ttk.Label(right, text="Car type:").pack(anchor="w")
        self.stat_car = ttk.Combobox(right, state="readonly", width=22)
        self.stat_car.pack(anchor="w")
        self.stat_car.bind("<<ComboboxSelected>>", lambda e: self.show_stats())
        self.stat_note = ttk.Label(right, text="", foreground="#666", justify="left")
        self.stat_note.pack(anchor="w", pady=(2, 6))
        grid = ttk.Frame(right)
        grid.pack(anchor="w")
        self.stat_vars = {}
        import hp2stats as st
        rows = list(zip(st.SPEC_KEYS, st.SPEC_TITLES)) + [
            ("Mass", "Mass (tonnes)"), ("power", "Power x (torque curve)"), ("grip", "Grip x (tyres)"),
            ("SpeedLimiter", "Top speed limiter (mph)"), ("Brake", "Brakes"), ("Steering", "Steering"),
            ("NumGears", "Gears (1..6)"), ("final", "Final drive"), ("Drag", "Drag")]
        for i, (k, title) in enumerate(rows):
            ttk.Label(grid, text=title).grid(row=i, column=0, sticky="w", pady=1)
            v = tk.StringVar()
            ttk.Entry(grid, textvariable=v, width=28 if k in ("full_name", "short_name") else 12).grid(
                row=i, column=1, sticky="w", padx=6)
            self.stat_vars[k] = v
        ttk.Button(right, text="Write into the game", command=self.write_stats).pack(anchor="w", pady=(10, 2))
        ttk.Label(right, justify="left", foreground="#666", text=(
            "The texts go into all six languages. Every\nnumber of the physics is in the Car physics tab.")).pack(
            anchor="w")

        # ---- a disc image of the game as it is now
        disc = ttk.Frame(inner, padding=8)
        inner.add(disc, text="Disc image")
        ttk.Label(disc, justify="left", text=(
            "A disc image of the game with every change made here, for PCSX2, OPL or a disc for a PS2. The original "
            "image\ngives the boot files, the PS2 logo and the system modules; the game's archive is made again from "
            "the installed game.")).pack(anchor="w")
        g = ttk.Frame(disc)
        g.pack(anchor="w", pady=8, fill="x")
        self.iso_src, self.iso_dst = tk.StringVar(value=app.settings.get("iso", "")), tk.StringVar()
        for r, (title, var, cmd) in enumerate((("The original image (.iso):", self.iso_src, self.pick_iso_src),
                                               ("The new image:", self.iso_dst, self.pick_iso_dst))):
            ttk.Label(g, text=title).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Entry(g, textvariable=var, width=80).grid(row=r, column=1, sticky="we", padx=6)
            ttk.Button(g, text="Browse…", command=cmd).grid(row=r, column=2)
        ttk.Button(disc, text="Make the image", command=self.make_iso).pack(anchor="w", pady=(4, 8))
        ttk.Label(disc, justify="left", foreground="#666", text=(
            "The original must be the disc the game was installed from; it is only read. What goes in is the game's own "
            "files: the port's\ntranslations, its menu pages and its settings stay in the port. Textures of a new size are "
            "not recommended on a disc yet\n(they are named before the image is made); models much denser than the "
            "game's own may lose parts of a frame "
            "on a PS2, where the port has room to spare.\nThe image is read back and checked when it is made. Try it in "
            "PCSX2 before you burn a disc.")).pack(anchor="w")

    # ---- the disc image
    def pick_iso_src(self):
        p = filedialog.askopenfilename(title="The original disc image", filetypes=[("Disc image", "*.iso")])
        if p:
            self.iso_src.set(p)
            if not self.iso_dst.get():
                base = os.path.splitext(p)[0]
                self.iso_dst.set(base + " (modded).iso")

    def pick_iso_dst(self):
        p = filedialog.asksaveasfilename(title="The new disc image", defaultextension=".iso",
                                         filetypes=[("Disc image", "*.iso")])
        if p:
            self.iso_dst.set(p)

    def make_iso(self):
        from tkinter import messagebox
        import hp2iso
        src, dst = self.iso_src.get().strip(), self.iso_dst.get().strip()
        if not src or not os.path.isfile(src):
            return self.app.say("choose the original disc image")
        if not dst:
            return self.app.say("choose where the new image goes")
        if os.path.abspath(src) == os.path.abspath(dst):
            return self.app.say("the new image must be another file than the original")
        if os.path.exists(dst) and not messagebox.askyesno("Disc image", "%s is there already. Replace it?" % dst,
                                                           parent=self.app):
            return
        self.app.settings["iso"] = src
        self.app.save()
        data = self.app.data()

        def work():
            for line in hp2iso.ps2_warnings(data):
                print("warning: " + line)
            rep = hp2iso.build(src, data, dst, log=print)
            bad = hp2iso.check(dst, data, log=print)
            if rep["over_dvd5"]:
                print("warning: the image is larger than a single-layer DVD (4.38 GB): fine for PCSX2 and OPL, a "
                      "dual-layer disc to burn")
            return bad

        def done(bad):
            if bad is None:
                return
            self.app.say("the disc image is made: %s%s" % (dst, "" if not bad else
                                                             " - BUT %d files did not read back right" % bad))
        self.app.run("make a disc image", work, done)

    # ---- the other game's cars
    def browse(self):
        d = filedialog.askdirectory(title="The game's folder (with its program and CARS)")
        if d:
            self.donor_dir.set(d)
            self.open_donor()

    def open_donor(self):
        import hp2donor as dn
        d = self.donor_dir.get()
        root = dn.find_game_root(d) if d and os.path.isdir(d) else None
        self.donor_cars.delete(0, "end")
        if not root:
            self.donor_info.configure(text="No game found there.")
            return
        game = dn.detect_game(root)
        self.donor_root = root
        self.app.settings["donor"] = d
        self.app.save()
        cars = dn.list_cars(root)
        for c in cars:
            self.donor_cars.insert("end", c)
        ok = "" if game in dn.GAMES else "  (its cars are not read yet)"
        self.donor_info.configure(text="%s: %d car folders in %s%s" % (game, len(cars), root, ok))

    def donor_car(self):
        import hp2donor as dn
        s = self.donor_cars.curselection()
        if not s or not self.donor_root:
            self.app.say("choose a car of the other game")
            return None
        try:
            car = dn.DonorCar(self.donor_root, self.donor_cars.get(s[0]))
        except (SystemExit, ValueError, OSError) as e:
            self.app.say("%s: %s" % (self.donor_cars.get(s[0]), e))
            return None
        if not car.lods():
            self.app.say("%s: no stock parts (a traffic car or a parts folder): not supported yet" % car.car)
            return None
        return car

    def view_donor(self):
        import numpy as np
        import hp2assets_gui as g
        import hp2view as view
        car = self.donor_car()
        if car is None:
            return
        meshes = []
        for s in car.stock_parts(car.lods()[0]):
            mats = []
            for m in s.materials:
                rgba, kind = car.picture(m.texture)
                if rgba is None:
                    rgba = np.full((2, 2, 4), (40, 50, 60, 140), np.uint8)
                mats.append(("%08X" % (m.texture or 0), rgba, m.indices))
            meshes.append((s.pos, s.normal, s.uv, None, mats))
        w = car.wheel(car.lods()[0])
        view.MeshViewer(self.app, "%s (%s)" % (car.car, car.game), [(car.car, view.mesh_batches(meshes))],
                        icon=g.ICON)

    def convert(self):
        import hp2assets_gui as g
        import hp2car as carinfo
        import hp2convert as cv
        import hp2view as view
        car = self.donor_car()
        target = self.target.get()
        if car is None or not target:
            return
        data = self.app.data()
        opts = cv.Options(fit=self.fit.get(), donor_wheels=self.wheels.get(), lights=self.lights.get())

        def shown(res):
            if not res:
                return
            names, rgba_now = cli.car_pictures(data, target)
            _, rgba_new = cli.car_pictures(data, target, {cli.CAR_TEXTURES: res.tex_bytes})
            ctype_now = cli.car_type_of(data, target)
            ctype_new = carinfo.car_type(carinfo.car_type_records(res.globalb_bytes), target) \
                if res.globalb_bytes else ctype_now
            skins = carinfo.skins(target, names.values())

            def write():
                def work():
                    cli.replace_file(cli.car_file(data, target), res.geo_bytes)
                    cli.replace_file(os.path.join(data, cli.CAR_TEXTURES), res.tex_bytes)
                    if res.globalb_bytes:
                        cli.replace_file(os.path.join(data, "GLOBAL", "GLOBALB.BUN"), res.globalb_bytes)
                    print("written: %s's geometry, CARS/TEXTURES.tex%s (the disc's kept as .orig)" % (
                        target, ", GLOBALB.BUN" if res.globalb_bytes else ""))
                self.app.run("write %s as %s" % (car.car, target), work, lambda _: self.app.load_game())
            v = view.CarViewer(self.app, target, [("%s now" % target, res.geo_before),
                                                  ("%s from %s" % (target, car.car), res.geo_after)],
                               names, rgba_new, ctype_new, skins, 1, icon=g.ICON,
                               actions=[("Write into the game", write), ("Cancel", lambda: None)],
                               scene_pictures=[(rgba_now, ctype_now), (rgba_new, ctype_new)])
            self.app.say("the viewer shows %s now and after; Write puts it into the game" % target)
        self.app.run("convert %s into %s" % (car.car, target), lambda: cv.convert(data, target, car, opts), shown)

    # ---- stats
    def load(self):
        import hp2stats as st
        data = self.app.data()
        self.stats = st.Stats(data)
        names = self.stats.car_names()
        self.target["values"] = sorted(os.path.basename(os.path.dirname(p))
                                       for p in glob.glob(os.path.join(data, "CARS", "*", "GEOMETRY.geo")))
        if not self.target.get() and self.SAFE in self.target["values"]:
            self.target.set(self.SAFE)
        self.stat_car["values"] = names
        if not self.stat_car.get() and names:
            self.stat_car.set(self.SAFE if self.SAFE in names else names[0])
        self.show_stats()
        if self.donor_dir.get() and not self.donor_root:
            self.open_donor()

    def show_stats(self):
        car = self.stat_car.get()
        if not car or self.stats is None:
            return
        texts, own = self.stats.texts(car)
        ph = self.stats.physics(car)
        v = self.stat_vars
        for k, s in texts.items():
            v[k].set(s)
        v["Mass"].set("%g" % ph["Mass"])
        v["power"].set("1")
        v["grip"].set("1")
        for k in ("SpeedLimiter", "Brake", "Steering", "Drag"):
            v[k].set("%g" % ph[k])
        v["NumGears"].set(str(ph["NumGears"]))
        v["final"].set("%g" % ph["FinalDriveRear"])
        shared = self.stats.shared_with(car)
        note = "" if own else "No texts of its own: it shows the first row's (the Corvette's).\n"
        if shared:
            note += "The same texts show for: %s" % ", ".join(shared[:6])
        self.stat_note.configure(text=note)

    def write_stats(self):
        import hp2stats as st
        car = self.stat_car.get()
        if not car:
            return
        v = self.stat_vars
        try:
            langs = self.stats.set_texts(car, {k: v[k].get() for k in st.SPEC_KEYS})
            cur = self.stats.physics(car)
            vals = {"Mass": float(v["Mass"].get()), "SpeedLimiter": float(v["SpeedLimiter"].get()),
                    "Brake": float(v["Brake"].get()), "Steering": float(v["Steering"].get()),
                    "Drag": float(v["Drag"].get()), "NumGears": int(v["NumGears"].get())}
            final = float(v["final"].get())
            if abs(final - cur["FinalDriveRear"]) > 1e-6:
                vals["FinalDriveRear"] = vals["FinalDriveFront"] = final
            vals = {k: x for k, x in vals.items() if abs(float(x) - float(cur[k])) > 1e-6}
            lines = self.stats.apply_physics(car, vals, float(v["power"].get()), float(v["grip"].get()))
        except ValueError as e:
            return self.app.say("error: %s" % e)
        for l in lines:
            self.app.say(l)
        self.stats.write(langs, bool(lines))
        self.app.say("%s: texts in %d languages, %s" % (car, len(langs), "physics written" if lines else
                                                         "physics unchanged"))
        self.load()
