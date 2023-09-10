#! /bin/bash

cd ~/tldr_news;
. /home/galois/.local/share/virtualenvs/tldr_news-6Za7KCig/bin/activate;
python3 script.py > ~/tldr_news/logs/log.txt 2>&1;

