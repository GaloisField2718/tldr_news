#!/bin/bash

git pull;
git add .;
git commit -m "Daily TLDR updates";
git push > ./logs/out.txt 2> ./logs/err.txt;
