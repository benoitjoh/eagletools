#!/usr/bin/env python
"""
Merge several RS274X (Gerber) files generated by Eagle into a single
job.

This program expects that each separate job has at least three files:
  - a board outline (RS274X)
  - data layers (copper, silkscreen, etc. in RS274X format)
  - an Excellon drill file

Furthermore, it is expected that each job was generated by Eagle
using the GERBER_RS274X plotter, except for the drill file which
was generated by the EXCELLON plotter.

This program places all jobs into a single job.

--------------------------------------------------------------------

This program is licensed under the GNU General Public License (GPL)
Version 3.  See http://www.fsf.org for details of the license.

Rugged Circuits LLC
http://ruggedcircuits.com/gerbmerge
"""

# Include standard modules
import sys
import argparse
from math import factorial
import time
import queue
import multiprocessing

# Include gerbmerge modules
import aptable
import jobs
import config
import fabdrawing
import makestroke
import strokes
import tiling
import tilesearch
import placement
import schwartz
import util
import scoring
import drillcluster
import gerber
import excellon

VERSION_MAJOR = 2
VERSION_MINOR = 0

RANDOM_SEARCH = 1
EXHAUSTIVE_SEARCH = 2
config.AutoSearchType = RANDOM_SEARCH
config.RandomSearchExhaustiveJobs = 2

# This is a handle to a GUI front end, if any, else None for command-line usage
GUI = None


def disclaimer(ack=False):
    print("""
  ****************************************************
  *           R E A D    C A R E F U L L Y           *
  *                                                  *
  * This program comes with no warranty. You use     *
  * this program at your own risk. Do not submit     *
  * board files for manufacture until you have       *
  * thoroughly inspected the output of this program  *
  * using a previewing program such as:              *
  *                                                  *
  * Windows:                                         *
  *          - GC-Prevue <http://www.graphicode.com> *
  *          - ViewMate  <http://www.pentalogix.com> *
  *          - gerbv <http://gerbv.sourceforge.net>  *
  *                                                  *
  * Linux:                                           *
  *          - gerbv <http://gerbv.sourceforge.net>  *
  *                                                  *
  * By using this program you agree to take full     *
  * responsibility for the correctness of the data   *
  * that is generated by this program.               *
  ****************************************************

  To agree to the above terms, press 'y' then Enter.
  Any other key will exit the program.

  """)
    if ack:
        return
    s = input('> ')
    # Couldn't get `s == "y"` to work, but the following works correctly on python 3.2 on w64
    if len(s) == 1 and s[0] == 'y'[0]:
        return

    print("\nExiting...")
    sys.exit(0)


def tile_jobs(Jobs):
    """Take a list of raw Job objects and find best tiling by calling tile_search"""

    # We must take the raw jobs and construct a list of 4-tuples (Xdim,Ydim,job,rjob).
    # This means we must construct a rotated job for each entry. We first sort all
    # jobs from largest to smallest. This should give us the best tilings first so
    # we can interrupt the tiling process and get a decent layout.
    L = []
    sortJobs = schwartz.schwartz(Jobs, jobs.Job.maxdimension)
    sortJobs.reverse()

    for job in sortJobs:
        Xdim = job.width_in()
        Ydim = job.height_in()
        rjob = jobs.rotateJob(job, 90)  # NOTE: This will only try 90 degree rotations though 180 & 270 are available

        for count in range(job.Repeat):
            L.append((Xdim, Ydim, job, rjob))

    PX, PY = config.Config['panelwidth'], config.Config['panelheight']
    if config.AutoSearchType == RANDOM_SEARCH:
        tile = tile_search_random(L, PX, PY, config.Config['xspacing'], config.Config['yspacing'], config.SearchTimeout, config.RandomSearchExhaustiveJobs)
    else:
        tile = tile_search_exhaustive(L, PX, PY, config.Config['xspacing'], config.Config['yspacing'], config.SearchTimeout)

    if not tile:
        raise RuntimeError('Panel size {:.2f}"x{:.2f}" is too small to hold jobs'.format(PX, PY))

    return tile


