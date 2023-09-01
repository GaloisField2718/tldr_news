import os
import imaplib
import email
from bs4 import BeautifulSoup 
from dotenv import dotenv_values
import html
import re
import urllib.parse
from datetime import datetime

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

all_ids = data[0].split()

# Filter out existing ids
new_ids = [id for id in all_ids if id not in ids_read]

is_written = False

for num in new_ids:
    print(num)
    is_written = False
    _, email_data = imap.fetch(num, '(RFC822)')
    raw_email = email_data[0][1]
    # Decode HTML entities
    raw_email = html.unescape(raw_email.decode())
	#print(raw_email)
    msg = email.message_from_string(raw_email)
    date_envoi = datetime.strptime(msg['Date'], '%a, %d %b %Y %H:%M:%S %z')
    print('Date envoi : ', date_envoi)

    soup = BeautifulSoup(raw_email, 'html.parser')
	#print(soup.prettify())

    articles = []

    for div in soup.find_all('div', class_='3D"text-block"'):
        print('\n div : \n', div)

        if div.find('strong') and div.find('a') and div.find('span'):
            title = div.find('strong').text
            title = html.unescape(title)
            title = title.replace("=","")
            title = title.replace('\r\n','')
            link = div.find('a')
            pattern = r'href=*?">'

            decoded_link = urllib.parse.unquote(link)
            match = re.search(pattern, str(decoded_link))
            
            if match:
                print(match)
                url = match.group(0)
                url = replace("href='3D","")
                url = replace(">","")
                url = urllib.parse.unquote(url)
                print('\n link : \n ', url)
            
            else:
                url='https://tldr.tech'
            
            summary = div.find('span').text
            summary = html.unescape(summary)
            summary = summary.replace("=","")
            cleaned_summary = summary.replace('\r\n','')
            article = {
	            'title': title,
	            'link': url,
	            'summary': cleaned_summary
	            }
            articles.append(article)
    
    if articles:
        articles.pop()
        print(articles)
        date_for_filename = date_envoi.date()
        for topic in topics:
            if f"TLDR {topic}" in raw_email:
                filename = f"article_{date_for_filename.strftime('%d-%m-%Y')}.md"
                folder = f"TLDR_{topic}"
                # Créer le dossier s'il n'existe pas
                if not os.path.exists(folder):
                    os.makedirs(folder)

                # Enregistrer le fichier
                filepath = os.path.join(folder, filename)
                with open(filepath, "w") as f:
                    f.write(f"# Articles TLDR {topic} {date_for_filename.strftime('%d-%m-%Y')}\n\n")
                    for i, article in enumerate(articles):
                        f.write(f'## Article {i+1}\n')
                        f.write(f'### [{article["title"]}]({article["link"]})\n')
                        f.write(f'### Summary \n {article["summary"]}\n\n')
                        is_written = True
    if is_written:    
        # Write the email id in ids.txt. I do here to be sure that the textfile is written
        with open('ids.txt', 'a') as i:
            i.write(f'{num}\n')

print('Latest email articles extracted!')
