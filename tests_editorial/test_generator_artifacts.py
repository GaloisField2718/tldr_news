import json,os,tempfile,time,unittest
from pathlib import Path
from tools.tldr_editorial.artifacts import validate_all
from tools.tldr_editorial.core import EditorialError
from tools.tldr_editorial.generator import generate
from tools.tldr_editorial.openrouter import Result
from tests_editorial.helpers import config,fake_webp,write_generated

class Never:
 def editorial(self,*a):raise AssertionError('network called')
 def image(self,*a):raise AssertionError('network called')
class Live:
 def __init__(self,fail=False):self.editorial_calls=0;self.image_calls=0;self.fail=fail
 def editorial(self,d):
  self.editorial_calls+=1
  if self.fail:raise EditorialError('openrouter_transport_failed')
  ids=[x['candidate_id'] for x in d if x['content_class']=='editorial' and x['summary']]
  p={"lead_candidate_id":ids[0],"front_page":[{"candidate_id":x,"role":"lead" if i==0 else "secondary"} for i,x in enumerate(ids)],"section_order":list(dict.fromkeys(x['sector_slug'] for x in d)),"visual_brief":{"mode":"lead_story","source_candidate_ids":[ids[0]],"central_subject":"Machine","visual_metaphor":"Bridge","composition":"Centered","forbidden_elements":["text"],"alt_text":"An editorial illustration of a machine"}}
  return Result(p,{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2,"cost_usd":.1},'e')
 def image(self,p):self.image_calls+=1;return Result(__import__('base64').b64encode(fake_webp()).decode(),{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2,"cost_usd":.2},'i')
class Storage:
 def __init__(self,base='https://assets.example.workers.dev'):self.calls=0;self.base=base
 def ensure_uploaded(self,*a,**k):self.calls+=1;return True
 def build_public_url(self,key):return self.base+'/'+key
 def verify_object(self,*a,**k):return {}

class GeneratorTests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.g=self.root/'generated';self.o=self.root/'editorial';write_generated(self.g)
 def tearDown(self):self.t.cleanup()
 def test_disabled_has_no_network_and_second_run_noop_mtime(self):
  a=generate(generated=self.g,output=self.o,latest=True,config=config(),client=Never());p=self.o/'2026'/'2026-07-21.json';before=(p.read_bytes(),p.stat().st_mtime_ns);time.sleep(.01);b=generate(generated=self.g,output=self.o,latest=True,config=config(),client=Never())
  self.assertEqual(a['status'],'disabled');self.assertTrue(b['noop']);self.assertEqual(before,(p.read_bytes(),p.stat().st_mtime_ns));self.assertEqual((b['network_calls'],b['r2_calls']),(0,0))
 def test_live_complete_then_no_http_or_r2(self):
  c=Live();s=Storage();a=generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=c,storage=s);self.assertEqual(a['status'],'ai_complete');self.assertEqual((c.editorial_calls,c.image_calls,s.calls),(1,1,1))
  b=generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=Never(),storage=Storage());self.assertTrue(b['noop'])
 def test_failure_persisted_no_minute_retry(self):
  c=Live(fail=True);a=generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=c,storage=Storage());self.assertEqual(a['status'],'deterministic_fallback');self.assertEqual(c.editorial_calls,1)
  b=generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=Never());self.assertTrue(b['noop'])
 def test_changed_issue_model_prompt_change_hash(self):
  a=generate(generated=self.g,output=self.o,latest=True,offline=True,config=config())['editorial_input_hash'];issue=next((self.g/'issues').rglob('*.json'));d=json.loads(issue.read_text());d['sections'][0]['articles'][0]['summary']='changed';issue.write_text(json.dumps(d));b=generate(generated=self.g,output=self.o,latest=True,offline=True,dry_run=True,config=config())['editorial_input_hash'];self.assertNotEqual(a,b)
  c=generate(generated=self.g,output=self.o,latest=True,offline=True,dry_run=True,config=config(editorial_model='other'))['editorial_input_hash'];self.assertNotEqual(b,c)
 def test_manifest_and_consistency(self):
  generate(generated=self.g,output=self.o,latest=True,config=config());m=json.loads((self.o/'manifest.json').read_text());self.assertEqual(m['dates'][0]['file'],'2026/2026-07-21.json');self.assertEqual(validate_all(self.o,self.g),[])
 def test_public_base_change_only_updates_url_without_models(self):
  generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=Live(),storage=Storage())
  result=generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x',r2_public_base_url='https://new.example.workers.dev'),client=Never())
  self.assertTrue(result['public_url_updated']);self.assertEqual(result['network_calls'],0)
 def test_dry_run_no_files(self):
  r=generate(generated=self.g,output=self.o,latest=True,dry_run=True,offline=True,config=config());self.assertTrue(r['dry_run']);self.assertFalse(self.o.exists())
if __name__=='__main__':unittest.main()