def merge(opts, gui=None):
    global GUI
    GUI = gui

    if opts.octagons == 'rotate':
        writeGerberHeader = gerber.writeHeader0degrees
    else:
        writeGerberHeader = gerber.writeHeader22degrees

    if opts.search == 'random':
        config.AutoSearchType = RANDOM_SEARCH
    else:
        config.AutoSearchType = EXHAUSTIVE_SEARCH

    config.RandomSearchExhaustiveJobs = opts.rs_esjobs
    config.SearchTimeout = opts.search_timeout

    if opts.no_trim_gerber:
        config.TrimGerber = False
    if opts.no_trim_excellon:
        config.TrimExcellon = False

    config.text = opts.text
    config.text_size = opts.text_size
    config.text_stroke = opts.text_stroke
    config.text_x = opts.text_x
    config.text_y = opts.text_y

    # Load up the Jobs global dictionary, also filling out GAT, the
    # global aperture table and GAMT, the global aperture macro table.
    updateGUI("Reading job files...")
    config.parseConfigFile(opts.configfile)

    # Force all X and Y coordinates positive by adding absolute value of minimum X and Y
    for name, job in config.Jobs.items():
        min_x, min_y = job.mincoordinates()
        shift_x = shift_y = 0
        if min_x < 0:
            shift_x = abs(min_x)
        if min_y < 0:
            shift_y = abs(min_y)
        if (shift_x > 0) or (shift_y > 0):
            job.fixcoordinates(shift_x, shift_y)

    # Display job properties
    for job in config.Jobs.values():
        print("Job {:s}:".format(job.name))
        if job.Repeat > 1:
            print("({:d} instances)".format(job.Repeat))
        else:
            print()
        print("  Extents: ({:d},{:d})-({:d},{:d})".format(job.minx, job.miny, job.maxx, job.maxy))
        print("  Size: {:f}\" x {:f}\"".format(job.width_in(), job.height_in()))
        print()

    # Trim drill locations and flash data to board extents
    if config.TrimExcellon:
        updateGUI("Trimming Excellon data...")
        print("Trimming Excellon data to board outlines ...")
        for job in config.Jobs.values():
            job.trimExcellon()

    if config.TrimGerber:
        updateGUI("Trimming Gerber data...")
        print("Trimming Gerber data to board outlines ...")
        for job in config.Jobs.values():
            job.trimGerber()

    # We start origin at (0.1", 0.1") just so we don't get numbers close to 0
    # which could trip up Excellon leading-0 elimination.
    OriginX = OriginY = 0.1

    # Read the layout file and construct the nested list of jobs. If there
    # is no layout file, do auto-layout.
    updateGUI("Performing layout...")
    print("Performing layout ...")
    if opts.layoutfile:
        # Construct a canonical placement from the manual layout (relative or absolute)
        Place = placement.Placement()
        Place.addFromFile(opts.layoutfile, OriginX + config.Config['leftmargin'], OriginY + config.Config['bottommargin'])
    else:
        # Do an automatic layout based on our tiling algorithm.
        tile = tile_jobs(config.Jobs.values())

        Place = placement.Placement()
        Place.addFromTiling(tile, OriginX + config.Config['leftmargin'], OriginY + config.Config['bottommargin'])

    (MaxXExtent, MaxYExtent) = Place.extents()
    MaxXExtent += config.Config['rightmargin']
    MaxYExtent += config.Config['topmargin']

    # Start printing out the Gerbers. In preparation for drawing cut marks
    # and crop marks, make sure we have an aperture to draw with. Use a 10mil line.
    # If we're doing a fabrication drawing, we'll need a 1mil line.
    OutputFiles = []

    try:
        fullname = config.MergeOutputFiles['placement']
    except KeyError:
        fullname = 'merged.placement.xml'
    Place.write(fullname)
    OutputFiles.append(fullname)

    # For cut lines
    AP = aptable.Aperture(aptable.Circle, 'D??', config.Config['cutlinewidth'])
    drawing_code_cut = aptable.findInApertureTable(AP, config.GAT)
    if drawing_code_cut is None:
        drawing_code_cut = aptable.addToApertureTable(AP, config.GAT)

    # For crop marks
    AP = aptable.Aperture(aptable.Circle, 'D??', config.Config['cropmarkwidth'])
    drawing_code_crop = aptable.findInApertureTable(AP, config.GAT)
    if drawing_code_crop is None:
        drawing_code_crop = aptable.addToApertureTable(AP, config.GAT)

    # For fiducials
    drawing_code_fiducial_copper = drawing_code_fiducial_soldermask = None
    if config.Config['fiducialpoints']:
        AP = aptable.Aperture(aptable.Circle, 'D??', config.Config['fiducialcopperdiameter'])
        drawing_code_fiducial_copper = aptable.findInApertureTable(AP, config.GAT)
        if drawing_code_fiducial_copper is None:
            drawing_code_fiducial_copper = aptable.addToApertureTable(AP, config.GAT)
        AP = aptable.Aperture(aptable.Circle, 'D??', config.Config['fiducialmaskdiameter'])
        drawing_code_fiducial_soldermask = aptable.findInApertureTable(AP, config.GAT)
        if drawing_code_fiducial_soldermask is None:
            drawing_code_fiducial_soldermask = aptable.addToApertureTable(AP, config.GAT)

    if config.text:
        text_size_ratio = 0.5  # proportion of Y spacing to use for text (much of this is taken up by, e.g., cutlines)
        if not config.text_size:
            print("Computing text size based on Y spacing...")
        text_size = config.text_size if config.text_size else (config.Config['yspacing'] * 1000.0) * text_size_ratio
        if text_size < config.min_text_size:
            print("Warning: Text size ({0} mils) less than minimum ({1} mils), using minimum.".format(text_size, config.min_text_size))
        text_size = max(text_size, config.min_text_size)
        print("Using text size: {0} mils".format(text_size))

        # by default, set stroke proportional to the size based on the ratio of the minimum stroke to the minimum size
        if not config.text_stroke:
            print("Computing text stroke based on text size...")
        text_stroke = config.text_stroke if config.text_stroke else int((text_size / config.min_text_size) * config.min_text_stroke)
        if text_stroke < config.min_text_stroke:
            print("Warning: Text stroke ({0} mils) less than minimum ({1} mils), using minimum.".format(text_stroke, config.min_text_stroke))
        text_stroke = max(text_stroke, config.min_text_stroke)
        print("Using text stroke: {0} mils".format(text_stroke))

        AP = aptable.Aperture(aptable.Circle, 'D??', text_stroke / 1000.0)
        drawing_code_text = aptable.findInApertureTable(AP, config.GAT)
        if drawing_code_text is None:
            drawing_code_text = aptable.addToApertureTable(AP, config.GAT)

    # For fabrication drawing.
    AP = aptable.Aperture(aptable.Circle, 'D??', 0.001)
    drawing_code1 = aptable.findInApertureTable(AP, config.GAT)
    if drawing_code1 is None:
        drawing_code1 = aptable.addToApertureTable(AP, config.GAT)

    updateGUI("Writing merged files...")
    print("Writing merged output files ...")

    for layername in config.LayerList.keys():
        lname = layername
        if lname[0] == '*':
            lname = lname[1:]

        try:
            fullname = config.MergeOutputFiles[layername]
        except KeyError:
            fullname = "merged.{:s}.ger".format(lname)
        OutputFiles.append(fullname)
        fid = open(fullname, 'wt')
        writeGerberHeader(fid)

        # Determine which apertures and macros are truly needed
        apUsedDict = {}
        apmUsedDict = {}
        for job in Place.jobs:
            apd, apmd = job.aperturesAndMacros(layername)
            apUsedDict.update(apd)
            apmUsedDict.update(apmd)

        # Increase aperature sizes to match minimum feature dimension
        if layername in config.MinimumFeatureDimension:

            print("  Thickening", lname, "feature dimensions ...")

            # Fix each aperture used in this layer
            for ap in list(apUsedDict.keys()):
                new = config.GAT[ap].getAdjusted(config.MinimumFeatureDimension[layername])
                if not new:  # current aperture size met minimum requirement
                    continue
                else:       # new aperture was created
                    new_code = aptable.findOrAddAperture(new, config.GAT)  # get name of existing aperture or create new one if needed
                    del apUsedDict[ap]                         # the old aperture is no longer used in this layer
                    apUsedDict[new_code] = None                # the new aperture will be used in this layer

                    # Replace all references to the old aperture with the new one
                    for joblayout in Place.jobs:
                        job = joblayout.job  # access job inside job layout
                        temp = []
                        if job.hasLayer(layername):
                            for x in job.commands[layername]:
                                if x == ap:
                                    temp.append(new_code)  # replace old aperture with new one
                                else:
                                    temp.append(x)         # keep old command
                            job.commands[layername] = temp

        if config.Config['cutlinelayers'] and (layername in config.Config['cutlinelayers']):
            apUsedDict[drawing_code_cut] = None

        if config.Config['cropmarklayers'] and (layername in config.Config['cropmarklayers']):
            apUsedDict[drawing_code_crop] = None

        if config.Config['fiducialpoints']:
            if ((layername == '*toplayer') or (layername == '*bottomlayer')):
                apUsedDict[drawing_code_fiducial_copper] = None
            elif ((layername == '*topsoldermask') or (layername == '*bottomsoldermask')):
                apUsedDict[drawing_code_fiducial_soldermask] = None

        if config.text:
            apUsedDict[drawing_code_text] = None

        # Write only necessary macro and aperture definitions to Gerber file
        gerber.writeApertureMacros(fid, apmUsedDict)
        gerber.writeApertures(fid, apUsedDict)

        # Finally, write actual flash data
        for job in Place.jobs:

            updateGUI("Writing merged output files...")
            job.writeGerber(fid, layername)

            if config.Config['cutlinelayers'] and (layername in config.Config['cutlinelayers']):
                fid.write("{:s}*\n".format(drawing_code_cut))    # Choose drawing aperture
                job.writeCutLines(fid, drawing_code_cut, OriginX, OriginY, MaxXExtent, MaxYExtent)

        if config.Config['cropmarklayers']:
            if layername in config.Config['cropmarklayers']:
                gerber.writeCropMarks(fid, drawing_code_crop, OriginX, OriginY, MaxXExtent, MaxYExtent)

        if config.Config['fiducialpoints']:
            if ((layername == '*toplayer') or (layername == '*bottomlayer')):
                gerber.writeFiducials(fid, drawing_code_fiducial_copper, OriginX, OriginY, MaxXExtent, MaxYExtent)
            elif ((layername == '*topsoldermask') or (layername == '*bottomsoldermask')):
                gerber.writeFiducials(fid, drawing_code_fiducial_soldermask, OriginX, OriginY, MaxXExtent, MaxYExtent)
        if config.Config['outlinelayers'] and (layername in config.Config['outlinelayers']):
            gerber.writeOutline(fid, OriginX, OriginY, MaxXExtent, MaxYExtent)

        if config.text:
            Y += row.height_in() + config.Config['yspacing']
            x = config.text_x if config.text_x else util.in2mil(OriginX + config.Config['leftmargin']) + 100  # convert inches to mils 100 is extra margin
            y_offset = ((config.Config['yspacing'] * 1000.0) - text_size) / 2.0
            y = config.text_y if config.text_y else util.in2mil(OriginY + config.Config['bottommargin'] + Place.jobs[0].height_in()) + y_offset  # convert inches to mils
            fid.write("{:s}*\n".format(drawing_code_text))    # Choose drawing aperture
            makestroke.writeString(fid, config.text, int(util.mil2gerb(x)), int(util.mil2gerb(y)), 0, int(text_size))
        gerber.writeFooter(fid)

        fid.close()

    # Write board outline layer if selected
    fullname = config.Config['outlinelayerfile']
    if fullname and fullname.lower() != "none":
        OutputFiles.append(fullname)
        fid = open(fullname, 'wt')
        writeGerberHeader(fid)

        gerber.writeOutline(fid, OriginX, OriginY, MaxXExtent, MaxYExtent)

        gerber.writeFooter(fid)
        fid.close()

    # Write scoring layer if selected
    fullname = config.Config['scoringfile']
    if fullname and fullname.lower() != "none":
        OutputFiles.append(fullname)
        fid = open(fullname, 'wt')
        writeGerberHeader(fid)

        # Write width-1 aperture to file
        AP = aptable.Aperture(aptable.Circle, 'D10', 0.001)
        AP.writeDef(fid)

        # Choose drawing aperture D10
        gerber.writeCurrentAperture(fid, 10)

        # Draw the scoring lines
        scoring.writeScoring(fid, Place, OriginX, OriginY, MaxXExtent, MaxYExtent, config.Config['xspacing'], config.Config['yspacing'])

        gerber.writeFooter(fid)
        fid.close()

    # Get a list of all tools used by merging keys from each job's dictionary
    # of tools.
    # Grab all tool diameters and sort them.
    allToolDiam = []
    for job in config.Jobs.values():
        for tool, diam in job.xdiam.items():
            if diam in config.GlobalToolRMap:
                continue

            allToolDiam.append(diam)
    allToolDiam.sort()
    
    # Then construct global mapping of diameters to tool numbers
    toolNum = 1
    for d in allToolDiam:
        config.GlobalToolRMap[d] = "T{:02d}".format(toolNum)
        toolNum += 1

    # Cluster similar tool sizes to reduce number of drills
    if config.Config['drillclustertolerance'] > 0:
        config.GlobalToolRMap = drillcluster.cluster(config.GlobalToolRMap, config.Config['drillclustertolerance'])
        drillcluster.remap(Place.jobs, list(config.GlobalToolRMap.items()))

    # Now construct mapping of tool numbers to diameters
    for diam, tool in config.GlobalToolRMap.items():
        config.GlobalToolMap[tool] = diam

    # Tools is just a list of tool names
    Tools = list(config.GlobalToolMap.keys())
    Tools.sort()

    fullname = config.Config['fabricationdrawingfile']
    if fullname and fullname.lower() != 'none':
        if len(Tools) > strokes.MaxNumDrillTools:
            raise RuntimeError("Only {:d} different tool sizes supported for fabrication drawing.".format(strokes.MaxNumDrillTools))

        OutputFiles.append(fullname)
        fid = open(fullname, 'wt')
        writeGerberHeader(fid)
        gerber.writeApertures(fid, {drawing_code1: None})
        fid.write("{:s}*\n".format(drawing_code1))    # Choose drawing aperture

        fabdrawing.writeFabDrawing(fid, Place, Tools, OriginX, OriginY, MaxXExtent, MaxYExtent)

        gerber.writeFooter(fid)
        fid.close()

    # Finally, print out the Excellon
    try:
        fullname = config.MergeOutputFiles['drills']
    except KeyError:
        fullname = "merged.drills.xln"
    OutputFiles.append(fullname)
    fid = open(fullname, 'wt')

    excellon.writeheader(fid, [(x, config.GlobalToolMap[x]) for x in Tools], units='in')

    # Ensure each one of our tools is represented in the tool list specified
    # by the user.
    for tool in Tools:
        try:
            size = config.GlobalToolMap[tool]
        except:
            raise RuntimeError("INTERNAL ERROR: Tool code {:s} not found in global tool map".format(tool))

        # Write the tool name then all of the positions where it will be drilled.
        excellon.writetoolname(fid, tool)
        for job in Place.jobs:
            job.writeExcellon(fid, size)

    excellon.writefooter(fid)
    fid.close()

    updateGUI("Closing files...")

    # Compute stats
    jobarea = 0.0
    for job in Place.jobs:
        jobarea += job.jobarea()

    totalarea = ((MaxXExtent - OriginX) * (MaxYExtent - OriginY))

    ToolStats = {}
    drillhits = 0
    for tool in Tools:
        ToolStats[tool] = 0
        for job in Place.jobs:
            hits = job.drillhits(config.GlobalToolMap[tool])
            ToolStats[tool] += hits
            drillhits += hits

    try:
        fullname = config.MergeOutputFiles['toollist']
    except KeyError:
        fullname = "merged.toollist.drl"
    OutputFiles.append(fullname)
    fid = open(fullname, 'wt')

    print('-' * 50)
    print("     Job Size : {:f}\" x {:f}\"".format(MaxXExtent - OriginX, MaxYExtent - OriginY))
    print("     Job Area : {:.2f} sq. in.".format(totalarea))
    print("   Area Usage : {:.1f}%".format(jobarea / totalarea * 100))
    print("   Drill hits : {:d}".format(drillhits))
    print("Drill density : {:.1f} hits/sq.in.".format(drillhits / totalarea))

    print("\nTool List:")
    smallestDrill = 999.9
    for tool in Tools:
        if ToolStats[tool]:
            fid.write("{:s} {:.4f}in\n".format(tool, config.GlobalToolMap[tool]))
            print("  {:s} {:.4f}\" {:5d} hits".format(tool, config.GlobalToolMap[tool], ToolStats[tool]))
            smallestDrill = min(smallestDrill, config.GlobalToolMap[tool])

    fid.close()
    print("Smallest Tool: {:.4f}in".format(smallestDrill))

    print()
    print("Output Files :")
    for f in OutputFiles:
        print("  ", f)

    if (MaxXExtent - OriginX) > config.Config['panelwidth'] or (MaxYExtent - OriginY) > config.Config['panelheight']:
        print('*' * 75)
        print("*")
        print("* ERROR: Merged job {:.3f}\"x{:.3f}\" exceeds panel dimensions of {:.3f}\"x{:.3f}\"".format(MaxXExtent - OriginX, MaxYExtent - OriginY, config.Config['panelwidth'], config.Config['panelheight']))
        print("*")
        print('*' * 75)
        sys.exit(1)

    # Done!
    return 0


