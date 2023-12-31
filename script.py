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
print(f"All ids : {all_ids}")


is_written = False

for num in all_ids[::-1]:
  print(num)
  is_written = False
  _, email_data = imap.fetch(str(num), '(RFC822)')
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
    
  date_for_filename = date_envoi.date()
    
  topic = sender
  filename = f"article_{date_for_filename.strftime('%d-%m-%Y')}.md"
  folder = f"{topic}"
  
  # Créer le dossier s'il n'existe pas
  if not os.path.exists(folder):
    os.makedirs(folder)
  
  # Enregistrer le fichier
  filepath = os.path.join(folder, filename)
  with open(filepath, "w") as f:
    f.write(f"# Articles {topic} {date_for_filename.strftime('%d-%m-%Y')}\n\n")
    f.write(newsletter)
    is_written= True
                    
  print("is writen  : ", is_written)
  if is_written:
    imap.store(str(num), "+FLAGS", "\\Deleted")
    imap.expunge()
    print('Email ', str(num), ' is deleted!')
# close the mailbox
imap.close()
# logout from the account
imap.logout()
 
print('Latest email articles extracted!')
