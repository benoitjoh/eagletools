#!/usr/bin/env python
"""A placement is a final arrangement of jobs at given (X,Y) positions.
This class is intended to "un-pack" an arragement of jobs constructed
manually through Layout/Panel/JobLayout/etc. (i.e., a layout.def file)
or automatically through a Tiling. From either source, the result is
simply a list of jobs.
--------------------------------------------------------------------

This program is licensed under the GNU General Public License (GPL)
Version 3.  See http://www.fsf.org for details of the license.

Rugged Circuits LLC
http://ruggedcircuits.com/gerbmerge
"""

from xml.dom.minidom import getDOMImplementation
import xml.etree.ElementTree as ET
from math import isnan

import jobs
import config


class Placement:
    def __init__(self):
        self.jobs = []

    def addFromTiling(self, t, OriginX, OriginY):
        # t is a Tiling. Calling its canonicalize() method will construct
        # a list of JobLayout objects and set the (X,Y) position of each
        # object.
        self.jobs = self.jobs + t.canonicalize(OriginX, OriginY)

    def addFromFile(self, placementFile, OriginX, OriginY):
        # Preprocess the XML jobs file removing lines that start with '#' as those're comment lines.
        # They're not handled by the XML parser, so we remove them beforehand.
        file = open(placementFile, 'r')
        unparsedXml = ""
        for line in file:
            if line[0] != '#':
                unparsedXml += line

        # Attempt to parse the jobs file
        try:
            root = ET.fromstring(unparsedXml)
        except ET.ParseError as e:
            raise RuntimeError("Layout file cannot be parsed. Error at {0[0]}, {0[1]}.".format(e.position))

        # Build up the array of rows
        rows = []
        for rowspec in root:
            if rowspec.tag == 'row':
                newRow = parseRowSpec(rowspec, config.Jobs)
            elif rowspec.tag == 'col':
                newRow = parseColSpec(rowspec, config.Jobs)
            elif rowspec.tag == 'board':
                newRow = parseJobSpec(rowspec, config.Jobs)
            else:
                raise RuntimeError("Invalid child of root element")
            rows.append(newRow)

        # Do the layout, updating offsets for each component job.
        # This only needs to be done for relative layouts, which don't
        # have Row objects which is why that check is done.
        x = OriginX + config.Config['leftmargin']
        y = OriginY + config.Config['bottommargin']
        for row in rows:
            if type(row) is Row:
                row.setPosition(x, y)
                y += row.height_in() + config.Config['yspacing']

        # Finally store a flattened list of jobs in this Placement
        for row in rows:
            self.jobs += row.canonicalize()

    def extents(self):
        """Return the maximum X and Y value over all jobs"""
        maxX = 0.0
        maxY = 0.0

        for job in self.jobs:
            maxX = max(maxX, job.x + job.width_in())
            maxY = max(maxY, job.y + job.height_in())

        return (maxX, maxY)

    def write(self, fname):
        """Write placement to an XML file of a form similar to that used for the layout files."""
        impl = getDOMImplementation()
        newpanel = impl.createDocument(None, 'panel', None)
        for job in self.jobs:
            board = newpanel.createElement('board')
            splitname = job.job.name.split('*rotated')
            board.setAttribute('name', splitname[0])
            if len(splitname) == 2:
                board.setAttribute('rotation', splitname[1])
            board.setAttribute('x', str(job.x))
            board.setAttribute('y', str(job.y))
            newpanel.documentElement.appendChild(board)
        fid = open(fname, 'wt')
        newpanel.writexml(fid, addindent='\t', newl='\n')
        fid.close()