def _tile_search_exhaustive(q, Jobs, X, Y, xspacing, yspacing, searchTimeout):
    search = tilesearch.ExhaustiveSearch(Jobs, X, Y, xspacing, yspacing, searchTimeout)
    search.run(q)


def tile_search_exhaustive(Jobs, X, Y, xspacing, yspacing, searchTimeout):
    """Wrapper around ExhaustiveSearch to handle keyboard interrupt, etc."""

    search = tilesearch.ExhaustiveSearch(Jobs, X, Y, xspacing, yspacing, searchTimeout)

    possiblePermutations = (2 ** len(Jobs)) * factorial(len(Jobs))
    print('=' * 70)
    print("Starting placement using exhaustive search.")
    print("There are {:d} possible permutations...".format(possiblePermutations))
    if possiblePermutations < 1e4:
        print("this'll take no time at all.")
    elif possiblePermutations < 1e5:
        print("surf the web for a few minutes.")
    elif possiblePermutations < 1e6:
        print("take a long lunch.")
    elif possiblePermutations < 1e7:
        print("come back tomorrow.")
    else:
        print("don't hold your breath.")
    print("Press Ctrl-C to stop and use the best placement so far.")
    print("Estimated maximum possible utilization is {:.1f}%.".format(tiling.maxUtilization(Jobs, xspacing, yspacing) * 100))

    try:
        search.run()
    except KeyboardInterrupt:
        print(search)
        print()
        print("Interrupted.")

    #TODO: Remove this obsolete code
    #computeTime = time.time() - x.startTime
    #print("Computed {:d} permutations in {:d} seconds / {:.1f} permutations/second".format(x.permutations, computeTime, x.permutations / computeTime))
    print('=' * 70)

    return search.bestTiling


