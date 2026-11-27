# Features

What the NFSHP2 Modding suite 0.14 can change, tab by tab. Any change can be undone. The first change of a file keeps the
disc's version as `<file>.orig`, and **Restore the disc's** in the tab of that file puts it back. The Experimental tab
writes car, texture, physics and text files, so its changes are undone in the Cars, Textures, Car physics and Texts tabs.

| Tab | What you change | Game files |
|---|---|---|
| [Cars](#cars) | car models, through OBJ, with a 3D viewer | `CARS\<CAR>\GEOMETRY.geo` |
| [Textures](#textures) | any picture of the game, through PNG | `.tex` and `.BUN` files |
| [Tracks](#tracks) | track models, through OBJ, with a fly-through viewer | `TRACKS\TRACKB<nn>.BUN` |
| [Models](#models) | the dashboards, the menus' and the race's models, the drivers, through OBJ | `CARS\<CAR>\DASHGEOM.geo`, `FRONTEND\FRONTB.BUN`, `GLOBAL\INGAMEB.BUN`, `GLOBAL\CHARACTERSA.geo` |
| [Car physics](#car-physics) | every physics number of each car type | `GLOBAL\GLOBALB.BUN` |
| [Texts](#texts) | every text, in six languages | `LANGUAGES\FE_<LANGUAGE>.lang` |
| [Menu screens](#menu-screens) | where things are on the menus and how they look | `FRONTEND\FRONTB.BUN`, `GLOBAL\GLOBALB.BUN`, `GLOBAL\INGAMEB.BUN` |
| [Sound](#sound) | effects, engines, music, speech, through WAV | `SOUND\` |
| [Movies](#movies) | intro and menu movies, from any video, with a player | `MOVIES\` |
| [Experimental](#experimental) | a car of NFS Underground in place of an HP2 car; car stats | as Cars, Textures, Car physics, Texts |
| [All files](#all-files) | nothing: shows every file and whether the game uses it | everything under `data\` |

## Cars

- **View the car**: the car put together as the game draws it, in a 3D viewer. It shows the body at each level of
  detail, the mirrors and plates, and the tyres and brakes where the car's wheels are, with any of its skins.
- **Export OBJ** writes an OBJ and MTL:
  - every part as its own object: the four levels of detail of the body, tyres, brakes, mirrors, wipers, plate, wheel
    blur and scuffs;
  - the whole car put together, for looking at;
  - the pictures, if you want them: mesh only, the default skin, some skins, or all of them.
- **Import OBJ** takes any shape: any number of polygons and any topology, made in Blender or anything else.
  - Before anything is written, the viewer shows the car as it is now and as it will be.
  - Parts that the OBJ does not have stay as they were, byte for byte.
  - The damage dents keep working on a new body.
- Skins, headlights and brake lights (off, on and broken), windows, tyres and the underside keep working as the game's
  own slots.

## Textures

- Every picture of a file goes out as PNG and comes back by name. This covers the cars' skins and lights, the shared
  car pictures (windows, tyres, plates, brakes), the menus, the HUD and the tracks.
- A picture of the texture's size keeps its format (4 or 8 bits with a palette, or 32 bits).
- A picture of another size gives the texture that size. A 16-colour texture can become 256-colour on the way, so a
  bigger picture keeps its detail.
- One texture may take as much of the game's texture memory as the largest on the disc: 1024 x 1024 at 16 colours,
  1024 x 512 at 256. A bigger one is refused, and 256 colours that would not fit stay 16.
- Textures that show the same pixels under other names keep their colours. These are an HP version's or a dash in
  other colours.
- A PNG drawn with the palette's own colours stays exact. Any other picture gets a new palette and new mip levels.

## Tracks

- **View the track**: the whole track with every object in place (about half a million triangles), drawn the way the
  game draws it: solid, cut-out and see-through pictures, and the objects of the chosen direction (forward or backward).
  Fly over it with W A S D and Q E; Shift goes faster.
- **Take the car's place**: the eye of a driver on the starting grid, at any of its eight places, in either direction.
- **Drive** on the track's own collision surface: up kerbs and slopes, under bridges, stopped by walls and rails.
- **Export OBJ** writes the track's models, with the whole track put together in a second file for looking at.
- **Import OBJ** changes models of the track: the road, the ground, buildings, trees and signs. A model that is placed
  several times changes everywhere it stands. The game's visibility culling grows to take in the new shapes.

## Models

The models that are neither a car nor a track:

- the dashboards of the Barchetta, the F50 and the Spider in the cockpit view (panel, wheel, needles);
- the menus': the car's platform, the car cover, the track select's small tracks;
- the race's: the spike belt, the smoke bomb, the rocket, the roadblock barrel, the shaking bushes, the ticket book, the
  markers, the drivers and the cops at three levels of detail;
- the cut-scenes' drivers and cops.

**View** them, **export** them as OBJ with their pictures, and **import** an OBJ back: any shape. You see the model now
and after before anything is written.

## Car physics

Every number of each of the 64 car types, in groups:

- wheels: position, radius and width;
- tyres: slip angle and grip;
- body: mass, size and centre of gravity;
- suspension;
- gearbox: final drive, torque split, number of gears, the ratios;
- engine: idle, red line, maximum RPM, the torque curve;
- aerodynamics: drag and downforce;
- control: steering, brakes, brake balance, top speed limiter.

Double click a value to change it. JSON export and import change many cars at once. The inertia follows a new mass or
size by itself.

## Texts

- All 2437 texts of the game in English, French, German, Italian, Spanish and Swedish. Double click a line to change it;
  any length.
- Export and import as a table (tab-separated UTF-8) for Excel, LibreOffice or a translation tool.
- **With the port's texts** shows the Windows port's own translations and additions next to the game's.

## Menu screens

- Every screen of the menus and the HUD, drawn as the game draws it, with the game's own fonts and pictures.
- Drag an object on the preview, or change its fields: position, scale, layer, visible or not, colour and transparency,
  text, and picture.
- **As the port draws them** shows the menus with the Windows port's own pages and rows (Graphics, Controls, Profiles and
  others), marked as the port's. Reading them needs a port build that writes its menu dump after its own changes (newer
  than 0.14).

## Sound

- **Effects**: 26 banks, among them the menu, the race, the regions and an engine bank for each car (12 engine loops and
  the horn).
- **Music**: the 23 tunes of the EA TRAX jukebox. A tune can be any length.
- **Speech**: the commentary and the police radio, in each language, every bank by its name (`19AddPrime`, `CarDa`...).
  A clip can be any length: the game plays each clip to where the next one starts, so the speech file is laid out
  anew round the clips you put in, with no pause after a shorter clip and nothing cut from a longer one. Space left
  behind by earlier versions of the tool (0.14 and before moved a bank to the end of the file) is given back.
- **BAN & DAT Rewrite**: one button for a whole voice-over. Pick a folder of speech WAVs (or a tree with
  `Speech\<LANGUAGE>`): the speech as it came from the disc, with those WAVs in, every clip at its own length, is
  written into the game. Whatever earlier imports left in the files goes; a clip not in the folder is the disc's.
- Play any sound, export it as WAV, or replace it with your own WAV (any rate, 8 to 32 bits). It is converted to the
  game's format, rate and channels by itself. A replaced effect loops if the original did.
- **Many at once**: export a bank, the music or a language's speech, change the WAVs you want, and import the folder:
  every WAV goes back into the sound of its name.
- **All the game's sound** as one tree of folders (`Effects\<BANK>`, `Music`, `Speech\<LANGUAGE>`). Export it whole, and
  import such a tree, or any part of it, in one go: a sound mod for many banks goes in in one step.
- WAVs left as they were exported are passed over, since every new encoding loses a little. The import names the files
  that match no sound and says how much each effects bank grows.

## Movies

- **Play** a movie with its sound.
- **Export** it as an ordinary AVI with its sound.
- **Replace** it with any video (MP4, AVI, MKV, MOV...). It is scaled to the movie's size, set to 30 frames a second,
  and encoded in the game's own movie format, with the sound from a WAV. The length is free and the quality is
  adjustable.

## Experimental

These are new. The Underground car import has been checked in the game, and so has a disc image in PCSX2.

- **Car from Underground 1**: a car of the PC game Need for Speed: Underground in place of an HP2 car (the game has
  exactly 64 car types and no free one).
  - **Body**: the car's stock body at each level of detail.
  - **Wheels and brakes**: its stock wheels (rim and tyre) and its stock brakes.
  - **Lamps**: they switch on, off and break as HP2's do.
  - **Glass**: the windows are glass, with the windscreen and the rear window in their own slots.
  - **Skins**: Underground's first nine gloss paints, with its badges and details.
  - **Wheel positions**: the wheels go where Underground puts them, and the physics follows.

  You see the result in the viewer before it is written. Collision, engine sound and damage stay those of the HP2 car
  it replaces.
- **Car stats**: what the car select screen shows (full and short name, 0-60, top speed, power) in all six languages,
  and the main physics: mass, power, grip, top speed, brakes, steering, gears, final drive and drag.
- **Disc image**: a disc image of the game with every change you made, for PCSX2, OPL or a disc for a PS2.
  - It needs the original image the game was installed from, which is only read. The game's archive is made again from
    the installed game.
  - Everything else is the original's, byte for byte: the boot files, the PS2 logo and the system modules. Both of the
    disc's file systems follow the archive's new size.
  - The image is read back and checked when it is made.
  - The port's own translations, menu pages and settings stay in the port. Pictures over 1024 a side, which a PS2
    cannot draw, are named before the image is made.
  - Textures given a new size are not recommended on a disc yet: they are named too.

## All files

Every file of the installed game with what it is and its status:

- **used** (the game names it, or it was read in play);
- **unused**;
- **not seen**;
- **empty**;
- **the port's own**;
- **a backup**.

## Limits

- New textures cannot be added. A bigger texture makes its file bigger, and the game keeps the PS2's memory, so
  keep car textures to what you need.
- A car part holds at most 32,767 strip vertices (a body of about 20,000 triangles).
- The game keeps the PS2's memory. A race leaves about 5 MB free for all the cars together, and a track takes up to
  about 16 MB with its textures.
- Collision does not follow a new shape:
  - Cars keep their collision volumes. Wheel positions are in Car physics.
  - Tracks keep their collision, the AI's routes and the cameras, so cars drive on the old ground.
- The sound chip has 2 MB for every sound bank loaded at once, and a race leaves about 270 KB of it free, so keep new
  effects short.