class Panel:                 # Meant to be subclassed as either a Row() or Col()
    def __init__(self):
        self.x = None
        self.y = None
        self.jobs = []           # List (left-to-right or bottom-to-top) of JobLayout() or Row()/Col() objects

    def canonicalize(self):    # Return plain list of JobLayout objects at the roots of all trees
        L = []
        for job in self.jobs:
            L = L + job.canonicalize()
        return L

    def addjob(self, job):     # Either a JobLayout class or Panel (sub)class
        assert isinstance(job, Panel) or isinstance(job, jobs.JobLayout)
        self.jobs.append(job)

    def addwidths(self):
        "Return width in inches"
        width = 0.0
        for job in self.jobs:
            width += job.width_in() + config.Config['xspacing']
        width -= config.Config['xspacing']
        return width

    def __str__(self):
        "Pretty-prints this panel"
        return self.__class__.__name__ + " " + str([str(x) for x in self.jobs])

    def maxwidths(self):
        "Return maximum width in inches of any one subpanel"
        width = 0.0
        for job in self.jobs:
            width = max(width, job.width_in())
        return width

    def addheights(self):
        "Return height in inches"
        height = 0.0
        for job in self.jobs:
            height += job.height_in() + config.Config['yspacing']
        height -= config.Config['yspacing']
        return height

    def maxheights(self):
        "Return maximum height in inches of any one subpanel"
        height = 0.0
        for job in self.jobs:
            height = max(height, job.height_in())
        return height

    def writeGerber(self, fid, layername):
        for job in self.jobs:
            job.writeGerber(fid, layername)

    def writeExcellon(self, fid, tool):
        for job in self.jobs:
            job.writeExcellon(fid, tool)

    def writeDrillHits(self, fid, tool, toolNum):
        for job in self.jobs:
            job.writeDrillHits(fid, tool, toolNum)

    def writeCutLines(self, fid, drawing_code, X1, Y1, X2, Y2):
        for job in self.jobs:
            job.writeCutLines(fid, drawing_code, X1, Y1, X2, Y2)

    def drillhits(self, tool):
        hits = 0
        for job in self.jobs:
            hits += job.drillhits(tool)

        return hits

    def jobarea(self):
        area = 0.0
        for job in self.jobs:
            area += job.jobarea()

        return area


# TODO: Add pretty-printing functionality
class Row(Panel):
    def __init__(self):
        Panel.__init__(self)
        self.LR = 1   # Horizontal arrangement

    def width_in(self):
        return self.addwidths()

    def height_in(self):
        return self.maxheights()

    def setPosition(self, x, y):   # In inches
        self.x = x
        self.y = y
        for job in self.jobs:
            job.setPosition(x, y)
            x += job.width_in() + config.Config['xspacing']


# TODO: Add pretty-printing functionality
class Col(Panel):
    def __init__(self):
        Panel.__init__(self)
        self.LR = 0   # Vertical arrangement

    def width_in(self):
        return self.maxwidths()

    def height_in(self):
        return self.addheights()

    def setPosition(self, x, y):   # In inches
        self.x = x
        self.y = y
        for job in self.jobs:
            job.setPosition(x, y)
            y += job.height_in() + config.Config['yspacing']


def parseJobSpec(spec, globalJobs):
    # Determine rotation for this job
    rotation = spec.get('rotation', 0)
    try:
        rotation = int(rotation)
    except ValueError:
        raise RuntimeError("Rotation must be specified in degrees as one of [0, 90, 180, 270].")

    # Grab any positional information
    try:
        x = float(spec.get('x', 'nan'))
        y = float(spec.get('y', 'nan'))
    except ValueError:
        raise RuntimeError("Illegal (x,y) coordinates in placement (x='{}',y='{}') file for job '{}'".format(spec.get('x', ''), spec.get('y', ''), spec.get('name')))

    # Now prepare the job
    job = jobs.findJob(spec.get('name'), rotation, globalJobs)
    if not isnan(x) and not isnan(y):
        job.setPosition(x, y)
    return job


def parseColSpec(spec, globalJobs):
    jobs = Col()

    for coljob in spec:
        if coljob.tag == 'board':
            jobs.addjob(parseJobSpec(coljob, globalJobs))
        elif coljob.tag == 'row':
            jobs.addjob(parseRowSpec(coljob, globalJobs))
        else:
            raise RuntimeError("Unexpected element '{:s}' encountered while parsing jobs file".format(coljob.tag))

    return jobs


def parseRowSpec(spec, globalJobs):
    jobs = Row()

    for rowjob in spec:
        if rowjob.tag == 'board':
            jobs.addjob(parseJobSpec(rowjob, globalJobs))
        elif rowjob.tag == 'col':
            jobs.addjob(parseColSpec(rowjob, globalJobs))
        else:
            raise RuntimeError("Unexpected element '{:s}' encountered while parsing jobs file".format(rowjob.tag))

    return jobs