def _tile_search_random(q, Jobs, X, Y, xspacing, yspacing, searchTimeout, exhaustiveSearchJobs):
    search = tilesearch.RandomSearch(Jobs, X, Y, xspacing, yspacing, searchTimeout, exhaustiveSearchJobs)
    search.run(q)


def tile_search_random(Jobs, X, Y, xspacing, yspacing, searchTimeout, exhaustiveSearchJobs):
    """Wrapper around RandomSearch to handle keyboard interrupt, etc."""

    print("=" * 70)
    print("Starting random placement trials. You must press Ctrl-C to")
    print("stop the process and use the best placement so far.")
    print("Estimated maximum possible utilization is {:.1f}.".format(tiling.maxUtilization(Jobs, xspacing, yspacing) * 100))

    bestScore = float("inf")
    bestTiling = None
    placementsTried = 0
    startTime = time.time()
    q = multiprocessing.Queue()
    p = []
    for i in range(multiprocessing.cpu_count()):
        p.append(multiprocessing.Process(target=_tile_search_random, args=(q, Jobs, X, Y, xspacing, yspacing, searchTimeout, exhaustiveSearchJobs)))
    try:
        for i in p:
            i.start()
        while 1:
            time.sleep(3)
            foundBetter = False
            try:
                newResult = q.get(block=False)
                while newResult is not None:
                    placementsTried += newResult[0]
                    if newResult[1] and newResult[1].area() < bestScore:
                        bestTiling = newResult[1]
                        foundBetter = True
                        bestScore = newResult[1].area()
                    newResult = q.get(block=False)
            except queue.Empty:
                if foundBetter:
                    if bestTiling:
                        utilization = bestTiling.usedArea() / bestTiling.area() * 100.0
                    else:
                        utilization = 0.0
                    print("\nTested {:d} placements over {:d} seconds. Best tiling at {:.2f}% usage.".format(placementsTried, time.time() - startTime, utilization))
                else:
                    print(".", end='')
                    sys.stdout.flush()
    except KeyboardInterrupt:
        for i in p:
            i.terminate()
        print("\nSearch ended by user.")

    computeTime = time.time() - startTime
    print("Computed {:d} placements in {:d} seconds ({:.1f} placements/second).".format(placementsTried, computeTime, placementsTried / computeTime))
    print("=" * 70)

    return bestTiling


