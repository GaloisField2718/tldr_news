from __future__ import annotations
import copy,json,tempfile,unittest
from dataclasses import replace
from pathlib import Path
from tools.tldr_editorial.artifacts import validate_all,write_artifact
from tools.tldr_editorial.candidates import load_date,shortlist
from tools.tldr_editorial.core import image_configuration
from tools.tldr_editorial.generator import generate
from tools.tldr_editorial.core import EditorialError
from tools.tldr_editorial.openrouter import Result
from tools.tldr_editorial.illustration_hash import illustration_input_hash
from tools.tldr_editorial.illustration_prompts import BASELINE_PREAMBLE,BASELINE_PROFILE,get_profile
from tools.tldr_editorial.image import assemble_prompt
from tools.tldr_editorial.plan import validate_plan
from tests_editorial.helpers import config,write_generated
from tests_editorial.test_generator_artifacts import Live,Storage

class ProductionV2MatrixTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.g=self.root/'generated';self.o=self.root/'editorial';write_generated(self.g);self.candidates=shortlist(load_date(self.g,'2026-07-21'),60);self.source=self.candidates[0];self.profile=get_profile('production-v2')
  self.brief={'schema_version':'2.0.0','mode':'lead_story','source_candidate_ids':[self.source.candidate_id],'editorial_idea':'A machine crosses a constrained bridge.','central_subject':'Machine','visual_relationship':'The machine moves across a bridge.','composition':'Machine at left, bridge leading right, clear negative space.','literal_elements':['machine','bridge'],'abstraction_level':'medium','forbidden_elements':['text','logos'],'failure_modes':['generic product render','diagram labels'],'alt_text':'A machine crossing a bridge'}
  self.facts=[{'issue_id':self.source.issue_id,'article_id':self.source.article_id,'title':self.source.title,'summary':self.source.summary}];self.cfg=image_configuration(12_000_000,20_000_000,2_000_000)
 def tearDown(self):self.t.cleanup()
 def h(self,brief=None,facts=None,model='image-model',version='2.0.0',cfg=None,profile=None):return illustration_input_hash(brief=brief or self.brief,sources=facts or self.facts,image_model=model,prompt_version=version,image_config=cfg or self.cfg,profile=profile or self.profile)
 def test_hash_semantic_sensitivity_matrix(self):
  base=self.h();cases={
   'profile_id':lambda:(None,None,None,None,replace(self.profile,profile_id='other')),
   'profile_content':lambda:(None,None,None,None,replace(self.profile,preamble=self.profile.preamble+' changed')),
   'prompt_version':lambda:(None,None,None,None,replace(self.profile,schema_version='2.0.1')),
   'brief_schema':lambda:({**self.brief,'schema_version':'2.0.1'},None,None,None,None),
   'editorial_idea':lambda:({**self.brief,'editorial_idea':'Changed'},None,None,None,None),'central_subject':lambda:({**self.brief,'central_subject':'Changed'},None,None,None,None),'visual_relationship':lambda:({**self.brief,'visual_relationship':'Changed'},None,None,None,None),'composition':lambda:({**self.brief,'composition':'Changed'},None,None,None,None),'literal_item':lambda:({**self.brief,'literal_elements':['changed','bridge']},None,None,None,None),'literal_append':lambda:({**self.brief,'literal_elements':['machine','bridge','road']},None,None,None,None),'literal_order':lambda:({**self.brief,'literal_elements':['bridge','machine']},None,None,None,None),'abstraction':lambda:({**self.brief,'abstraction_level':'high'},None,None,None,None),'forbidden':lambda:({**self.brief,'forbidden_elements':['words','logos']},None,None,None,None),'failure_modes':lambda:({**self.brief,'failure_modes':['stock CGI']},None,None,None,None),'source_issue':lambda:(None,[{**self.facts[0],'issue_id':'other:2026-07-21'}],None,None,None),'source_article':lambda:(None,[{**self.facts[0],'article_id':'other:a01'}],None,None,None),'source_title':lambda:(None,[{**self.facts[0],'title':'Changed'}],None,None,None),'source_summary':lambda:(None,[{**self.facts[0],'summary':'Changed'}],None,None,None),'image_model':lambda:(None,None,'other-model',None,None),'image_width':lambda:(None,None,None,{**self.cfg,'resolution':'2K'},None),'image_height':lambda:(None,None,None,{**self.cfg,'aspect_ratio':'4:3'},None),'image_format':lambda:(None,None,None,{**self.cfg,'conversion':{**self.cfg['conversion'],'format':'png'}},None)}
  for name,mutation in cases.items():
   with self.subTest(case=name):
    brief,facts,model,cfg,profile=mutation();self.assertNotEqual(base,self.h(brief,facts,model or 'image-model',cfg=cfg,profile=profile))
 def test_hash_nonsemantic_insensitivity_matrix(self):
  base=self.h();artifact={'generated_at':'a','generation':{'editorial_request_id':'e','illustration_request_id':'i','failure_code':None},'usage':{'editorial':{},'illustration':{},'total_cost_usd':0},'illustration':{'public_url':'u','object_key':'k','sha256':'s','width':1,'height':1,'bytes':1},'status':'ai_complete','git':{'commit':'a'},'manifest':[2,1]}
  mutations=['generated_at','editorial_request_id','illustration_request_id','editorial_usage','illustration_usage','cost','public_url','object_key','image_sha','image_dimensions','image_bytes','status','failure_code','git_metadata','manifest_order']
  for name in mutations:
   with self.subTest(case=name):
    changed=copy.deepcopy(artifact);changed['generated_at']=name;self.assertEqual(base,self.h())
 def test_duplicate_arrays_rejected_before_hashing(self):
  ids=[c.candidate_id for c in self.candidates];plan={'lead_candidate_id':ids[0],'front_page':[{'candidate_id':x,'role':'lead' if i==0 else 'secondary'} for i,x in enumerate(ids)],'section_order':list(dict.fromkeys(c.sector_slug for c in self.candidates)),'visual_brief':{**self.brief,'forbidden_elements':['text','text']}}
  with self.assertRaisesRegex(Exception,'plan_forbidden_elements'):validate_plan(plan,self.candidates)
 def test_exact_sectioned_prompt_and_legacy_identity(self):
  prompt=assemble_prompt(self.brief,[self.source],self.profile);headings=['Rendering style:','Exact source facts:','Editorial idea:','Central subject:','Visual relationship:','Composition:','Permitted literal elements:','Abstraction level:','Story-specific forbidden elements:','Likely failure modes to avoid:','Global factual restrictions:'];self.assertEqual([prompt.index(x) for x in headings],sorted(prompt.index(x) for x in headings));self.assertIn(self.source.title,prompt);self.assertIn(self.source.summary,prompt);self.assertIn('Do not render any words, letters, numbers, labels, captions, annotations, signage, diagrams with text, logos, watermarks, or pseudo-writing anywhere in the image.',prompt);self.assertIn('If the concept cannot be represented without visible text, represent the relationship through shape, scale, spacing, direction, grouping, interruption, containment, or contrast instead.',prompt);self.assertNotIn('\n\n\n',prompt);self.assertEqual(BASELINE_PROFILE.preamble,BASELINE_PREAMBLE);self.assertTrue(all(x not in self.profile.preamble.lower() for x in ('amd','sandbox','hyundai','worker automation')))
 def _v2(self):
  c=Live();s=Storage();generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=c,storage=s);return json.loads((self.o/'2026/2026-07-21.json').read_text())
 def test_artifact_valid_and_invalid_matrix(self):
  base=self._v2();self.assertEqual(validate_all(self.o,self.g),[])
  cases={
   'missing_profile':lambda a:a.pop('illustration_profile_id'),'missing_schema_metadata':lambda a:a.pop('visual_brief_schema_version'),'missing_both':lambda a:(a.pop('illustration_profile_id'),a.pop('visual_brief_schema_version')),'unknown_profile':lambda a:a.update(illustration_profile_id='unknown'),'unknown_schema':lambda a:a.update(visual_brief_schema_version='9.0.0'),'v1_brief':lambda a:a['plan'].__setitem__('visual_brief',{'mode':'lead_story','sources':a['plan']['visual_brief']['sources'],'central_subject':'x','visual_metaphor':'x','composition':'x','forbidden_elements':[],'alt_text':'x'}),'historical_prompt':lambda a:a['prompt_versions'].__setitem__('illustration','1.0.0'),'incomplete_brief':lambda a:a['plan']['visual_brief'].pop('editorial_idea'),'foreign_source':lambda a:a['plan']['visual_brief'].__setitem__('sources',[{'issue_id':'foreign','article_id':'foreign'}]),'candidate_id_leak':lambda a:a['plan']['visual_brief'].__setitem__('source_candidate_ids',['c001']),'ready_missing_prompt_hash':lambda a:a['generation'].__setitem__('final_prompt_sha256',None),'ready_missing_input_hash':lambda a:a.__setitem__('illustration_input_hash',None)}
  for name,mutation in cases.items():
   with self.subTest(case=name):
    a=copy.deepcopy(base);mutation(a);write_artifact(self.o,'2026-07-21',a);errors=validate_all(self.o,self.g);self.assertTrue(errors,name)
    write_artifact(self.o,'2026-07-21',base)
 def test_committed_historical_artifact_is_read_only_and_valid(self):
  repo=Path(__file__).resolve().parents[1];path=repo/'generated/editorial/2026/2026-07-21.json';before=path.read_bytes();self.assertEqual(validate_all(repo/'generated/editorial',repo/'generated'),[]);self.assertEqual(path.read_bytes(),before);a=json.loads(before);self.assertEqual(a['prompt_versions']['illustration'],'1.0.0');self.assertNotIn('illustration_profile_id',a);self.assertNotIn('visual_brief_schema_version',a)
 def test_invalid_editorial_refresh_matrix_never_reaches_image_or_r2(self):
  mutations={'missing_editorial_idea':lambda v:v.pop('editorial_idea'),'missing_central_subject':lambda v:v.pop('central_subject'),'missing_relationship':lambda v:v.pop('visual_relationship'),'missing_composition':lambda v:v.pop('composition'),'missing_literals':lambda v:v.pop('literal_elements'),'invalid_abstraction':lambda v:v.__setitem__('abstraction_level','extreme'),'duplicate_forbidden':lambda v:v.__setitem__('forbidden_elements',['text','text']),'oversized_failures':lambda v:v.__setitem__('failure_modes',['x']*13),'extra_field':lambda v:v.__setitem__('extra','x'),'foreign_reference':lambda v:v.__setitem__('source_candidate_ids',['c999']),'malformed_reference':lambda v:v.__setitem__('source_candidate_ids','c001'),'whitespace':lambda v:v.__setitem__('editorial_idea','   ')}
  for name,mutation in mutations.items():
   with self.subTest(case=name):
    root=self.root/name;g=root/'generated';o=root/'editorial';write_generated(g);generate(generated=g,output=o,latest=True,config=config());base=Live();original=base.editorial
    def editorial(d,original=original,mutation=mutation):
     result=original(d);value=copy.deepcopy(result.value);mutation(value['visual_brief']);return Result(value,result.usage,result.request_id)
    base.editorial=editorial;storage=Storage();result=generate(generated=g,output=o,latest=True,config=config(enabled=True,api_key='x'),client=base,storage=storage);self.assertEqual((base.editorial_calls,base.image_calls,storage.calls),(1,0,0));self.assertNotEqual(result['status'],'ai_complete');artifact=json.loads((o/'2026/2026-07-21.json').read_text());self.assertNotEqual(artifact['illustration']['status'],'ready')
 def test_compatible_v2_retry_reuses_plan_and_historical_retry_refreshes(self):
  class ImageFail(Live):
   def image(self,p):self.image_calls+=1;raise EditorialError('synthetic_image_failure')
  failed=ImageFail();generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=failed,storage=Storage());retry=Live();result=generate(generated=self.g,output=self.o,latest=True,retry_image=True,config=config(enabled=True,api_key='x'),client=retry,storage=Storage());self.assertEqual((retry.editorial_calls,retry.image_calls),(0,1));self.assertEqual(result['status'],'ai_complete');a=json.loads((self.o/'2026/2026-07-21.json').read_text());self.assertEqual(a['illustration_profile_id'],'production-v2')
  other=self.root/'historical';g=other/'generated';o=other/'editorial';write_generated(g);generate(generated=g,output=o,latest=True,config=config());refresh=Live();generate(generated=g,output=o,latest=True,retry_image=True,config=config(enabled=True,api_key='x'),client=refresh,storage=Storage());self.assertEqual((refresh.editorial_calls,refresh.image_calls),(1,1))
 def test_historical_to_v2_migration_then_zero_call_noop(self):
  generate(generated=self.g,output=self.o,latest=True,config=config());old=json.loads((self.o/'2026/2026-07-21.json').read_text());self.assertNotIn('illustration_profile_id',old);client=Live();storage=Storage();first=generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=client,storage=storage);self.assertEqual((client.editorial_calls,client.image_calls,storage.calls),(1,1,1));new=json.loads((self.o/'2026/2026-07-21.json').read_text());self.assertEqual((new['illustration_profile_id'],new['visual_brief_schema_version'],new['prompt_versions']['illustration']),('production-v2','2.0.0','2.0.0'));before=(self.o/'2026/2026-07-21.json').read_bytes();second=generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=type('Never',(object,),{'editorial':lambda *a:(_ for _ in ()).throw(AssertionError()),'image':lambda *a:(_ for _ in ()).throw(AssertionError())})());self.assertTrue(second['noop']);self.assertEqual((second['network_calls'],second['r2_calls'],second['written']),(0,0,False));self.assertEqual((self.o/'2026/2026-07-21.json').read_bytes(),before)

if __name__=='__main__':unittest.main()
