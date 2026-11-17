"""Light and dark themes for the window. "System" follows Windows' own setting for apps (HKCU ...\\Themes\\Personalize,
AppsUseLightTheme); the button in the head goes System -> Light -> Dark -> System, and the choice is kept in the settings.

Light is Windows' own look (ttk's vista theme and the system's colours). Dark is ttk's clam theme coloured dark, the classic
Tk widgets (lists, texts, the preview canvas) coloured by hand, and Windows' dark title bar (DwmSetWindowAttribute 20).
Windows opened later (viewers, Help, dialogs) take the theme when they first show."""

import tkinter as tk
from tkinter import ttk

MODES = ("system", "light", "dark")
LABELS = {"system": "◐ System", "light": "☀ Light", "dark": "☾ Dark"}

DARK = dict(bg="#202124", panel="#2b2d31", field="#1b1c1f", fg="#e8e8e8", muted="#a9adb4", select="#3b6fd4",
            selfg="#ffffff", border="#3c3f45", button="#34373d", active="#40444b", heading="#2f3237")
LIGHT = dict(bg="SystemButtonFace", panel="SystemButtonFace", field="SystemWindow", fg="SystemWindowText",
             muted="#666666", select="SystemHighlight", selfg="SystemHighlightText", border="#a0a0a0",
             button="SystemButtonFace", active="SystemButtonFace", heading="SystemButtonFace")
MUTED = {"#666", "#666666", "#555", "#555555", "#a9adb4"}


def system_dark():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except (ImportError, OSError):
        return False


