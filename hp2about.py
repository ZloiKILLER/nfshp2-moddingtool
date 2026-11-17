"""The window's head, Help and About, as the port's Saves Manager (nfshp2-port-win, recomp/savestransfer) has them: the game's name and
what the program is for, and on the right Help and About with Windows' own icons for them (imageres.dll, the stock Help
and Info icons). Help is a window of its own over the main one; About is Windows' task dialog."""

import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk

NAME = "NFSHP2 Modding suite"
VERSION = "0.1"                   # the program's own (the exe's file properties), not the game's
AUTHOR = "ZloiKILLER"
YEAR = "2026"
TITLE = "NFS Hot Pursuit 2"
SUBTITLE = "Modding suite: cars, tracks, pictures, texts, menus, sound and movies"

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = getattr(sys, "_MEIPASS", HERE)

HELP_TEXT = """\
The NFSHP2 Modding suite takes the game's cars, tracks, pictures, texts, menus, sound and movies out of the installed PC \
port, shows them, and puts your changes back. It works on the unpacked files the port's setup put in data\\. It does not \
use a disc image.

Every file it changes keeps the disc's copy beside it (<file>.orig) the first time, and Restore puts that copy back. \
A changed file is written whole and then put in the place of the old one, so the install's other copies of it are \
never written into.

THE GAME FOLDER
The folder is found by itself where the port's setup installed the game. If not, press Browse... and choose the \
folder with speed.exe.

CARS
The cars, their parts and their levels of detail.
    View the car: the car put together as the game draws it (body, mirrors, plates, wheels, brakes), with any skin.
    Export OBJ: every part (the file to edit and import back), the whole car, and its pictures: mesh only, the default \
skin, some skins or all of them.
    Import OBJ: any shape. The viewer shows the car now and after, and Write into the game puts it in.
In Blender: import and export with Up Z, Forward Y; keep the object and material names.

TEXTURES
Every picture of a file, as PNG, and back by name. A picture keeps its size and its format.

TRACKS
View the track (fly with W A S D, Q E; Shift goes faster), export the solids as OBJ and import them back. The \
collision and the AI's routes stay as they are: cars drive on the old ground.

CAR PHYSICS
Every number of each car type: wheels, tyres, mass, suspension, gearbox, engine, aerodynamics, brakes, top speed. \
Double click a value to change it. JSON out and in for many cars at once.

TEXTS
The game's texts in its six languages; double click to change a line. With the port's texts shows the port's own \
translations and overrides (data\\lang).

MENU SCREENS
Every menu screen drawn as the game draws it. Drag an object to move it, or change its numbers, colour, text or \
picture. As the port draws them shows the menus with the port's own pages and rows (Read the port's menus starts the \
game for a few seconds to read them).

SOUND
Effects, music and speech: play them, export them as WAV, replace them with your WAV.

MOVIES
Play a movie, export it as an AVI with its sound, or replace it with any video (MP4, AVI, MKV...).

EXPERIMENTAL
    Car from Underground 1: a car of NFS Underground in the place of an HP2 car, with its wheels, brakes, lamps, \
badges and its paints as the skins. The game has 64 car types and no free one: BMWM5 is the safest to replace.
    Car stats: what the car select screen shows (name, 0-60, top speed, power) and the main physics.

ALL FILES
Every file of the install, what it is, and whether the game uses it.

LIMITS
Pictures keep their sizes. A race leaves about 5 MB of the game's memory free for all the cars together. Collision and \
physics do not follow a new shape: change them in Car physics.

FROM A COMMAND LINE
    ModManager.exe [game folder]          the window
    ModManager.exe --selftest GAME OUT     a check of every part, nothing written to the game
    python hp2assets.py --help             the same work without the window (in the program's folder)
"""


def _icon(name, size=16):
    try:
        return tk.PhotoImage(file=os.path.join(BASE, "icons", "%s_%d.png" % (name, size)))
    except tk.TclError:
        return None


