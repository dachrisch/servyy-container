#!/bin/bash

pushd serve
echo "extracting archive..."
unzip -o ../achim-hoefer-html.zip 

echo "setting file modes..."
find . -type f -exec chmod 664 {} \;
find . -type d -exec chmod 775 {} \;

echo "fixing html files"
for html_file in *.html;do
  sed -i '5 i <meta charset="utf-8" />' $html_file
  sed -i 's/href="\/playground_assets\/favicon/href="\/public\/playground_assets\/favicon/' $html_file
done

