
#     script.py
#
#   Target dan@tldrnewsletter.com puis enregistre automatiquement ses mails
#
#

import os

import imaplib
import email

from dotenv import dotenv_values

import html
import re
import urllib.parse
from bs4 import BeautifulSoup 

from datetime import datetime
import ast # To transform ids string from ids.txt in bytes
from link import extract_url

import quopri

##########################################
####        CONFIG      #################
########################################
config = dotenv_values(".env")
password = config['KEY']
username = config['email']

########################################
######      CONNEXION       ############
########################################
imap = imaplib.IMAP4_SSL("74.125.20.108")
imap.login(username, password)
imap.select("inbox")

#########################################
######      CATCH DATA          #########
#########################################
# Search for latest email from dan@tldrnewsletter.com
typ, data = imap.search(None, 'FROM "dan@tldrnewsletter.com"') 
#print(data)

topics = ["AI", "Crypto", "Design", "Cybersecurity", "Founders", "Web Dev", "Marketing","InfoSec", ""]

ids_read = []
with open('ids.txt','r') as i:
  ids_read = [line.strip() for line in i] 

ids_read = [ast.literal_eval(id) for id in ids_read]
print(f"ids read : {ids_read}")
all_ids = data[0].split()

# Filter out existing ids
new_ids = [id for id in all_ids if id not in ids_read]

print(f"new ids : {new_ids}")


for num in range(1,5):
  print('\n \n ') 

  num = new_ids[num]

  _, email_data = imap.fetch(num, '(RFC822)')
  print(email_data)

  raw_email = email_data[0][1]
 
  msg = quopri.decodestring(raw_email)
  print('type msg : ', type(msg))

  body = email.message_from_bytes(msg)

  payload = body.get_payload()

  print(' PAYLOAD 0 : ', payload[0])
  print(' PAYLOAD 1 : ', payload[1])

  pattern = r"View\r\nOnline\r\n[(.+?)](\r\n)"
  print(' BODY   : ', body)

#  match = re.search(pattern,msg)
  
#  print('match group(0) : ', match.group(0))

#  print('match group(1) : ', match.group(1))

#  online_link = match.group(1)

  print('\n\n  msg : \n', msg)

#  print('\n\n\n   url online : \n', online_link,'\n \n ')




#for num in new_ids:
#    print(num)
#    is_written = False
#    _, email_data = imap.fetch(num, '(RFC822)')
#    raw_email = email_data[0][1]
#    # Decode HTML entities
#    raw_email = html.unescape(raw_email.decode())
#	#print(raw_email)
#    msg = email.message_from_string(raw_email)
#    date_envoi = datetime.strptime(msg['Date'], '%a, %d %b %Y %H:%M:%S %z')
#    print('Date envoi : ', date_envoi)
#
#    soup = BeautifulSoup(raw_email, 'html.parser')
#	#print(soup.prettify())
#
#    articles = []
#
#    for div in soup.find_all('div', class_='3D"text-block"'):
#        print('\n div : \n', div)
#
#        if div.find('strong') and div.find('a') and div.find('span'):
#            
#            title = div.find('strong').text
#            title = html.unescape(title)
#            title = title.replace("=","")
#            title = title.replace('\r\n','')
#
#            a_tag = div.find('a')
#            print('a tag complet : ', a_tag)
#            opening_tag = a_tag.split('>', 1) 
#
#            print('a tag : ',opening_tag)
#            url = extract_url(opening_tag)
#
#            summary = div.find('span').text
#            summary = html.unescape(summary)
#            summary = summary.replace("=","")
#            cleaned_summary = summary.replace('\r\n','')
#            
#            article = {
#	            'title': title,
#	            'link': url,
#	            'summary': cleaned_summary
#	            }
#            
#            articles.append(article)
#    
#    if articles:
#        articles.pop()
#        print(articles)
#        date_for_filename = date_envoi.date()
#        for topic in topics:
#            if f"TLDR {topic}" in raw_email:
#                filename = f"article_{date_for_filename.strftime('%d-%m-%Y')}.md"
#                folder = f"TLDR_{topic}"
#                # Créer le dossier s'il n'existe pas
#                if not os.path.exists(folder):
#                    os.makedirs(folder)
#
#                # Enregistrer le fichier
#                filepath = os.path.join(folder, filename)
#                with open(filepath, "w") as f:
#                    f.write(f"# Articles TLDR {topic} {date_for_filename.strftime('%d-%m-%Y')}\n\n")
#                    for i, article in enumerate(articles):
#                        f.write(f'## Article {i+1}\n')
#                        f.write(f'### [{article["title"]}]({article["link"]})\n')
#                        f.write(f'### Summary \n {article["summary"]}\n\n')
#                        is_written= True
#    print("is writen  : ", is_written)
#    if is_written:    
#        # Write the email id in ids.txt. I do here to be sure that the textfile is written
#        with open('ids.txt', 'a') as i:
#            i.write(f'{num}\n')
#
#print('Latest email articles extracted!')
