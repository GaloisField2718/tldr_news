import base64,tempfile,unittest
from pathlib import Path
from tools.tldr_editorial.core import EditorialError,object_key
from tools.tldr_editorial.image import decode_image,validate_image
from tools.tldr_editorial.openrouter import OpenRouterClient
from tools.tldr_editorial.r2_storage import R2Storage
from tests_editorial.helpers import config,fake_webp

class Response:
 status_code=200
 def __init__(self,doc):self.doc=doc
 def json(self):return self.doc
class ClientTests(unittest.TestCase):
 def test_editorial_request_strict_fixed_host_timeout_usage(self):
  seen={};plan={"lead_candidate_id":"c001","front_page":[],"section_order":[],"visual_brief":{"mode":"none","source_candidate_ids":[],"central_subject":"","visual_metaphor":"","composition":"","forbidden_elements":[],"alt_text":""}}
  def post(url,**kw):seen.update(url=url,**kw);return Response({"id":"req","choices":[{"message":{"content":__import__('json').dumps(plan)}}],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5,"cost":.01}})
  r=OpenRouterClient(config(api_key="private"),post).editorial([]);self.assertEqual(seen["url"],"https://openrouter.ai/api/v1/chat/completions");self.assertEqual(seen["timeout"],90);self.assertTrue(seen["json"]["response_format"]["json_schema"]["strict"]);self.assertTrue(seen["json"]["provider"]["require_parameters"]);self.assertEqual(r.usage["cost_usd"],.01)
 def test_malformed_missing_choices_sanitized_http(self):
  with self.assertRaises(EditorialError):OpenRouterClient(config(api_key="x"),lambda *a,**k:Response({})).editorial([])
  r=Response({"secret":"must not appear"});r.status_code=500
  with self.assertRaisesRegex(EditorialError,"openrouter_http_500"):OpenRouterClient(config(api_key="x"),lambda *a,**k:r).editorial([])
 def test_image_exactly_one_and_options(self):
  seen={};data=base64.b64encode(fake_webp()).decode()
  def post(url,**kw):seen.update(kw);return Response({"choices":[{"message":{"images":[{"b64_json":data}]}}]})
  r=OpenRouterClient(config(api_key="x"),post).image("prompt");self.assertEqual(r.value,data);self.assertEqual(seen["json"]["n"],1);self.assertEqual(seen["json"]["image_config"]["output_format"],"webp")

class ImageTests(unittest.TestCase):
 def test_decode_validate_dimensions_checksum(self):
  d=fake_webp();raw,media=decode_image("data:image/webp;base64,"+base64.b64encode(d).decode());im=validate_image(raw,media,2000000);self.assertEqual((im.width,im.height),(600,400));self.assertTrue(im.sha256.startswith("sha256:"))
 def test_invalid_base64_empty_nonwebp_malformed_oversize_aspect(self):
  for fn in [lambda:decode_image("!!!"),lambda:validate_image(b"","image/webp",10),lambda:validate_image(fake_webp(),"image/png",1000),lambda:validate_image(b"RIFFx","image/webp",1000),lambda:validate_image(fake_webp(),"image/webp",5),lambda:validate_image(fake_webp(600,600),"image/webp",1000)]:
   with self.assertRaises(EditorialError):fn()

class S3:
 def __init__(self,head=None):self.head=head;self.calls=[]
 def head_object(self,**kw):
  self.calls.append(("head",kw))
  if self.head is None:
   e=Exception();e.response={"Error":{"Code":"404"}};raise e
  return self.head
 def upload_file(self,*args,**kw):self.calls.append(("upload",args,kw));self.head={"ContentLength":Path(args[0]).stat().st_size,"ContentType":"image/webp","Metadata":kw["ExtraArgs"]["Metadata"]}
class R2Tests(unittest.TestCase):
 def test_endpoint_key_and_url(self):
  c=config();self.assertEqual(c.r2_endpoint,"https://acct.r2.cloudflarestorage.com");key=object_key("2026-07-21","sha256:"+"a"*64);self.assertEqual(R2Storage(c,S3()).build_public_url(key),"https://assets.example.workers.dev/"+key)
 def test_upload_metadata_and_verify(self):
  data=fake_webp();sha="sha256:"+__import__('hashlib').sha256(data).hexdigest();key=object_key("2026-07-21",sha);s3=S3();r=R2Storage(config(),s3)
  with tempfile.NamedTemporaryFile() as f:f.write(data);f.flush();self.assertTrue(r.ensure_uploaded(Path(f.name),key,size=len(data),sha256=sha,width=600,height=400,date="2026-07-21"))
  upload=[x for x in s3.calls if x[0]=="upload"][0];extra=upload[2]["ExtraArgs"];self.assertEqual(extra["ContentType"],"image/webp");self.assertIn("immutable",extra["CacheControl"]);self.assertEqual(extra["Metadata"]["sha256"],sha[7:])
 def test_existing_reused_and_mismatch_rejected(self):
  sha="sha256:"+"a"*64;key=object_key("2026-07-21",sha);head={"ContentLength":12,"ContentType":"image/webp","Metadata":{"sha256":"a"*64}};r=R2Storage(config(),S3(head))
  with tempfile.NamedTemporaryFile() as f:self.assertFalse(r.ensure_uploaded(Path(f.name),key,size=12,sha256=sha,width=1,height=1,date="2026-07-21"))
  with self.assertRaises(EditorialError):R2Storage(config(),S3({**head,"ContentLength":13})).verify_object(key,size=12,sha256=sha)
 def test_traversal_rejected(self):
  with self.assertRaises(EditorialError):R2Storage(config(),S3()).build_public_url("daily/../x.webp")
if __name__=='__main__':unittest.main()
