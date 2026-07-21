import copy,unittest
from tools.tldr_editorial.candidates import Candidate
from tools.tldr_editorial.core import EditorialError
from tools.tldr_editorial.plan import fallback,parse_plan_content,validate_plan

def candidates(n=10):
 return [Candidate(f"c{i:03}",f"s{i}:d",f"a{i}","tldr" if i==1 else f"sector-{i}","NEWS",f"Title {i}",f"Summary {i}",f"https://e/{i}","e",3,"editorial",(0,i)) for i in range(1,n+1)]
def valid(n=10):
 count=min(9,n);return {"lead_candidate_id":"c001","front_page":[{"candidate_id":f"c{i:03}","role":"lead" if i==1 else "secondary" if i<6 else "brief"} for i in range(1,count+1)],"section_order":["tldr"],"visual_brief":{"mode":"lead_story","source_candidate_ids":["c001"],"central_subject":"A machine","visual_metaphor":"A bridge","composition":"Centered subject","forbidden_elements":["text"],"alt_text":"An editorial illustration of a machine"}}
class PlanTests(unittest.TestCase):
 def test_valid_nine(self): self.assertEqual(len(validate_plan(valid(),candidates())["front_page"]),9)
 def bad(self,change,code=None):
  p=valid();change(p)
  with self.assertRaises(EditorialError):validate_plan(p,candidates())
 def test_exactly_one_lead(self): self.bad(lambda p:p["front_page"][1].update(role="lead"))
 def test_secondary_max(self): self.bad(lambda p:[x.update(role="secondary") for x in p["front_page"][1:7]])
 def test_duplicate(self): self.bad(lambda p:p["front_page"][1].update(candidate_id="c001"))
 def test_unknown(self): self.bad(lambda p:p["front_page"][1].update(candidate_id="c999"))
 def test_resource_cannot_be_front_page_role_or_visual_source(self):
  for role in ("lead","secondary","brief"):
   cs=candidates();cs[0]=Candidate(**{**cs[0].__dict__,"content_class":"resource"});p=valid();p["front_page"][0]["role"]=role
   if role!="lead":p["front_page"][1]["role"]="lead";p["lead_candidate_id"]="c002";p["visual_brief"]["source_candidate_ids"]=["c002"]
   with self.assertRaises(EditorialError):validate_plan(p,cs)
 def test_sponsor_and_incomplete(self):
  cs=candidates();cs[1]=Candidate(**{**cs[1].__dict__,"content_class":"sponsor"})
  with self.assertRaises(EditorialError):validate_plan(valid(),cs)
  cs=candidates();cs[1]=Candidate(**{**cs[1].__dict__,"summary":""})
  with self.assertRaises(EditorialError):validate_plan(valid(),cs)
 def test_sections(self):
  self.bad(lambda p:p.update(section_order=["missing"]));self.bad(lambda p:p.update(section_order=["tldr","tldr"]))
 def test_visual_selected_and_max(self):
  self.bad(lambda p:p["visual_brief"].update(mode="edition_theme",source_candidate_ids=["c010"]))
  self.bad(lambda p:p["visual_brief"].update(mode="edition_theme",source_candidate_ids=["c001","c002","c003","c004"]))
 def test_oversized_unknown_markup(self):
  self.bad(lambda p:p["visual_brief"].update(composition="x"*501));self.bad(lambda p:p.update(extra=1));self.bad(lambda p:p["visual_brief"].update(alt_text="<b>art</b>"))
 def test_prose_outside_json(self):
  with self.assertRaises(EditorialError):parse_plan_content('Here: {"x":1}')
 def test_fallback_deterministic_tldr_distinct_max(self):
  cs=candidates(12);a=fallback(cs);self.assertEqual(a,fallback(cs));self.assertEqual(a["lead_candidate_id"],"c001");self.assertEqual(len(a["front_page"]),9);self.assertEqual(sum(x["role"]=="secondary" for x in a["front_page"]),4)
 def test_fallback_small_and_none(self):
  self.assertEqual(len(fallback(candidates(2))["front_page"]),2);self.assertEqual(fallback([])["front_page"],[])
 def test_fallback_no_sponsor(self):
  cs=candidates(3);cs[0]=Candidate(**{**cs[0].__dict__,"content_class":"sponsor"});self.assertNotEqual(fallback(cs)["lead_candidate_id"],"c001")
if __name__=='__main__':unittest.main()
