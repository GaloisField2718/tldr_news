
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

all_ids = data[0].decode().split()
all_ids = [int(id_) for id_ in all_ids]

ids_read = [ast.literal_eval(line.strip()) for line in open('ids.txt')]

new_ids = [id_ for id_ in all_ids if id_ not in ids_read]

print(f"new ids : {new_ids}")

is_written = False

num

for num in new_ids[::-1]:
  print(num)
  is_written = False
  _, email_data = imap.fetch(num, '(RFC822)')
  raw_email = email_data[0][1]
  msg = email.message_from_bytes(raw_email)
  date_envoi = datetime.strptime(msg['Date'], '%a, %d %b %Y %H:%M:%S %z')
  print('Date envoi : ', date_envoi)
  

  sender = msg['From']
  pattern = r' <dan@tldrnewsletter.com>'
  sender = re.sub(pattern,'', sender)
  pattern = r'=?utf-\w+\?Q\?.+\?='
  sender = re.sub(pattern, '', sender)
  sender = sender.replace(' =?', '')
  print(sender)
  

  newsletter = ""
  
  for part in msg.walk():
    if part.get_content_type()=='text/plain':
      part_text = part.get_payload()
      part_decoded = quopri.decodestring(part_text)
      part_string = part_decoded.decode('utf-8')
      newsletter = part_string
  
#  print('La newsletter du ', date_envoi, ' est \n\n ', newsletter)

print('Latest email articles extracted!')
