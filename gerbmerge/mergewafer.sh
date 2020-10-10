#!/bin/bash
gerbmerge --ack --search-timeout 3 --no-trim-gerber gerbmerge_wafer.cfg gerbmerge_wafer.def
rm merged.drills-unplated.xln 