def updateGUI(text=None):
    global GUI
    if GUI is not None:
        GUI.updateProgress(text)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge gerber files for individual boards into a single panel. Can follow\nmanual layouts or search for optimal arrangements.", epilog="If a layout file is not specified, automatic placement is performed. The layout\nfile can specify either a relative positioning or a manual positioning. A\nmanual positioning layout file is generated by default by this tool.\n\nNOTE: The dimensions of each job are determined solely by the maximum extent\nof the board outline layer for each job.", formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--search', choices=['random', 'exhaustive'], default='random', help="Specify search method for automatic layouts. Defaults to random.")
    parser.add_argument('--version', action='version', version="%(prog)s " + str(VERSION_MAJOR) + "." + str(VERSION_MINOR))
    parser.add_argument('--rs-esjobs', type=int, help="When using random search, exhaustively search N jobs for each random placement. Only matters when using random search. Defaults to 2.", metavar='N', default=2)
    parser.add_argument('--search-timeout', type=int, help="When using random search, search for T seconds for best random placement. Without this option the search will continue until interrupted by user.", metavar='T', default=0)
    parser.add_argument('--no-trim-gerber', action='store_true', help="Do not attempt to trim Gerber data to extents of board")
    parser.add_argument('--no-trim-excellon', action='store_true', help="Do not attempt to trim Excellon  data to extents of board")
    parser.add_argument('--octagons', choices=['rotate', 'normal'], default='normal', help="Generate octagons in two different styles depending on the argument. 'rotate' sets rotation to 0 while 'normal' rotates the octagons 22.5deg")
    parser.add_argument('--ack', action='store_true', help="Automatically acknowledge disclaimer/warning")
    parser.add_argument('--text', type=str, help="A string of text to print between boards in layout")
    parser.add_argument('--text-size', type=int, metavar='N', help="Size (height in mils) of text. Should be less than 'y spacing' set in .cfg file")
    parser.add_argument('--text-stroke', type=int, metavar='N', default=10, help="Stroke (width in mils) of text.")
    parser.add_argument('--text-x', type=int, default=0, metavar='X', help="X position of text. Defaults to inside space between jobs")
    parser.add_argument('--text-y', type=int, default=0, metavar='Y', help="Y position of text. Defaults to inside space between jobs")
    parser.add_argument('configfile', type=str, help=".cfg file setting configuration values for this panel")
    parser.add_argument('layoutfile', type=str, help=".xml file specifying a manual layout for this panel")

    args = parser.parse_args()

    # Display the disclaimer, skipping it if specified
    disclaimer(args.ack)

    # Run gerbmerge
    try:
        rv = merge(args)
    except RuntimeError as e:
        print(e.args[0])
        print("Exiting...")
    finally:
        rv = 0

    sys.exit(rv)
# vim: expandtab ts=2 sw=2 ai syntax=python
