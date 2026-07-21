import json,tempfile,unittest
from pathlib import Path
from tools.tldr_editorial.candidates import canonicalize_url,load_date,shortlist,sector_key
from tests_editorial.helpers import article,write_generated

class CandidateTests(unittest.TestCase):
 def setUp(self): self.t=tempfile.TemporaryDirectory();self.g=Path(self.t.name)/"generated"
 def tearDown(self): self.t.cleanup()
 def test_grouped_date_and_latest_only(self):
  write_generated(self.g,"2026-07-20"); write_generated(self.g,"2026-07-21")
  # helper replaces manifest, proving historical files are not input
  self.assertTrue(all(c.issue_id.endswith("2026-07-21") for c in load_date(self.g,"2026-07-21")))
 def test_empty_title_excluded_and_empty_summary_ineligible(self):
  write_generated(self.g,sectors={"tldr":[article("x",title=""),article("y",summary="")]})
  c=load_date(self.g,"2026-07-21");self.assertEqual([x.article_id for x in c],["y"]);self.assertFalse(c[0].front_page_eligible)
 def test_sponsor_and_resource_not_front_page(self):
  write_generated(self.g,sectors={"tldr":[article("s",sponsor=True),article("r",content_type="resource")]})
  c=load_date(self.g,"2026-07-21");self.assertEqual([x.content_class for x in c],["sponsor","resource"]);self.assertFalse(any(x.front_page_eligible for x in c))
 def test_same_pair_merged_sponsor_wins(self):
  write_generated(self.g,sectors={"tldr":[article("same",order=1),article("same",sponsor=True,order=2)]})
  c=load_date(self.g,"2026-07-21");self.assertEqual(len(c),1);self.assertEqual(c[0].content_class,"sponsor")
 def test_tracking_canonicalization(self):
  self.assertEqual(canonicalize_url("HTTPS://Example.COM/a?z=2&utm_source=x&a=1#f"),"https://example.com/a?a=1&z=2")
 def test_url_dedup_scoped_by_class(self):
  u="https://e.test/a?utm_campaign=x"
  write_generated(self.g,sectors={"tldr":[article("a",url=u),article("b",url="https://e.test/a",content_type="resource"),article("c",url="https://e.test/a?utm_source=z")]})
  c=load_date(self.g,"2026-07-21");self.assertEqual(len(c),2);self.assertEqual({x.content_class for x in c},{"editorial","resource"})
 def test_sector_order_known_then_unknown(self):
  self.assertLess(sector_key("tldr"),sector_key("tldr-ai"));self.assertLess(sector_key("tldr-marketing"),sector_key("aaa"));self.assertLess(sector_key("aaa"),sector_key("zzz"))
 def test_balanced_cap_and_ids_deterministic(self):
  sectors={"tldr":[article(f"t{i}",title=f"T{i}") for i in range(5)],"tldr-ai":[article(f"a{i}",title=f"A{i}") for i in range(5)],"tldr-design":[article(f"d{i}",title=f"D{i}") for i in range(5)]}
  write_generated(self.g,sectors=sectors); a=shortlist(load_date(self.g,"2026-07-21"),6);b=shortlist(load_date(self.g,"2026-07-21"),6)
  self.assertEqual([x.candidate_id for x in a],[f"c{i:03}" for i in range(1,7)]);self.assertEqual(a,b);self.assertEqual({x.sector_slug for x in a},{"tldr","tldr-ai","tldr-design"})
 def test_failed_issue_excluded(self):
  write_generated(self.g);m=json.loads((self.g/"manifest.json").read_text());m["issues"][0]["parse_status"]="failed";(self.g/"manifest.json").write_text(json.dumps(m))
  self.assertTrue(all(x.sector_slug!="tldr" for x in load_date(self.g,"2026-07-21")))

if __name__=='__main__': unittest.main()
