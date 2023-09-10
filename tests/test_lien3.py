import re
from urllib.parse import unquote
from bs4 import BeautifulSoup

a_tag = """<a 422-48d9-975c-b86c909f33ae-000000="" agnipekk2z4vc2uy3_5uhfamw_t4ossoui5z1rvxs='xY=3D284"' cl0="" com="" href='3D"https://tracking.tldrnewsletter.=' https:%2f%2fthedefiant.io%2fcentrifuge-quietly-sets-pace-in-real-wo="rld-assets-race%3Futm_source=3Dtldrnewsletter/1/01000185debcd6b9-b0d18f35-4="></a>"""
#a_tag = a_tag.replace(" ","")

print(a_tag)
# Extraire tout href
href_part = re.search(r"href=.*?>", a_tag)

print("href_part : ", href_part)


# Get the matched string 
matched = href_part.group(0) 
matched = matched.replace("""href='3D"https://tracking.tldrnewsletter.=' """, "")
matched = matched.replace(">","")
print("matched : ", matched)
full_href = unquote(matched)
full_href = full_href.replace(" ","")
print("full href : ", full_href)

test_lien = unquote(""""https://tracking.tldrnewsletter.='https:%2f%2fthedefiant.io%2fcentrifuge-quietly-sets-pace-in-real-wo="rld-assets-race%3Futm_source=3Dtldrnewsletter/1/01000185debcd6b9-b0d18f35-4=""""")
print(test_lien)
