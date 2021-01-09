#!/usr/bin/env python
"""
Parse the GerbMerge configuration file.

--------------------------------------------------------------------

This program is licensed under the GNU General Public License (GPL)
Version 3.  See http://www.fsf.org for details of the license.

Rugged Circuits LLC
http://ruggedcircuits.com/gerbmerge
"""

import sys
import configparser
import re
import os

import jobs
import aptable
import excellon

# Configuration dictionary. Specify floats as strings. Ints can be specified
# as ints or strings.
Config = {
    'xspacing': '0.125',              # Spacing in horizontal direction
    'yspacing': '0.125',              # Spacing in vertical direction
    'panelwidth': '12.6',             # X-Dimension maximum panel size (Olimex)
    'panelheight': '7.8',             # Y-Dimension maximum panel size (Olimex)
    'cropmarklayers': None,           # e.g., *toplayer,*bottomlayer
    'cropmarkwidth': '0.01',          # Width (inches) of crop lines
    'cutlinelayers': None,            # as for cropmarklayers
    'cutlinewidth': '0.01',           # Width (inches) of cut lines
    'minimumfeaturesize': 0,          # Minimum dimension for selected layers
    'toollist': None,                 # Name of file containing default tool list
    'drillclustertolerance': '.002',  # Tolerance for clustering drill sizes
    'allowmissinglayers': 0,          # Set to 1 to allow multiple jobs to have non-matching layers
    'fabricationdrawingfile': None,   # Name of file to which to write fabrication drawing, or None
    'fabricationdrawingtext': None,   # Name of file containing text to write to fab drawing
    'excellondecimals': 4,            # Number of digits after the decimal point in input Excellon files
    'excellonleadingzeros': 0,        # Generate leading zeros in merged Excellon output file
    'outlinelayerfile': None,         # Name of file to which to write simple box outline, or None
    'outlinelayers': None,            # e.g., *toplayer, *bottomlayer
    'scoringfile': None,              # Name of file to which to write scoring data, or None
    'leftmargin': 0,                  # Inches of extra room to leave on left side of panel for tooling
    'topmargin': 0,                   # Inches of extra room to leave on top side of panel for tooling
    'rightmargin': 0,                 # Inches of extra room to leave on right side of panel for tooling
    'bottommargin': 0,                # Inches of extra room to leave on bottom side of panel for tooling
    'fiducialpoints': None,           # List of X,Y co-ordinates at which to draw fiducials
    'fiducialcopperdiameter': 0.08,   # Diameter of copper part of fiducial
    'fiducialmaskdiameter': 0.32,     # Diameter of fiducial soldermask opening
}

# these are for special text, printed on every layer
text = None
text_size = None  # mils, must be enough less than Yspacing that there isn't overlap
                     # if not specified, deduce based on Yspacing and other variables
                     # (cutline width, etc.)
text_stroke = None  # mils, deduce based on text_size
text_rotation = None  # degrees
text_x = None  # if not specified, put it in the first cutline area
text_y = None  # if not specified, put it in the first cutline area

min_text_stroke = 6  # mils, this is the minimum at SeeedStudio
min_text_size = 32  # mils, this is the minimum at SeeedStudio

# This dictionary is indexed by lowercase layer name and has as values a file
# name to use for the output.
MergeOutputFiles = {
    'boardoutline': 'merged.boardoutline.ger',
    'drills': 'merged.drills.xln',
    'placement': 'merged.placement.xml',
    'toollist': 'merged.toollist.drl'
}

# The global aperture table, indexed by aperture code (e.g., 'D10')
GAT = {}

# The global aperture macro table, indexed by macro name (e.g., 'M3', 'M4R' for rotated macros)
GAMT = {}

# The list of all jobs loaded, indexed by job name (e.g., 'PowerBoard')
Jobs = {}

# The set of all Gerber layer names encountered in all jobs. Doesn't
# include drills.
LayerList = {'boardoutline': 1}

# The tool list as read in from the DefaultToolList file in the configuration
# file. This is a dictionary indexed by tool name (e.g., 'T03') and
# a floating point number as the value, the drill diameter in inches.
DefaultToolList = {}

# The GlobalToolMap dictionary maps tool name to diameter in inches. It
# is initially empty and is constructed after all files are read in. It
# only contains actual tools used in jobs.
GlobalToolMap = {}

