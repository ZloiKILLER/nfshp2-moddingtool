# Technical notes

## Building

The program is Python with one small C library. The release `ModManager.exe` is built from this repository with
PyInstaller as one file that carries everything it needs.

You need:

- Windows 10 or 11, 64-bit;
- Python 3.10 or later (the release is built with 3.14);
- the Python packages: `python -m pip install --user numpy pillow pyopengl pyopengltk opencv-python-headless pyinstaller`;
- [LLVM](https://github.com/llvm/llvm-project/releases)'s `clang` for the codec library (or set `CLANG=` to another
  compiler that makes a Windows DLL);
- a POSIX shell for the scripts, for example the Git Bash that comes with Git for Windows.

Then:

```sh
sh codec/build.sh      # codec/hp2codec.dll: the movie codec, the PS2 sound codec and JDLZ
sh build_exe.sh        # ModManager.exe; build files go to build/ (BUILD= to change), the exe to the repository (DIST= to change)
```

The `.py` files also run without building:

- `python hp2assets_gui.py [GAME]` opens the window. It needs `codec/hp2codec.dll` for movies and sound.
- `python hp2assets.py` does the same work for cars and textures from the command line: `cars`, `export-car`,
  `import-car`, `export-textures`, `import-textures`, `restore` and `verify`. `--help` lists the options.

## Checks

- **`python hp2assets.py verify GAME`** reads every car of an install and checks that:
  - the file written back is byte for byte the disc's;
  - every strip packet encodes again to the same bytes;
  - export to OBJ and import back gives the same triangles, vertices and materials.

  For release 0.14 all 44 cars pass.
- **`ModManager.exe --selftest GAME OUT`** runs every part through the built exe and writes `OUT/selftest.log`. It
  writes nothing to the game. It covers:
  - car export and an import in dry-run mode;
  - texture and movie export;
  - texts, a sound bank and a track rebuilt and compared with the files;
  - a menu screen drawn;
  - the file survey, the port's texts, the track viewer and the car viewer.
- **Files rebuilt without changes** come out byte for byte the disc's: the six language files, the 26 sound banks, the
  music and the tracks.

## Layout

| File | What it is |
|---|---|
| `hp2assets_gui.py` | the window: the Cars and Textures tabs, settings, the self-test; the program's entry point |
| `hp2assets.py` | the command line, and the file handling the window shares (finding the game, `.orig` backups, safe writes) |
| `hp2about.py` | the window's head, Help and About, the program's name and version |
| `hp2theme.py` | the light and dark themes |
| `hp2tabs.py` | the Tracks, Car physics, Texts, Menu screens, Sound and Movies tabs |
| `hp2tabs2.py` | the All files tab and the track viewer window |
| `hp2exp.py` | the Experimental tab |
| `hp2core.py` | bChunk containers, car geometry (eSolid, VU1 strip packets), the name hash |
| `hp2model.py` | car geometry to Wavefront OBJ and back |
| `hp2car.py` | a car put together as the game draws it, from its car type record |
| `hp2tex.py` | texture packs: decode, encode, palettes, mip levels |
| `hp2view.py` | the OpenGL viewers (cars, tracks) |
| `hp2track.py` | tracks: solid lists, instances, the culling tree |
| `hp2physics.py` | the car type records (CarTypeInfo) field by field |
| `hp2stats.py` | the car select screen's stats and the physics numbers behind them |
| `hp2text.py` | the language files, and the port's own texts |
| `hp2screens.py` | the menu screens (Flailer projects): read, draw, change; the port's menu dump |
| `hp2sound.py` | sound banks, the jukebox, speech |
| `hp2movie.py` | movies: AVI in and out, MV30 through the codec library, other codecs through OpenCV |
| `hp2files.py` | the survey of every file, with `seen_files.txt` (files the port read in its recorded demos) |
| `hp2donor.py` | NFS Underground's cars and textures |
| `hp2convert.py` | an Underground car made into an HP2 car |
| `hp2models.py` | the models outside the cars and the tracks: dashboards, the menus' and the race's, the drivers |
| `hp2iso.py` | a disc image: the archive made from the installed game, ISO9660 and UDF made to follow |
| `codec/hp2codec.c` | MV30 decode and encode, PS2 SPU ADPCM decode and encode, JDLZ decompression |
| `icons/`, `modmanager.ico` | the window's icons |
| `version_info.txt` | the exe's file properties |

## How it works

