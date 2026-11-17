#!/bin/sh
# Builds ModManager.exe: the window with Python, numpy, Pillow, Tk, PyOpenGL (the car viewer), OpenCV (reading
# videos) and codec/hp2codec.dll inside, one file that needs nothing installed.
# Needs PyInstaller, PyOpenGL, pyopengltk and opencv-python-headless (python -m pip install --user pyinstaller pyopengl pyopengltk
# opencv-python-headless). Its build files go to build/ (BUILD= to change).
set -e
HERE="$(cd "$(dirname "$0")" && pwd -W 2>/dev/null || pwd)"
WORK="${BUILD:-$HERE/build}"
cd "$HERE"
[ -f codec/hp2codec.dll ] || sh codec/build.sh
python -m PyInstaller --noconfirm --clean --onefile --windowed --name ModManager \
    --icon "$HERE/modmanager.ico" --add-data "$HERE/modmanager.ico;." \
    --add-binary "$HERE/codec/hp2codec.dll;." --add-data "$HERE/seen_files.txt;." --add-data "$HERE/icons;icons" \
    --version-file "$HERE/version_info.txt" \
    --hidden-import OpenGL.platform.win32 --hidden-import OpenGL.arrays.numpymodule \
    --hidden-import OpenGL.arrays.ctypesarrays --hidden-import OpenGL.arrays.lists \
    --hidden-import OpenGL.arrays.numbers --hidden-import OpenGL.arrays.strings \
    --collect-submodules pyopengltk \
    --distpath "${DIST:-$HERE}" --workpath "$WORK" --specpath "$WORK" \
    "$HERE/hp2assets_gui.py"
echo "built ${DIST:-$HERE}/ModManager.exe"
