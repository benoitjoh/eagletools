
rm *.jpg
ls *.eps | xargs -n 1 bash -c 'convert -density 1200 $0 $0.jpg'
montage *eps.jpg -adjoin -rotate 90 -tile 2x2 -geometry 1600x2000+40+40 4aufeinerseite.jpg

