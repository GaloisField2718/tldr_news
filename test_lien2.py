import re

a_tag = """<a 000="" cl0="" href='3D"https://tracking.tldrnewslet=' https:%2f%2fdataanddesign.substack.com%2fp%2fimprove-ux-researc="h-presentations/1/0100018a4b7b56c9-b14f2b7c-9193-4860-9f6f-87edc1c70e90-000=" p5hnx1ysuf4felnzrhg0qcnufv6wbrpspal7rmy3lw8='3D316"' ter.com="">"""

a_tag = a_tag.replace(" ","")
# Récupérer tout le contenu entre guillemets simples  
#full_link = re.findall(r"'(.+?)'", a_tag, re.DOTALL).group(1)
# Trouver tous les href
hrefs = re.findall(r"href='(.+?)'", a_tag)

# Concaténer les hrefs 
full_link = "".join(hrefs)

# Décoder les caractères spéciaux
from urllib.parse import unquote
full_link = unquote(full_link)

print(full_link)

# Afficher comme lien cliquable
print(f"<a href='{full_link}'>{full_link}</a>")