- **Formats.** The game's files are read as the game reads them. The layouts come first of all from NFSHP2-ModSuite's
  research, then from the Windows port's own loaders and renderer and the references below. Each layout was checked
  against the files of the disc.
- **Writing.** Every write goes through one function. The first time a file changes, it copies the file to
  `<file>.orig`. Then it writes the new file in full under a temporary name and renames it over the old one. The port's
  installer may make hard links, so the original is never written into.
- **Car geometry.** On import, polygons are triangulated, grouped by material in the game's drawing order (see-through
  groups such as glass last), turned into triangle strips, and packed into VU1 packets of at most 30 vertices. What OBJ
  cannot carry (the vertex alpha bit, the damage keys) comes from the nearest vertex of the old part. The vertex colours
  are the game's baked light (RGB555, 15 of 31 is the picture as it is).
- **Material names** in the OBJ carry what the strips need: `<texture>__f<strip flags>__l<light material>__n<normals>`,
  for example `VANQUISH_SKIN1__fC180__l0__n1`. A material named only by its texture takes the flags of that texture's
  existing strips.
- **Texture slots.** Some textures are slots that the game fills while it runs (`WINDOW_FRONT`, `TIRE`, `CARBOTTOM`,
  `<CAR>_HEADLIGHT_LEFT`...). On the disc they are hashes only; the program knows the 140 slots the cars use.
- **Movies.** The game's movies are AVI files with MV30 video, a DCT codec of the game's own. The codec library decodes
  every key and inter frame, and the encoder writes key frames only. The sound is the PS2's SPU ADPCM.
- **Underground cars.** Underground's geometry, its JDLZ-packed texture packs and its car and part records are read
  from the PC game. Its parts are mapped to HP2's: the stock body and kit parts, the stock wheel, the stock brake, the
  lamp slots and the glass. The pictures are packed into the car's skin picture. Underground's vertex colours are taken
  as a darkening and turned into HP2's baked light.

## Credits

### The base

**[NFSHP2-ModSuite](https://github.com/TechX1320/NFSHP2-ModSuite)** (NFS HP2 PS2 Mod Suite) by **TechX1320 (Dave
Myers)** and its contributors. This program is built first of all on its work:

- the GLOBALB car data and its car editor;
- the texture packs and the PS2 swizzle;
- the car geometry and the 3D cars;
- the track extraction;
- the language and bundle strings;
- the MSB engine audio;
- the research on converting Underground cars to HP2.

NFSHP2-ModSuite is under the MIT License: Copyright (c) 2026 Dave Myers (TechX1320).

### This program

**ZloiKILLER**:

- the program for the Windows port's installed game: one window with a tab for each kind of asset;
- the viewers;
- the movie and sound codec;
- the menu screens;
- the Underground car conversion;
- the reading of the port's own changes.

### References

- **[reNFSHP2](https://github.com/Romalu86/reNFSHP2)** (R95) by **Romalu86**: the reversed source code of Hot Pursuit 2.
  It was read for the car type records' fields and the movie codec's tables.
- **[NFSHP2-3DS](https://github.com/Octoblimp/NFSHP2-3DS)** by Octoblimp: the format notes on texture packs, solid
  geometry and its winding, and the car type records.
- **[NFS-ModTools](https://github.com/NFSTools/NFS-ModTools)** by NFSTools: the layouts of Underground's geometry and
  textures, the JDLZ compression, and how the PC games are told apart.
- **[nfshp2-port-win](https://github.com/ZloiKILLER/nfshp2-port-win)**, the Windows port: its loaders, renderer and
  movie decoder.

### Inside the release exe

`ModManager.exe` carries these components, each under its own license:

- **Python** 3.14 (PSF License) with **Tcl/Tk** 8.6 (Tcl/Tk License);
- **NumPy** (BSD-3-Clause and others);
- **Pillow** (MIT-CMU);
- **PyOpenGL** (BSD);
- **pyopengltk** (MIT);
- **OpenCV** 5.0, `opencv-python-headless` (Apache 2.0), and its **FFmpeg** build `opencv_videoio_ffmpeg` (LGPL 2.1);
- the **PyInstaller** bootloader (GPL 2.0 with the bootloader exception).

The window's icons are Windows' own stock icons (`shell32.dll`, `imageres.dll`), the property of Microsoft.

Need for Speed: Hot Pursuit 2 and Need for Speed: Underground are the property of Electronic Arts Inc.
