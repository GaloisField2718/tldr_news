import imaplib
import email
from dotenv import dotenv_values
import os
import datetime
from pprint import pprint
import re
from bs4 import BeautifulSoup

def parse_content(html):
    
    soup = BeautifulSoup(html, 'html.parser')
    articles = soup.find_all('table')

    titles = []
    summaries = []

    for article in articles:
        title = article.find('strong').text
        link = article.find('a')
        if link and 'href' in link.attrs:
            link = link['href']
        else:
            link = None
        summary = article.find('span', {'style': re.compile('font-family')})
        summary = summary.text.strip()
        titles.append(title)
        summaries.append(summary)
        print(title)
        print(link)
        print(summary)

    return titles, summaries, articles

now = datetime.datetime.now() + datetime.timedelta(hours=2)
print(now.strftime("[%d-%m-%Y %H:%M:%S]")+ " Script is running")

config = dotenv_values(".env")
password = config['KEY']
email_address = config['email']

imap_server = "imap.gmail.com"

imap = imaplib.IMAP4_SSL("74.125.20.108")
imap.login(email_address,password)

imap.select('Inbox')

status, msgnums = imap.search(None, 'FROM "dan@tldrnewsletter.com"')


topics=["AI", "Crypto", "Design", "Cybersecurity", "Founders", "Web Dev", "Marketing", ""]


def display_message(ids, id_):
    msgnum = ids[id_]
    _,data = imap.fetch(msgnum, "(RFC822)")
    message = email.message_from_bytes(data[0][1])
    print(f"\n ------- DATA FROM {id_} id  --------------\n")

    print(f" \n ----- MESSAGE FROM {id_} id  -----------\n ")

    file = f'./tldr_{id_}.html'
    html_body = None
    if message.is_multipart():
        for part in message.get_payload():
            if part.get_content_type() == 'text/html':
                html_body = part.as_string()

    
    if html_body:    
        # Remove more than 2 newlines
        parse_content(html_body) 
        html_body = re.sub(r'\n\s*\n', '\n\n', html_body)

        # Remove whitespace between tags
        html_body = re.sub(r'>\s+<', '><', html_body)
        titles, summaries, articles = parse_content(html_body)
        print(articles)

        with open(file,'w') as f:
            f.write(html_body)
    else :
        print('html_body is None')

    print('New file added')


ids = msgnums[0].split() 
last = len(ids) - 1

mid = last//2

display_message(ids,0)
display_message(ids, last)
display_message(ids, mid)



