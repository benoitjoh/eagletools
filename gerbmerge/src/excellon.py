import re
import string


def writeheader(fid, tools, units='mm'):
    """This file writes the header for an Excellon drill file. Specifically it specifies the name of each drill and its size and specifies the units both the drills and the placement values. Note that tools should be a list of tuples with the tool name and then its size."""
    # Print start of header
    fid.write("%\nM48\n")
    
    # Specify units
    if units == 'mm':
        fid.write("M71\n")
    elif units == 'in':
        fid.write("M72\n")
    else:
        raise RuntimeError("Invalid units {:s} specified in excellon.writeheader()".format(units))

    # Write out all tool dimensions
    for tool in tools:
        writetool(fid, tool[0], tool[1], units)

    # End the header
    fid.write("%\n")


def writefooter(fid):
    fid.write("M30\n")


def writetool(fid, tool, size, units='mm'):
    if units == 'mm':
        numformat = "{:4.2f}"
    elif units == 'in':
        numformat = "{:2.4f}"
    else:
        raise RuntimeError("Invalid units {:s} specified in excellon.writetool()".format(units))
    fid.write(("{:s}C" + numformat + "\n").format(tool, size))


def writetoolname(fid, tool):
    fid.write("{:s}\n".format(tool))


def parseToolList(fname):
    """Parse an Excellon tool list file of the form:
    T01 0.035in
    T02 0.042in
    """
    TL = {}

    try:
        fid = open(fname, 'rt')
    except Exception as detail:
        raise RuntimeError("Unable to open tool list file '{:s}':\n  {:s}".format(fname, str(detail)))

    units_pat = re.compile(r"\s*(T\d+)\s+([0-9.]+)\s*(in|mm|mil)\s*")
    for line in fid:
        line = line.lstrip()
        if line[0] == '#' or line[0] == ';':
            continue

        # Parse out tool name and size (with units) from lines
        match = units_pat.match(line)
        tool, size, units = match.groups()

        # Get the size as a float
        try:
            size = float(size)
        except:
            raise RuntimeError("Tool size in file '{:s}' is not a valid floating-point number:\n  {:s}".format(fname, line))

        # Convert any non-inches unit to inches
        if units == 'mil':
            size = size * 0.001  # Convert mil to inches
        elif units == 'mm':
            size = size / 25.4   # Convert mm to inches

        # Canonicalize tool so that T1 becomes T01
        tool = "T{:02d}".format(tool[1:])

        # If this tool already exists, there's a problem with the file
        if tool in TL:
            raise RuntimeError("Tool '{:s}' defined more than once in tool list file '{:s}'".format(tool, fname))

        TL[tool] = size
    fid.close()

    return TL


def write_excellon(fid, diameter, Xoff, Yoff, leadingZeros, xdiam, xcommands, minx, miny):
    "Write out the data such that the lower-left corner of this job is at the given (X,Y) position, in inches"

    # First convert given inches to 2.4 co-ordinates. Note that Gerber is 2.5 (as of GerbMerge 1.2)
    # and our internal Excellon representation is 2.4 as of GerbMerge
    # version 0.91. We use X,Y to calculate DX,DY in 2.4 units (i.e., with a
    # resolution of 0.0001".
    X = int(round(Xoff / 0.00001))  # First work in 2.5 format to match Gerber
    Y = int(round(Yoff / 0.00001))

    # Now calculate displacement for each position so that we end up at specified origin
    DX = X - minx
    DY = Y - miny

    # Now round down to 2.4 format
    DX = int(round(DX / 10.0))
    DY = int(round(DY / 10.0))

    ltools = []
    for tool, diam in xdiam.items():
        if diam == diameter:
            ltools.append(tool)

    if leadingZeros:
        fmtstr = "X{:06d}Y{:06d}\n"
    else:
        fmtstr = "X{:d}Y{:d}\n"

    # Boogie
    for ltool in ltools:
        if ltool in xcommands:
            for cmd in xcommands[ltool]:
                x, y = cmd
                fid.write(fmtstr.format(x + DX, y + DY))
