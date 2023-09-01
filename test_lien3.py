import re
from urllib.parse import unquote
from bs4 import BeautifulSoup

a_tag = """<a 0100018a4b7ac1a8-38de07f5-11aa-4ac9-9f19-f18e1e1ff8e3-000000="" cb6xb6gprfur8o='STnqFWZlRazh1XWUrCAs_X6tSlncQ=3D316"' cl0="" href='3D"https://tracking.tldrnewslet=' https:%2f%2fmedium.com%2fperennial-protocol%2fan-intuitive-deri="vation-of-the-perennial-mechanism-58a092e33c62%3Futm_source=3Dtldrcrypto/1/=" ter.com=""></a>"""
#a_tag = a_tag.replace(" ","")

print(a_tag)
# Extraire tous les morceaux d'href
href_parts = re.findall(r"href='(.*?)'", a_tag)

# Concaténer les morceaux
full_href = "".join(href_parts) 

# Décoder les caractères spéciaux
full_href = unquote(full_href)

# Nettoyer le résultat
cleaned_href = full_href.split("=")[1]

print(cleaned_href)
print(full_href)
soup = BeautifulSoup(a_tag, 'html.parser')

a = soup.find('a')
print(a)
a = str(a).replace(" ","")
href = a['href']

print(href)


