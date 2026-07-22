from __future__ import annotations
import copy,json,tempfile,unittest
from pathlib import Path
from tools.tldr_editorial.artifacts import validate_all
from tools.tldr_editorial.candidates import load_date,shortlist
from tools.tldr_editorial.core import EditorialError
from tools.tldr_editorial.generator import assess_active_illustration_compatibility,generate
from tests_editorial.helpers import config,write_generated
from tests_editorial.test_generator_artifacts import Live,Storage

class ProductionV2StalenessTests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.g=self.root/'generated';self.o=self.root/'editorial';write_generated(self.g);self.candidates=shortlist(load_date(self.g,'2026-07-21'),60)
 def tearDown(self):self.t.cleanup()
 def historical(self):generate(generated=self.g,output=self.o,latest=True,config=config());return json.loads((self.o/'2026/2026-07-21.json').read_text())
 def v2(self):generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=Live(),storage=Storage());return json.loads((self.o/'2026/2026-07-21.json').read_text())
 def test_exact_committed_historical_preflight_requires_migration_without_calls_or_writes(self):
  repo=Path(__file__).resolve().parents[1];artifact=repo/'generated/editorial/2026/2026-07-21.json';before=artifact.read_bytes();self.assertEqual(validate_all(repo/'generated/editorial',repo/'generated'),[])
  result=generate(generated=repo/'generated',output=repo/'generated/editorial',date='2026-07-21',offline=True,dry_run=True,config=config(enabled=True,api_key='configured'))
  expected={'historical_artifact_valid':True,'active_contract_compatible':False,'illustration_stale':True,'editorial_refresh_required':True,'image_regeneration_required':True,'expected_editorial_calls':1,'expected_image_calls':1,'expected_r2_uploads':1,'noop':False,'network_calls':0,'r2_calls':0,'written':False};self.assertEqual({k:result[k] for k in expected},expected);self.assertIn('prompt_version_mismatch',result['staleness_reasons']);self.assertEqual(artifact.read_bytes(),before)
 def test_matching_v2_is_compatible_and_second_run_noop(self):
  a=self.v2();assessment=assess_active_illustration_compatibility(a,self.candidates,config(enabled=True,api_key='x'));self.assertTrue(assessment['active_contract_compatible']);self.assertFalse(assessment['illustration_stale']);before=(self.o/'2026/2026-07-21.json').read_bytes();r=generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=object());self.assertTrue(r['noop']);self.assertEqual((r['network_calls'],r['r2_calls'],r['written']),(0,0,False));self.assertEqual((self.o/'2026/2026-07-21.json').read_bytes(),before)
 def test_historical_v1_matches_a_genuine_active_v1_contract(self):
  a=self.historical();x=assess_active_illustration_compatibility(a,self.candidates,config(),active_prompt_version='1.0.0',active_profile_id=None,active_brief_schema_version=None);self.assertTrue(x['active_contract_compatible']);self.assertFalse(x['illustration_stale'])
 def test_failed_v2_image_keeps_compatible_brief_without_editorial_refresh(self):
  class Fail(Live):
   def image(self,p):self.image_calls+=1;raise EditorialError('synthetic')
  generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=Fail(),storage=Storage());a=json.loads((self.o/'2026/2026-07-21.json').read_text());x=assess_active_illustration_compatibility(a,self.candidates,config(enabled=True,api_key='x'));self.assertTrue(x['active_contract_compatible']);self.assertFalse(x['editorial_refresh_required']);self.assertTrue(x['image_regeneration_required'])
 def test_compatibility_reason_matrix_and_nonsemantic_metadata(self):
  base=self.v2();cases={'profile':['illustration_profile_id','other','illustration_profile_mismatch'],'schema_metadata':['visual_brief_schema_version','1.0.0','visual_brief_schema_mismatch'],'prompt':['prompt_versions.illustration','1.0.0','prompt_version_mismatch'],'brief_schema':['plan.visual_brief.schema_version','1.0.0','incompatible_visual_brief']}
  for name,(path,value,reason) in cases.items():
   with self.subTest(case=name):
    a=copy.deepcopy(base);target=a;parts=path.split('.')
    for p in parts[:-1]:target=target[p]
    target[parts[-1]]=value;x=assess_active_illustration_compatibility(a,self.candidates,config(enabled=True,api_key='x'));self.assertFalse(x['active_contract_compatible']);self.assertIn(reason,x['staleness_reasons'])
  a=copy.deepcopy(base);a['generated_at']='changed';a['usage']['total_cost_usd']=999;x=assess_active_illustration_compatibility(a,self.candidates,config(enabled=True,api_key='x'));self.assertTrue(x['active_contract_compatible'])
 def test_corrupt_historical_hash_fails_before_any_call(self):
  self.historical();p=self.o/'2026/2026-07-21.json';a=json.loads(p.read_text());a['illustration_input_hash']='sha256:'+'0'*64
  from tools.tldr_editorial.artifacts import write_artifact
  write_artifact(self.o,'2026-07-21',a)
  class Never:
   def editorial(self,*a):raise AssertionError('called')
   def image(self,*a):raise AssertionError('called')
  with self.assertRaisesRegex(EditorialError,'existing_artifact_invalid'):generate(generated=self.g,output=self.o,latest=True,dry_run=True,config=config(enabled=True,api_key='x'),client=Never())

if __name__=='__main__':unittest.main()
