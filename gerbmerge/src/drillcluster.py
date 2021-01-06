#!/usr/bin/env python

"""
Drill clustering routines to reduce total number of drills and remap
drilling commands to the new reduced drill set.

--------------------------------------------------------------------

This program is licensed under the GNU General Public License (GPL)
Version 3.  See http://www.fsf.org for details of the license.

Rugged Circuits LLC
http://ruggedcircuits.com/gerbmerge
"""

global _STATUS
_STATUS = True  # indicates status messages should be shown
global _DEBUG
_DEBUG = False   # indicates debug and status messages should be shown


def cluster(drills, tolerance, debug=_DEBUG):
    """
        Take a dictionary of drill names and sizes and cluster them
        A tolerance of 0 will effectively disable clustering

        Returns clustered drill dictionary
    """

    global _DEBUG
    _DEBUG = debug

    clusters = []

    debug_print("\n  " + str(len(drills)) + " Original drills:")
    debug_print(drillsToString(drills))
    debug_print("Clustering drill sizes ...", True)

    # Loop through all drill sizes
    sizes = sorted(drills.keys())
    for size in sizes:

        match = False

        # See if size fits into any current clusters, else make new cluster
        for index in range(len(clusters)):
            c = clusters[index]
            if not len(c):
                break
            mn = min(c)
            mx = max(c)

            if (size >= mx - 2 * tolerance) and (size <= mn + 2 * tolerance):

                debug_print(str_d(size) + " belongs with " + str_d(c))

                clusters[index].append(size)
                match = True
                break

        if not match:
            debug_print(str_d(size) + " belongs in a new cluster")
            clusters.append([size])

    debug_print("\n  Creating new drill dictionary ...")

    new_drills = {}
    tool_num = 0

    # Create new dictionary of clustered drills
    for c in clusters:
        tool_num += 1
        new_drill = "T{:02d}".format(tool_num)
        c.sort()
        new_size = (min(c) + max(c)) / 2.0
        new_drills[new_size] = new_drill

        debug_print("{:s} will be represented by {:s} ({:s})".format(str_d(c), new_drill, str_d(new_size)))

    debug_print("\n {:d} Clustered Drills:".format(len(new_drills)))
    debug_print(drillsToString(new_drills))
    debug_print("Drill count reduced from {:d} to {:d}".format(len(drills), len(new_drills)), True)

    return new_drills


def remap(jobs, globalToolMap, debug=_DEBUG):
    """
        Remap tools and commands in all jobs to match new tool map

        Returns None
    """

    # Set global variables from parameters
    global _DEBUG
    _DEBUG = debug

    debug_print("Remapping tools and commands ...", True)

    for job in jobs:
        job = job.job  # Access job inside job layout
        debug_print("\n  Job name: {:s}".format(job.name))
        debug_print("\n  Original job tools:")
        debug_print(str(job.xdiam))
        debug_print("\n  Original commands:")
        debug_print(str(job.xcommands))
        new_tools = {}
        new_commands = {}
        for tool, diam in job.xdiam.items():

            # Search for best matching tool
            best_diam, best_tool = globalToolMap[0]

            for glob_diam, glob_tool in globalToolMap:
                if abs(glob_diam - diam) < abs(best_diam - diam):
                    best_tool = glob_tool
                    best_diam = glob_diam
            new_tools[best_tool] = best_diam

            # Append commands to existing commands if they exist
            if best_tool in new_commands:
                temp = new_commands[best_tool]
                temp.extend(job.xcommands[tool])
                new_commands[best_tool] = temp
            else:
                new_commands[best_tool] = job.xcommands[tool]

        debug_print("\n  New job tools:")
        debug_print(str(new_tools))
        debug_print("\n  New commands:")
        debug_print(str(new_commands))
        job.xdiam = new_tools
        job.xcommands = new_commands


def debug_print(text, status=False, newLine=True):
    """
        Print debugging statemetns

        Returs None, Printts text
    """

    if _DEBUG or (status and _STATUS):
        if newLine:
            print(" ", text)
        else:
            print(" ", text)


def str_d(drills):
    """
        Format drill sizes for printing debug and status messages

        Returns drills as formatted string
    """

    string = ""

    try:
        len(drills)
    except:
        string = "{:.4f}".format(drills)
    else:
        string = "["
        for drill in drills:
            string += ("{:.4f}, ".format(drill))
        string = string[:len(string) - 2] + "]"

    return string


def drillsToString(drills):
    """
        Format drill dictionary for printing debug and status messages

        Returns drills as formatted string
    """
    string = ""

    drills = sorted(drills.items())
    for size, drill in drills:
        string += "{:s} = {:s}\n  ".format(drill, str_d(size))

    return string

"""
    The following code runs test drill clusterings with random drill sets.
"""

if __name__ == "__main__":
    import random

    print("  Clustering random drills...")

    old = {}
    tool_num = 0
    while len(old) < 99:
        rand_size = round(random.uniform(.02, .04), 4)
        if rand_size in old:
            continue
        tool_num += 1
        old[rand_size] = "T{:02d}".format(tool_num)

    new = cluster(old, .0003, True)
