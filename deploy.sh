#!/bin/bash
rm -rf .git
cd output
git init -b main
echo "kernel.love" >> CNAME
git add .
git config user.name "Yori Fang"
git config user.email "fangying2725@gmail.com"
git config --global push.default simple
git commit -m "latest release `date +"%Y-%m-%d %H:%M"`"
git remote add origin "git@github.com:YoriFang/yorifang.github.io-src.git"
git checkout -b html
git push -u origin html:html --force
