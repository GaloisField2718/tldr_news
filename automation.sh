#! /bin/bash

cd ~/bots/tldr_news;
. /home/galois/.local/share/virtualenvs/tldr_news-_ykhbpHM/bin/activate;
python3 script.py > ~/bots/tldr_news/logs/log.txt 2>&1;

