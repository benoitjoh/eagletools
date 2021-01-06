#!/usr/bin/env python
"""Support for writing characters and graphics to Gerber files
--------------------------------------------------------------------

This program is licensed under the GNU General Public License (GPL)
Version 3.  See http://www.fsf.org for details of the license.

Rugged Circuits LLC
http://ruggedcircuits.com/gerbmerge
"""
import sys

import math

import strokes

# Define percentage of cell height and width to determine
# intercharacter spacing
SPACING_X = 1.20
SPACING_Y = 1.20

# Arrow dimensions
BAR_LENGTH = 1500         # Length of dimension line
ARROW_WIDTH = 750         # How broad the arrow is
ARROW_LENGTH = 750        # How far back from dimension line it is
ARROW_STEM_LENGTH = 1250  # How long the arrow stem extends from center point

#################################################################

# Arrow directions
FACING_LEFT = 0   # 0 degrees
FACING_DOWN = 1   # 90 degrees counterclockwise
FACING_RIGHT = 2  # 180 degrees
FACING_UP = 3     # 270 degrees

SPACING_DX = 10 * int(round(strokes.MaxWidth * SPACING_X))
SPACING_DY = 10 * int(round(strokes.MaxHeight * SPACING_Y))

RotatedGlyphs = {}

# Default arrow glyph is at 0 degrees rotation, facing left
ArrowGlyph = [
    [(0, -BAR_LENGTH / 2), (0, BAR_LENGTH / 2)],
    [(ARROW_LENGTH, ARROW_WIDTH / 2), (0, 0), (ARROW_LENGTH, -ARROW_WIDTH / 2)],
    [(0, 0), (ARROW_STEM_LENGTH, 0)]
]


def rotateGlyph(glyph, degrees, glyphName):
    """Rotate a glyph counterclockwise by given number of degrees. The glyph
    is a list of lists, where each sub-list is a connected path."""
    try:
        return RotatedGlyphs["{:.1f}_{:s}".format(degrees, glyphName)]
    except KeyError:
        pass  # Not cached yet

    rad = degrees / 180.0 * math.pi
    cosx = math.cos(rad)
    sinx = math.sin(rad)

    newglyph = []
    for path in glyph:
        newpath = []
        for X, Y in path:
            x = int(round(X * cosx - Y * sinx))
            y = int(round(X * sinx + Y * cosx))
            newpath.append((x, y))
        newglyph.append(newpath)

    RotatedGlyphs["{:.1f}_{:s}".format(degrees, glyphName)] = newglyph
    return newglyph


def writeFlash(fid, X, Y, D):
    fid.write("X{:07d}Y{:07d}D{:02d}*\n".format(int(X), int(Y), int(D)))


def drawPolyline(fid, L, offX, offY, scale=1):
    for ix in range(len(L)):
        X, Y = L[ix]
        X *= scale
        Y *= scale
        if ix == 0:
            writeFlash(fid, X + offX, Y + offY, 2)
        else:
            writeFlash(fid, X + offX, Y + offY, 1)


def writeGlyph(fid, glyph, X, Y, degrees, glyphName=None, size=10):
    if not glyphName:
        glyphName = str(glyph)

    for path in rotateGlyph(glyph, degrees, glyphName):
        drawPolyline(fid, path, X, Y, size)


def writeChar(fid, c, X, Y, degrees, size=10):
    if c == ' ':
        return

    try:
        glyph = strokes.StrokeMap[c]
    except:
        raise RuntimeError("No glyph for character {:X}".format(ord(c)))

    writeGlyph(fid, glyph, X, Y, degrees, c, size)


# this assumes the aperture has already been set.
# x and y are in gerber units (hundredths of mils?)
# size is in mils
def writeString(fid, s, X, Y, degrees, size=60.0):
    posX = X
    posY = Y
    rad = degrees / 180.0 * math.pi
    # convert mils to whatever goofy unit they use
    size = size * 1 / 6.0
    # divide by 10 to get offset of size right
    dX = int(round(math.cos(rad) * SPACING_DX * (size / 10.0)))
    dY = int(round(math.sin(rad) * SPACING_DX * (size / 10.0)))

    for char in s:
        writeChar(fid, char, posX, posY, degrees, size)
        posX += dX
        posY += dY


def drawLine(fid, X1, Y1, X2, Y2):
    drawPolyline(fid, [(X1, Y1), (X2, Y2)], 0, 0)


def boundingBox(s, X1, Y1):
    "Return (X1,Y1),(X2,Y2) for given string"
    if not s:
        return (X1, Y1), (X1, Y1)

    X2 = X1 + (len(s) - 1) * SPACING_DX + 10 * strokes.MaxWidth
    Y2 = Y1 + 10 * strokes.MaxHeight  # Not including descenders
    return (X1, Y1), (X2, Y2)


def drawDimensionArrow(fid, X, Y, facing):
    writeGlyph(fid, ArrowGlyph, X, Y, facing * 90, "Arrow")


def drawDrillHit(fid, X, Y, toolNum):
    writeGlyph(fid, strokes.DrillStrokeList[toolNum], X, Y, 0, "Drill{:02d}".format(toolNum))


if __name__ == "__main__":
    import string
    s = string.digits + string.ascii_letters + string.punctuation
    #s = "The quick brown fox jumped over the lazy dog!"
    size = float(sys.argv[1]) if len(sys.argv) > 1 else 10
    fid = open("test.ger", 'wt')
    fid.write("""G75*
  G70*
  %OFA0B0*%
  %FSAX24Y24*%
  %IPPOS*%
  %LPD*%
  %AMOC8*
  5,1,8,0,0,1.08239X$1,22.5*
  *%
  %ADD10C,0.0100*%
  D10*
  """)

    writeString(fid, s, 0, 0, 0, 10)
    writeString(fid, s, 0, 20000, 0, size)
    drawDimensionArrow(fid, 0, 5000, FACING_LEFT)
    drawDimensionArrow(fid, 5000, 5000, FACING_RIGHT)
    drawDimensionArrow(fid, 0, 10000, FACING_UP)
    drawDimensionArrow(fid, 5000, 10000, FACING_DOWN)

    for diam in range(0, strokes.MaxNumDrillTools):
        writeGlyph(fid, strokes.DrillStrokeList[diam], diam * 1250, 15000, 0, "{:02d}".format(diam))

    fid.write("M02*\n")
    fid.close()
