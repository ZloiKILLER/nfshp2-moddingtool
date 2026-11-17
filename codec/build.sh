#!/bin/sh
# Builds codec/hp2codec.dll (the movie codec and the SPU ADPCM, for hp2movie.py and hp2sound.py) with LLVM's clang.
set -e
cd "$(dirname "$0")"
CLANG="${CLANG:-C:/Program Files/LLVM/bin/clang.exe}"
"$CLANG" -O2 -Wall -shared -o hp2codec.dll hp2codec.c
rm -f hp2codec.lib hp2codec.exp
echo "built $(pwd)/hp2codec.dll"