# The GlobalToolRMap dictionary is a reverse dictionary of ToolMap, i.e., it maps
# diameter to tool name.
GlobalToolRMap = {}

##############################################################################

# This configuration option determines whether trimGerber() is called
TrimGerber = True

# This configuration option determines whether trimExcellon() is called
TrimExcellon = True

# This configuration option determines the minimum size of feature dimensions for
# each layer. It is a dictionary indexed by layer name (e.g. '*topsilkscreen') and
# has a floating point number as the value (in inches).
MinimumFeatureDimension = {}

# This configuration option is a positive integer that determines the maximum
# amout of time to allow for random placements (seconds). A SearchTimeout of 0
# indicates that no timeout should occur and random placements will occur
# forever until a KeyboardInterrupt is raised.
SearchTimeout = 0


# Construct the reverse-GAT/GAMT translation table, keyed by aperture/aperture macro
# hash string. The value is the aperture code (e.g., 'D10') or macro name (e.g., 'M5').
def buildRevDict(D):
    RevD = {}
    for key, val in D.items():
        RevD[val.hash()] = key
    return RevD


def parseStringList(L):
    """Parse something like '*toplayer, *bottomlayer' into a list of names
       without quotes, spaces, etc."""

    # This pattern matches quotes at the beginning and end...quotes must match
    quotepat = re.compile(r'^([' "'" '"' r']?)([^\1]*)\1$')
    delimitpat = re.compile(r"[ \t]*[,;][ \t]*")

    match = quotepat.match(L)
    if match:
        L = match.group(2)

    return delimitpat.split(L)


