# NFSHP2 Modding suite

A Windows program for modding **Need for Speed: Hot Pursuit 2** (the Blackbox PS2 version, as the
[Windows port](https://github.com/ZloiKILLER/nfshp2-port-win) installs it). It takes the game's assets out of the
installed game, shows them, and puts your changes back:

- cars: models, skins, a 3D viewer;
- textures;
- tracks, with a fly-through viewer;
- car physics and the stats the menus show;
- texts in all six languages;
- menu screens;
- sound effects, music and speech;
- movies, with a player.

Made by ZloiKILLER, based first of all on [NFSHP2-ModSuite](https://github.com/TechX1320/NFSHP2-ModSuite) by
TechX1320. The full list of what can be changed is in [FEATURES.md](FEATURES.md). Building it and how it works
inside are in [TECHNICAL.md](TECHNICAL.md).

**No game data is included.** The program works only on a game you have installed yourself from your own disc.

## What you need

- Windows 10 or 11, 64-bit.
- Hot Pursuit 2 installed by the [Windows port](https://github.com/ZloiKILLER/nfshp2-port-win) from your own disc. The
  program works on the unpacked files that the port's installer puts in the game's `data\` folder. It does not read
  disc images.
- For the Experimental car import only: your own install of the PC game **Need for Speed: Underground**.

## Starting it

1. Download `ModManager.exe` from [Releases](https://github.com/ZloiKILLER/nfshp2-moddingtool/releases).
2. Start it. It is the whole program in one file, with nothing to install. The first start takes a few seconds while it
   unpacks itself.
3. It finds the game where the port installed it. If it cannot, choose the folder that holds the game's `speed.exe`
   (**Browse...**).

**Help** at the top right of the window explains every tab. The button next to it switches between the system theme,
light and dark.

## Your files are safe

- The first time a file is changed, the disc's version is kept beside it as `<file>.orig`.
- **Restore** puts that version back.
- Every change can be looked at first: cars in the viewer before and after, screens as they will be drawn.
- Changes are written to a new file, which then takes the old one's place. A failed write leaves the game as it was.

To be safe, try bigger changes on a copy of the game's folder first. **The game must be closed** while you write into
it.