def header(app, parent):
    """The head of the window: the game's name and what this is, Help and About on the right."""
    f = ttk.Frame(parent, padding=(10, 8, 10, 2))
    f.pack(fill="x")
    texts = ttk.Frame(f)
    texts.pack(side="left")
    ttk.Label(texts, text=TITLE, font=("Segoe UI Semibold", 16)).pack(anchor="w")
    ttk.Label(texts, text=SUBTITLE, font=("Segoe UI", 11), foreground="#555").pack(anchor="w")
    app._help_icon, app._about_icon = _icon("help"), _icon("about")
    ttk.Button(f, text=" About", image=app._about_icon, compound="left", width=8,
               command=lambda: show_about(app)).pack(side="right")
    ttk.Button(f, text=" Help", image=app._help_icon, compound="left", width=8,
               command=lambda: show_help(app)).pack(side="right", padx=(0, 6))
    if getattr(app, "theme", None) is not None:
        # the theme: System (Windows' own setting), Light, Dark, in turn
        app.theme_text = tk.StringVar(value=app.theme.label())
        ttk.Button(f, textvariable=app.theme_text, width=10, command=app.toggle_theme).pack(side="right",
                                                                                           padx=(0, 6))
    return f


def show_help(app):
    """Help over the main window, which waits for it."""
    w = tk.Toplevel(app)
    w.title("Help - %s" % NAME)
    w.transient(app)
    w.resizable(False, False)
    try:
        w.iconbitmap(os.path.join(BASE, "modmanager.ico"))
    except tk.TclError:
        pass
    head = ttk.Frame(w, padding=(16, 14, 16, 6))
    head.pack(fill="x")
    try:
        from PIL import Image, ImageTk
        img = Image.open(os.path.join(BASE, "modmanager.ico"))
        img.size = (48, 48)
        w._img = ImageTk.PhotoImage(img.convert("RGBA").resize((48, 48)))
        ttk.Label(head, image=w._img).pack(side="left", padx=(0, 12))
    except Exception:       # the head without its picture
        pass
    t = ttk.Frame(head)
    t.pack(side="left")
    ttk.Label(t, text=TITLE, font=("Segoe UI Semibold", 16)).pack(anchor="w")
    ttk.Label(t, text="How to use the modding suite", font=("Segoe UI", 11)).pack(anchor="w")
    body = ttk.Frame(w, padding=(16, 0, 16, 0))
    body.pack(fill="both", expand=True)
    text = tk.Text(body, width=86, height=30, wrap="word", font=("Segoe UI", 9), padx=8, pady=8, relief="solid",
                   borderwidth=1)
    sb = ttk.Scrollbar(body, command=text.yview)
    text.configure(yscrollcommand=sb.set)
    text.insert("1.0", HELP_TEXT)
    text.configure(state="disabled")
    text.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    foot = ttk.Frame(w, padding=(16, 10, 16, 14))
    foot.pack(fill="x")
    ok = ttk.Button(foot, text="OK", width=12, command=w.destroy)
    ok.pack(side="right")
    w.bind("<Return>", lambda e: w.destroy())
    w.bind("<Escape>", lambda e: w.destroy())
    w.update_idletasks()
    x = app.winfo_rootx() + (app.winfo_width() - w.winfo_width()) // 2
    y = app.winfo_rooty() + (app.winfo_height() - w.winfo_height()) // 2
    w.geometry("+%d+%d" % (max(0, x), max(0, y)))
    ok.focus_set()
    w.grab_set()
    app.wait_window(w)


def show_about(app):
    """Windows' task dialog: the name, the version, who made it and when (a message box where there is none)."""
    title = "About - %s" % NAME
    main = "%s\n%s" % (TITLE, NAME)
    content = "Version %s\nMade by %s, %s" % (VERSION, AUTHOR, YEAR)
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = int(app.wm_frame(), 16)
        exe = ctypes.windll.kernel32.GetModuleHandleW(None)
        td = ctypes.windll.comctl32.TaskDialog
        td.argtypes = [wintypes.HWND, wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                       ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        frozen = hasattr(sys, "_MEIPASS")
        # the exe's own icon (its first icon group) when frozen, else Windows' information icon
        icon = ctypes.c_void_p(1 if frozen else 0xFFFD)
        pressed = ctypes.c_int(0)
        hr = td(hwnd, exe if frozen else None, title, main, content, 1, icon, ctypes.byref(pressed))
        if hr == 0:
            return
    except (AttributeError, OSError, ValueError):
        pass
    messagebox.showinfo(title, "%s\n\n%s" % (main, content), parent=app)
