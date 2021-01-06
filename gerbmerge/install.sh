#! /bin/bash
echo "... installing gerbmerge"
PYTHONVERSION=$(python3 --version)
if [ "${PYTHONVERSION:7:2}" == "3." ]
then
    echo "[ OK ] Python 3 is installed"
else
    echo "[ ERR ] Python3 not found"
    exit
fi

echo "... copying pythonscripts to /opt/gerbmerge"
sudo mkdir /opt/gerbmerge
sudo cp src/* /opt/gerbmerge
echo "... copying startscript to /usr/bin"
sudo cp gerbmerge /usr/bin/
sudo chmod 755 /usr/bin/gerbmerge


