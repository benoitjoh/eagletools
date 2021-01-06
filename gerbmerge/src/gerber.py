import config
import util
import aptable

def writeHeader22degrees(fid):
    fid.write("""G75*
G70*
%OFA0B0*%
%FSLAX25Y25*%
%IPPOS*%
%LPD*%
%AMOC8*
5,1,8,0,0,1.08239X$1,22.5*
%
""")


def writeHeader0degrees(fid):
    fid.write("""G75*
G70*
%OFA0B0*%
%FSLAX25Y25*%
%IPPOS*%
%LPD*%
%AMOC8*
5,1,8,0,0,1.08239X$1,0.0*
%
""")


def writeCurrentAperture(fid, aperture):
    fid.write("D{:d}*\n".format(aperture))

def writeApertureMacros(fid, usedDict):
    keys = list(config.GAMT.keys())
    keys.sort()
    for key in keys:
        if key in usedDict:
            config.GAMT[key].writeDef(fid)


def writeApertures(fid, usedDict):
    keys = list(config.GAT.keys())
    keys.sort()
    for key in keys:
        if key in usedDict:
            config.GAT[key].writeDef(fid)


def writeFooter(fid):
    fid.write("M02*\n")


def writeFiducials(fid, drawcode, OriginX, OriginY, MaxXExtent, MaxYExtent):
    """Place fiducials at arbitrary points. The FiducialPoints list in the config specifies
    sets of X,Y co-ordinates. Positive values of X/Y represent offsets from the lower left
    of the panel. Negative values of X/Y represent offsets from the top right. So:
           FiducialPoints = 0.125,0.125,-0.125,-0.125
    means to put a fiducial 0.125,0.125 from the lower left and 0.125,0.125 from the top right"""
    fid.write("{:s}*\n".format(drawcode))    # Choose drawing aperture

    fList = config.Config['fiducialpoints'].split(',')
    for i in range(0, len(fList), 2):
        x, y = float(fList[i]), float(fList[i + 1])
        if x >= 0:
            x += OriginX
        else:
            x = MaxXExtent + x
        if y >= 0:
            y += OriginX
        else:
            y = MaxYExtent + y
        fid.write("X{:07d}Y{:07d}D03*\n".format(util.in2gerb(x), util.in2gerb(y)))


def writeOutline(fid, OriginX, OriginY, MaxXExtent, MaxYExtent):
    # Write width-1 aperture to file
    AP = aptable.Aperture(aptable.Circle, 'D10', 0.001)
    AP.writeDef(fid)

    # Choose drawing aperture D10
    writeCurrentAperture(fid, 10)

    # Draw the rectangle starting at the bottom left and going clockwise.
    fid.write("X{:07d}Y{:07d}D02*\n".format(util.in2gerb(OriginX), util.in2gerb(OriginY)))
    fid.write("Y{:07d}D01*\n".format(util.in2gerb(MaxYExtent)))
    fid.write("X{:07d}D01*\n".format(util.in2gerb(MaxXExtent)))
    fid.write("Y{:07d}D01*\n".format(util.in2gerb(OriginY)))
    fid.write("X{:07d}D01*\n".format(util.in2gerb(OriginX)))


def writeCropMarks(fid, drawing_code, OriginX, OriginY, MaxXExtent, MaxYExtent):
    """Add corner crop marks on the given layer"""

    # Draw 125mil lines at each corner, with line edge right up against
    # panel border. This means the center of the line is D/2 offset
    # from the panel border, where D is the drawing line diameter.
    fid.write("{:s}*\n".format(drawing_code))    # Choose drawing aperture

    offset = config.GAT[drawing_code].dimx / 2.0

    # Lower-left
    x = OriginX + offset
    y = OriginY + offset
    fid.write("X{:07d}Y{:07d}D02*\n".format(util.in2gerb(x + 0.125), util.in2gerb(y + 0.000)))
    fid.write("X{:07d}D01*\n".format(util.in2gerb(x + 0.000)))
    fid.write("Y{:07d}D01*\n".format(util.in2gerb(y + 0.125)))

    # Lower-right
    x = MaxXExtent - offset
    y = OriginY + offset
    fid.write("X{:07d}Y{:07d}D02*\n".format(util.in2gerb(x + 0.000), util.in2gerb(y + 0.125)))
    fid.write("Y{:07d}D01*\n".format(util.in2gerb(y + 0.000)))
    fid.write("X{:07d}D01*\n".format(util.in2gerb(x - 0.125)))

    # Upper-right
    x = MaxXExtent - offset
    y = MaxYExtent - offset
    fid.write("X{:07d}Y{:07d}D02*\n".format(util.in2gerb(x - 0.125), util.in2gerb(y + 0.000)))
    fid.write("X{:07d}D01*\n".format(util.in2gerb(x + 0.000)))
    fid.write("Y{:07d}D01*\n".format(util.in2gerb(y - 0.125)))

    # Upper-left
    x = OriginX + offset
    y = MaxYExtent - offset
    fid.write("X{:07d}Y{:07d}D02*\n".format(util.in2gerb(x + 0.000), util.in2gerb(y - 0.125)))
    fid.write("Y{:07d}D01*\n".format(util.in2gerb(y + 0.000)))
    fid.write("X{:07d}D01*\n".format(util.in2gerb(x + 0.125)))
