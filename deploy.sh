#!/bin/bash

cd output
git add .
git config user.name "Yori Fang"
git config user.email "fangying2725@gmail.com"
git config --global push.default simple
git commit -m "latest release `date +"%Y-%m-%d %H:%M"`"
echo "kernel.love" >> CNAME
git push -u origin main --force