# This function parses the job configuration file and does
# everything needed to:
#
#   * parse global options and store them in the Config dictionary
#     as natural types (i.e., ints, floats, lists)
#
#   * Read Gerber/Excellon data and populate the Jobs dictionary
#
#   * Read Gerber/Excellon data and populate the global aperture
#     table, GAT, and the global aperture macro table, GAMT
#
#   * read the tool list file and populate the DefaultToolList dictionary
def parseConfigFile(configFilePath, Config=Config, Jobs=Jobs):
    global DefaultToolList
    
    if not os.path.exists(configFilePath):
        raise RuntimeError('[ERROR] not found: configurationfile "%s"' % configFilePath)
    CP = configparser.ConfigParser()
    CP.read(configFilePath)

    # Store the base directory that all files are referenced from (the one the config file is in).
    configDir = os.path.dirname(configFilePath)

    # First parse global options and merge them into the global Config options object.
    if CP.has_section('Options'):
        for opt in CP.options('Options'):
            # Is it one we expect
            if opt in Config:
                # Yup...override it
                Config[opt] = CP.get('Options', opt)

            elif opt in CP.defaults():
                pass   # Ignore DEFAULTS section keys

            elif opt in ('fabricationdrawing', 'outlinelayer'):
                print('*' * 73)
                print('\nThe FabricationDrawing and OutlineLayer configuration options have been')
                print('renamed as of GerbMerge version 1.0. Please consult the documentation for')
                print('a description of the new options, then modify your configuration file.\n')
                print('*' * 73)
                sys.exit(1)
            else:
                raise RuntimeError("Unknown option '{:s}' in [Options] section of configuration file".format(opt))
    else:
        raise RuntimeError("Missing [Options] section in configuration file")

    # Ensure we got a tool list
    if 'toollist' not in Config:
        raise RuntimeError("INTERNAL ERROR: Missing tool list assignment in [Options] section")

    # Make integers integers, floats floats
    for key, val in Config.items():
        try:
            val = int(val)
            Config[key] = val
        except:
            try:
                val = float(val)
                Config[key] = val
            except:
                pass

    # Process lists of strings
    if Config['cutlinelayers']:
        Config['cutlinelayers'] = parseStringList(Config['cutlinelayers'])
    if Config['cropmarklayers']:
        Config['cropmarklayers'] = parseStringList(Config['cropmarklayers'])
    if Config['outlinelayers']:
        Config['outlinelayers'] = parseStringList(Config['outlinelayers'])

    # Process list of minimum feature dimensions
    if Config['minimumfeaturesize']:
        temp = Config['minimumfeaturesize'].split(",")
        try:
            for index in range(0, len(temp), 2):
                MinimumFeatureDimension[temp[index]] = float(temp[index + 1])
        except:
            raise RuntimeError("Illegal configuration string:" + Config['minimumfeaturesize'])

    # Process MergeOutputFiles section to set output file names
    if CP.has_section('MergeOutputFiles'):
        for opt in CP.options('MergeOutputFiles'):
            # Each option is a layer name and the output file for this name
            if opt[0] == '*' or opt in ('boardoutline', 'drills', 'placement', 'toollist'):
                MergeOutputFiles[opt] = CP.get('MergeOutputFiles', opt)

    # Now, we go through all jobs and collect Gerber layers
    # so we can construct the Global Aperture Table.
    apfiles = []

    for jobname in CP.sections():
        if jobname == 'Options' or jobname == 'MergeOutputFiles' or jobname == 'GerbMergeGUI':
            continue

        # Ensure all jobs have a board outline
        if not CP.has_option(jobname, 'boardoutline'):
            raise RuntimeError("Job '{:s}' does not have a board outline specified".format(jobname))

        if not CP.has_option(jobname, 'drills'):
            raise RuntimeError("Job '{:s}' does not have a drills layer specified".format(jobname))

        for layername in CP.options(jobname):
            if layername[0] == '*' or layername == 'boardoutline':
                fname = CP.get(jobname, layername)
                apfiles.append(fname)

                if layername[0] == '*':
                    LayerList[layername] = 1

    # Now construct global aperture tables, GAT and GAMT. This step actually
    # reads in the jobs for aperture data but doesn't store Gerber
    # data yet.
    aptable.constructApertureTable([os.path.join(configDir, x) for x in apfiles], GAT, GAMT)
    del apfiles

    # Parse the tool list
    if Config['toollist']:
        DefaultToolList = excellon.parseToolList(Config['toollist'])

    # Now get jobs. Each job implies layer names, and we
    # expect consistency in layer names from one job to the
    # next. Two reserved layer names, however, are
    # BoardOutline and Drills.

    Jobs.clear()

    do_abort = False
    errstr = 'ERROR'
    if Config['allowmissinglayers']:
        errstr = 'WARNING'

    for jobname in CP.sections():
        if jobname == 'Options' or jobname == 'MergeOutputFiles' or jobname == 'GerbMergeGUI':
            continue

        print('Reading data from', jobname, '...')

        J = jobs.Job(jobname)

        # Parse the job settings, like tool list, first, since we are not
        # guaranteed to have ConfigParser return the layers in the same order that
        # the user wrote them, and we may get Gerber files before we get a tool
        # list! Same thing goes for ExcellonDecimals. We need to know what this is
        # before parsing any Excellon files.
        for layername in CP.options(jobname):
            fname = CP.get(jobname, layername)

            if layername == 'toollist':
                fname = os.path.join(configDir, CP.get(jobname, layername))
                J.ToolList = excellon.parseToolList(fname)
            elif layername == 'excellondecimals':
                try:
                    J.ExcellonDecimals = int(fname)
                except:
                    raise RuntimeError("Excellon decimals '{:s}' in config file is not a valid integer".format(fname))
            elif layername == 'repeat':
                try:
                    J.Repeat = int(fname)
                except:
                    raise RuntimeError("Repeat count '{:s}' in config file is not a valid integer".format(fname))

        for layername in CP.options(jobname):
            fname = os.path.join(configDir, CP.get(jobname, layername))

            if layername == 'boardoutline':
                J.parseGerber(fname, layername, updateExtents=1)
            elif layername[0] == '*':
                J.parseGerber(fname, layername, updateExtents=0)
            elif layername == 'drills':
                J.parseExcellon(fname)

        # Emit warnings if some layers are missing
        LL = LayerList.copy()
        for layername in J.apxlat.keys():
            assert layername in LL
            del LL[layername]

        if LL:
            if errstr == 'ERROR':
                do_abort = True

            print("{:s}: Job {:s} is missing the following layers:".format(errstr, jobname))
            for layername in LL.keys():
                print("  {:s}".format(layername))

        # Store the job in the global Jobs dictionary, keyed by job name
        Jobs[jobname] = J

    if do_abort:
        raise RuntimeError("Exiting since jobs are missing layers. Set AllowMissingLayers=1\nto override.")

if __name__ == "__main__":
    CP = parseConfigFile(sys.argv[1])
    print(Config)
    sys.exit(0)
