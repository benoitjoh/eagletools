#! /bin/bash
# install old library for eagle 7
sudo dpkg -i libssl1.0.0_1.0.2g-1ubuntu4.18_amd64.deb

echo "trying to downloade eagle from http://eagle.autodesk.com/eagle/software-versions/1"
wget http://eagle.autodesk.com/eagle/download-software/5
mv 5 eaglesetup770.run
chmod 755 eaglesetup770.run

#firefox http://eagle.autodesk.com/eagle/software-versions/1
./eaglesetup770.run
