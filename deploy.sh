#!/bin/bash
rm -rf .git
cd output
git init
git add .
git config user.name "Yori Fang"
git config user.email "fangying2725@gmail.com"
git config --global push.default simple
git commit -m "latest release `date +"%Y-%m-%d %H:%M"`"
git remote add upstream "git@github.com:YoriFang/yorifang.github.io.git"
echo "kernel.love" >> CNAME
git push -u upstream html --force
