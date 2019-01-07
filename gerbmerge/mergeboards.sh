#!/bin/bash
if ['$1' = ''];
  then
  echo "*******************************************************"
  echo "* errror:                                             *"
  echo "* script expects one argument: the timeout in seconds *"
  echo "*******************************************************"
  exit;
fi
gerbmerge --search-timeout $1 gerbmerge_atmwm.cfg
rm merged.drills-unplated.xln 


