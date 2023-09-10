# 
#       link.py
# 
# Link management for main script
#

import re
from urllib.parse import unquote


def extract_url(a_tag):

  # Example a_tag
  # a_tag = """<a 0100018a74e6e0a2-61d0c822-f291-4508-b0a2-aaf448f00772-000000="" 1="" cl0="" com="" href='3D"https://tracking.tldrnewsletter.=' https:%2f%2fmarkomih.github.io%2fresfields%2f%3futm_source="3Dtldrai=" iis8idx6j3r='9f1hOP46BLg-INnMYvPrmYg7hokgYtFI=3D317"'>"""

  a_tag_text = a_tag.get_text()

  pattern = r"https://tracking\.tldrnewsletter\.=(.+?)(?=utm_source)"
  match = re.search(pattern, a_tag_text)

  try : 

    url = unquote(match.group(1))
    print("url clean : ", url)
    return url
  
  except AttributeError :
    print("match : ", match)
    return "no_url"

a_tag ="""<a 0100018a74e6e0a2-61d0c822-f291-4508-b0a2-aaf448f00772-000000="" cl0="" com="" href='3D"https://tracking.tldrnewsletter.=' https:%2f%2farxiv.org%2fabs%2f2309.03079v1%3futm_source="3Dtldrai/1/=" s-ysjwej6ah_ty='Asbyaes8Oc4h6MOt0B2-hopNuCeEk=3D317"'> """

#extract_url(a_tag)


	