class Theme:
    def __init__(self, app, mode="system"):
        self.app = app
        self.mode = mode if mode in MODES else "system"
        self.style = ttk.Style(app)
        self.native = self.style.theme_use()
        self.dark = False
        app.bind_class("Toplevel", "<Map>", self._on_map, add="+")
        app.bind("<Map>", self._on_map, add="+")

    # -- what is wanted
    def resolve(self):
        return system_dark() if self.mode == "system" else self.mode == "dark"

    def next_mode(self):
        self.mode = MODES[(MODES.index(self.mode) + 1) % len(MODES)]
        return self.mode

    def label(self):
        return LABELS[self.mode]

    # -- applying it
    def apply(self):
        self.dark = self.resolve()
        p = DARK if self.dark else LIGHT
        s = self.style
        if self.dark:
            s.theme_use("clam")
            s.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["field"],
                        bordercolor=p["border"], darkcolor=p["panel"], lightcolor=p["panel"], troughcolor=p["field"],
                        selectbackground=p["select"], selectforeground=p["selfg"], insertcolor=p["fg"],
                        focuscolor=p["select"])
            s.configure("TFrame", background=p["bg"])
            s.configure("TLabel", background=p["bg"], foreground=p["fg"])
            s.configure("TLabelframe", background=p["bg"], bordercolor=p["border"])
            s.configure("TLabelframe.Label", background=p["bg"], foreground=p["fg"])
            s.configure("TButton", background=p["button"], foreground=p["fg"], bordercolor=p["border"], padding=4)
            s.map("TButton", background=[("pressed", p["select"]), ("active", p["active"])],
                  foreground=[("disabled", p["muted"])])
            s.configure("TCheckbutton", background=p["bg"], foreground=p["fg"], indicatorbackground=p["field"])
            s.configure("TRadiobutton", background=p["bg"], foreground=p["fg"], indicatorbackground=p["field"])
            s.map("TCheckbutton", background=[("active", p["bg"])], indicatorbackground=[("selected", p["select"])])
            s.map("TRadiobutton", background=[("active", p["bg"])], indicatorbackground=[("selected", p["select"])])
            s.configure("TEntry", fieldbackground=p["field"], foreground=p["fg"], insertcolor=p["fg"])
            s.configure("TCombobox", fieldbackground=p["field"], background=p["button"], foreground=p["fg"],
                        arrowcolor=p["fg"])
            s.map("TCombobox", fieldbackground=[("readonly", p["field"])], foreground=[("readonly", p["fg"])],
                  selectbackground=[("readonly", p["field"])], selectforeground=[("readonly", p["fg"])])
            s.configure("TNotebook", background=p["bg"], bordercolor=p["border"])
            s.configure("TNotebook.Tab", background=p["panel"], foreground=p["muted"], padding=(8, 3))
            s.map("TNotebook.Tab", background=[("selected", p["bg"])], foreground=[("selected", p["fg"])])
            s.configure("Treeview", background=p["field"], fieldbackground=p["field"], foreground=p["fg"])
            s.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["selfg"])])
            s.configure("Treeview.Heading", background=p["heading"], foreground=p["fg"], bordercolor=p["border"])
            s.map("Treeview.Heading", background=[("active", p["active"])])
            s.configure("TScrollbar", background=p["button"], troughcolor=p["field"], arrowcolor=p["fg"],
                        bordercolor=p["border"])
            s.configure("TPanedwindow", background=p["bg"])
            s.configure("TSeparator", background=p["border"])
            self.app.option_add("*TCombobox*Listbox.background", p["field"])
            self.app.option_add("*TCombobox*Listbox.foreground", p["fg"])
            self.app.option_add("*TCombobox*Listbox.selectBackground", p["select"])
        else:
            s.theme_use(self.native)
            self.app.option_add("*TCombobox*Listbox.background", "SystemWindow")
            self.app.option_add("*TCombobox*Listbox.foreground", "SystemWindowText")
            self.app.option_add("*TCombobox*Listbox.selectBackground", "SystemHighlight")
        self.app.configure(background=p["bg"])
        for w in self.app.winfo_children():
            self._paint(w, p)
        self._paint(self.app, p)
        for top in self._toplevels():
            self._title_bar(top)

    def _toplevels(self):
        out = [self.app]
        stack = list(self.app.winfo_children())
        while stack:
            w = stack.pop()
            if isinstance(w, tk.Toplevel):
                out.append(w)
            stack.extend(w.winfo_children())
        return out

    def _on_map(self, e):
        w = e.widget
        if isinstance(w, (tk.Toplevel, tk.Tk)) and getattr(w, "_themed", None) != self.dark:
            w._themed = self.dark
            p = DARK if self.dark else LIGHT
            if isinstance(w, tk.Toplevel):
                try:
                    w.configure(background=p["bg"])
                except tk.TclError:
                    pass
                for c in w.winfo_children():
                    self._paint(c, p)
            self._title_bar(w)

    def _paint(self, w, p):
        """The classic Tk widgets by hand; ttk labels with a muted colour get the theme's muted one."""
        try:
            cls = w.winfo_class()
            if cls in ("Listbox",):
                w.configure(background=p["field"], foreground=p["fg"], selectbackground=p["select"],
                            selectforeground=p["selfg"], highlightbackground=p["border"],
                            highlightcolor=p["select"])
            elif cls == "Text":
                w.configure(background=p["field"], foreground=p["fg"], insertbackground=p["fg"],
                            selectbackground=p["select"], selectforeground=p["selfg"],
                            highlightbackground=p["border"])
            elif cls == "Canvas":
                if not getattr(w, "_keep_bg", False):
                    w.configure(highlightbackground=p["bg"])
            elif cls == "Label":
                if str(w.cget("background")) not in ("black", "#000000"):
                    w.configure(background=p["bg"], foreground=p["fg"])
            elif cls in ("Frame", "Toplevel"):
                w.configure(background=p["bg"])
            elif cls == "TLabel":
                fg = str(w.cget("foreground"))
                if fg in MUTED:
                    w.configure(foreground=p["muted"])
        except tk.TclError:
            pass
        for c in w.winfo_children():
            self._paint(c, p)

    def _title_bar(self, w):
        """Windows' dark (or light) title bar for a window (Windows 10 1809 and later)."""
        try:
            import ctypes
            w.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(w.winfo_id())
            value = ctypes.c_int(1 if self.dark else 0)
            for attr in (20, 19):           # DWMWA_USE_IMMERSIVE_DARK_MODE, and its number before 20H1
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value),
                                                             ctypes.sizeof(value)) == 0:
                    break
            # the frame is drawn again only when the window changes: nudge it
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
        except Exception:       # an older Windows draws its own title bar
            pass
