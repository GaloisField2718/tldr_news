import re
from urllib.parse import unquote

html = """<a 000="" cl0="" href='3D"https://tracking.tldrnewslet=' https:%2f%2fdataanddesign.substack.com%2fp%2fimprove-ux-researc="h-presentations/1/0100018a4b7b56c9-b14f2b7c-9193-4860-9f6f-87edc1c70e90-000=" p5hnx1ysuf4felnzrhg0qcnufv6wbrpspal7rmy3lw8='3D316"' ter.com="">"""
html = html.replace(" ","").replace("\n","")

# Trouver tous les href 
hrefs = re.findall(r"href='(.*?)'", html)

# Concaténer les parties
full_link = "".join(hrefs)

full_link= unquote(full_link)
# Afficher comme lien cliquable
print(f"[Lien]({full_link})")
