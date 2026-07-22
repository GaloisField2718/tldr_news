from __future__ import annotations
import copy,json,tempfile,unittest
from pathlib import Path
from tools.tldr_editorial.core import EditorialError
from tools.tldr_editorial.generator import generate
from tools.tldr_editorial.openrouter import OpenRouterClient,PLAN_SCHEMA,ProviderHTTPError,validate_strict_json_schema
from tests_editorial.helpers import config,write_generated
from tests_editorial.test_clients_image_storage import Response
from tests_editorial.test_generator_artifacts import Live,Storage

class NeverStorage:
 def __getattr__(self,name):return lambda *a,**k:(_ for _ in ()).throw(AssertionError('R2 called'))
class HTTP400Client:
 def __init__(self):self.editorial_calls=0;self.image_calls=0
 def editorial(self,d):self.editorial_calls+=1;raise ProviderHTTPError(400,'invalid_json_schema','Unsupported keyword: const','req-safe',False)
 def image(self,p):self.image_calls+=1;raise AssertionError('image called')

class MigrationFailureAtomicityTests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.g=self.root/'generated';self.o=self.root/'editorial';write_generated(self.g)
 def tearDown(self):self.t.cleanup()
 def historical(self):generate(generated=self.g,output=self.o,latest=True,config=config());return (self.o/'2026/2026-07-21.json').read_bytes(),(self.o/'manifest.json').read_bytes()
 def test_structured_http_400_is_sanitized_and_counted_at_client_boundary(self):
  response=Response({'error':{'code':'invalid_json_schema','message':'Unsupported keyword: const   in response schema'}},{'x-request-id':'req-123'});response.status_code=400;attempts=[]
  def post(url,**kw):attempts.append(kw);return response
  client=OpenRouterClient(config(api_key='private'),post)
  with self.assertRaises(ProviderHTTPError) as caught:client.editorial([])
  e=caught.exception;self.assertEqual((len(attempts),e.status,e.provider_code,e.provider_message,e.request_id,e.retryable),(1,400,'invalid_json_schema','Unsupported keyword: const in response schema','req-123',False));self.assertNotIn('private',str(e))
 def test_corrected_exact_request_schema_is_strict_serializable_and_const_free(self):
  validate_strict_json_schema(PLAN_SCHEMA);encoded=json.dumps(PLAN_SCHEMA,sort_keys=True);self.assertNotIn('"const"',encoded);self.assertEqual(PLAN_SCHEMA['properties']['visual_brief']['properties']['schema_version']['enum'],['2.0.0'])
  broken=copy.deepcopy(PLAN_SCHEMA);broken['properties']['visual_brief']['properties']['schema_version']={'const':'2.0.0'}
  with self.assertRaisesRegex(EditorialError,'editorial_schema_unsupported'):validate_strict_json_schema(broken)
 def test_existing_published_artifact_survives_editorial_http_400_byte_for_byte(self):
  before_artifact,before_manifest=self.historical();client=HTTP400Client();result=generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=client,storage=NeverStorage());self.assertEqual((client.editorial_calls,client.image_calls),(1,0));self.assertEqual((result['editorial_attempts'],result['editorial_successful_responses'],result['image_attempts'],result['r2_calls'],result['written']),(1,0,0,0,False));self.assertTrue(result['published_artifact_preserved']);self.assertEqual(result['provider_error']['provider_code'],'invalid_json_schema');self.assertEqual((self.o/'2026/2026-07-21.json').read_bytes(),before_artifact);self.assertEqual((self.o/'manifest.json').read_bytes(),before_manifest)
 def test_existing_artifact_survives_image_failure(self):
  before_artifact,before_manifest=self.historical()
  class ImageFail(Live):
   def image(self,p):self.image_calls+=1;raise EditorialError('synthetic_image_failure')
  client=ImageFail();result=generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=client,storage=NeverStorage());self.assertEqual((client.editorial_calls,client.image_calls,result['written']),(1,1,False));self.assertEqual((self.o/'2026/2026-07-21.json').read_bytes(),before_artifact);self.assertEqual((self.o/'manifest.json').read_bytes(),before_manifest)
 def test_existing_artifact_survives_upload_failure(self):
  before_artifact,before_manifest=self.historical()
  class FailStorage(Storage):
   def ensure_uploaded(self,*a,**k):self.calls+=1;raise EditorialError('r2_upload_failed')
  client=Live();storage=FailStorage();result=generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=client,storage=storage);self.assertEqual((client.editorial_calls,client.image_calls,storage.calls,result['written']),(1,1,1,False));self.assertEqual((self.o/'2026/2026-07-21.json').read_bytes(),before_artifact);self.assertEqual((self.o/'manifest.json').read_bytes(),before_manifest)
 def test_missing_edition_keeps_deterministic_fallback_behavior(self):
  client=HTTP400Client();result=generate(generated=self.g,output=self.o,latest=True,config=config(enabled=True,api_key='x'),client=client,storage=NeverStorage());self.assertEqual(result['status'],'deterministic_fallback');self.assertTrue(result['written']);self.assertTrue((self.o/'2026/2026-07-21.json').exists())

if __name__=='__main__':unittest.main()
