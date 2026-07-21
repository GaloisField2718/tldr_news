import base64,json,tempfile,unittest
from pathlib import Path
from tools.tldr_editorial.core import EditorialError,object_key
from tools.tldr_editorial.image import decode_image,validate_image
from tools.tldr_editorial.openrouter import CHAT_COMPLETIONS_URL,IMAGE_GENERATION_URL,IMAGE_MODELS_URL,OpenRouterClient
from tools.tldr_editorial.r2_storage import R2Storage
from tests_editorial.helpers import config,fake_webp

class Response:
 status_code=200
 def __init__(self,doc,headers=None):self.doc=doc;self.content=json.dumps(doc).encode();self.headers=headers or {}
 def json(self):return self.doc
 def iter_content(self,chunk_size=65536):
  for i in range(0,len(self.content),chunk_size):yield self.content[i:i+chunk_size]

def capability_docs(complete=True):
 model="google/gemini-3.1-flash-lite-image";path=f"/api/v1/images/models/{model}/endpoints"
 models={"data":[{"id":model,"endpoints":path}]}
 params={"n":{"type":"range","min":1,"max":1},"resolution":{"type":"enum","values":["1K"]},"aspect_ratio":{"type":"enum","values":["3:2"]}}
 if complete:params.update(output_format={"type":"enum","values":["webp"]},output_compression={"type":"range","min":1,"max":100},background={"type":"enum","values":["opaque"]})
 endpoints={"id":model,"endpoints":[{"provider_slug":"provider/compatible","supported_parameters":params}]}
 return models,endpoints

def capability_get(models=None,endpoints=None,calls=None):
 models=models or capability_docs()[0];endpoints=endpoints or capability_docs()[1]
 def get(url,**kw):
  if calls is not None:calls.append((url,kw))
  return Response(models if url==IMAGE_MODELS_URL else endpoints)
 return get

class ClientTests(unittest.TestCase):
 def test_editorial_request_has_strict_rules_metadata_and_usage(self):
  seen={};plan={"lead_candidate_id":"c001","front_page":[],"section_order":[],"visual_brief":{"mode":"none","source_candidate_ids":[],"central_subject":"","visual_metaphor":"","composition":"","forbidden_elements":[],"alt_text":""}}
  def post(url,**kw):seen.update(url=url,**kw);return Response({"id":"req","choices":[{"message":{"content":json.dumps(plan)}}],"usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5,"cost":.01}})
  dossier=[{"candidate_id":"c001","title":"T","summary":"S","content_class":"editorial","sector_slug":"tldr"}]
  r=OpenRouterClient(config(api_key="private"),post).editorial(dossier);self.assertEqual(seen["url"],CHAT_COMPLETIONS_URL);self.assertEqual(seen["timeout"],90);self.assertTrue(seen["json"]["response_format"]["json_schema"]["strict"]);self.assertTrue(seen["json"]["provider"]["require_parameters"]);self.assertEqual(r.usage["cost_usd"],.01)
  system=seen["json"]["messages"][0]["content"];user=json.loads(seen["json"]["messages"][1]["content"])
  for text in ("exactly 1","exactly one lead","no more than four secondaries","remaining stories briefs","lead_candidate_id","unique present sectors","exactly the lead","two or three genuinely related","Return only the strict JSON object"):self.assertIn(text,system)
  self.assertEqual(user["request_metadata"],{"expected_front_page_count":1,"eligible_candidate_count":1});self.assertNotIn("url",json.dumps(user).lower())
 def test_malformed_missing_choices_sanitized_http(self):
  with self.assertRaises(EditorialError):OpenRouterClient(config(api_key="x"),lambda *a,**k:Response({})).editorial([])
  r=Response({"secret":"must not appear"});r.status_code=500
  with self.assertRaisesRegex(EditorialError,"openrouter_http_500"):OpenRouterClient(config(api_key="x"),lambda *a,**k:r).editorial([])
 def test_capability_discovery_cached_and_compatible_endpoint_selected(self):
  calls=[];client=OpenRouterClient(config(api_key="x"),lambda *a,**k:None,capability_get(calls=calls));cap=client.image_capability();self.assertEqual(cap["provider_slug"],"provider/compatible");self.assertIs(client.image_capability(),cap);self.assertEqual(len(calls),2);self.assertTrue(all(x[1]["headers"]["Authorization"].startswith("Bearer ") for x in calls))
 def test_configured_model_missing(self):
  with self.assertRaisesRegex(EditorialError,"image_model_unavailable"):OpenRouterClient(config(api_key="x"),get=capability_get(models={"data":[]})).image_capability()
 def test_required_capability_absent(self):
  models,endpoints=capability_docs(False)
  with self.assertRaisesRegex(EditorialError,"image_required_capability_absent"):OpenRouterClient(config(api_key="x"),get=capability_get(models,endpoints)).image_capability()
 def test_dedicated_image_request_shape_cost_and_media(self):
  seen={};data=base64.b64encode(fake_webp()).decode()
  def post(url,**kw):seen.update(url=url,**kw);return Response({"id":"image-req","data":[{"b64_json":data,"media_type":"image/webp"}],"usage":{"cost":.25}})
  r=OpenRouterClient(config(api_key="x"),post,capability_get()).image("prompt");self.assertEqual(seen["url"],IMAGE_GENERATION_URL);self.assertNotEqual(seen["url"],CHAT_COMPLETIONS_URL)
  for key,value in {"model":"google/gemini-3.1-flash-lite-image","prompt":"prompt","n":1,"resolution":"1K","aspect_ratio":"3:2","output_format":"webp","output_compression":82,"background":"opaque"}.items():self.assertEqual(seen["json"][key],value)
  self.assertNotIn("messages",seen["json"]);self.assertEqual((r.value,r.media_type,r.usage["cost_usd"]),(data,"image/webp",.25))
 def test_unsupported_optional_image_parameters_are_omitted(self):
  models,endpoints=capability_docs();params=endpoints["endpoints"][0]["supported_parameters"];params.pop("output_compression");params.pop("background");seen={}
  def post(url,**kw):seen.update(kw);return Response({"data":[{"b64_json":"eA=="}]})
  OpenRouterClient(config(api_key="x"),post,capability_get(models,endpoints)).image("p");self.assertNotIn("output_compression",seen["json"]);self.assertNotIn("background",seen["json"])
 def test_image_data_count_and_shape_rejected(self):
  for data in ([],[{"b64_json":"x"},{"b64_json":"y"}],[{}],"bad"):
   with self.assertRaises(EditorialError):OpenRouterClient(config(api_key="x"),lambda *a,**k:Response({"data":data}),capability_get()).image("p")
 def test_bounded_editorial_capability_and_image_responses(self):
  huge=Response({});huge.content=b"{"+b" "*300000+b"}"
  with self.assertRaisesRegex(EditorialError,"editorial_response_too_large"):OpenRouterClient(config(api_key="x"),lambda *a,**k:huge).editorial([])
  huge_cap=Response({},headers={"Content-Length":"3000000"})
  with self.assertRaisesRegex(EditorialError,"image_capability_response_too_large"):OpenRouterClient(config(api_key="x"),get=lambda *a,**k:huge_cap).image_capability()
  huge_image=Response({},headers={"Content-Length":"9999999"})
  with self.assertRaisesRegex(EditorialError,"image_response_too_large"):OpenRouterClient(config(api_key="x",max_image_bytes=1000),lambda *a,**k:huge_image,capability_get()).image("p")

class ImageTests(unittest.TestCase):
 def test_decode_validate_dimensions_checksum(self):
  d=fake_webp();raw,media=decode_image("data:image/webp;base64,"+base64.b64encode(d).decode());im=validate_image(raw,media,2000000);self.assertEqual((im.width,im.height),(600,400));self.assertTrue(im.sha256.startswith("sha256:"))
 def test_invalid_base64_empty_nonwebp_malformed_oversize_aspect(self):
  for fn in [lambda:decode_image("!!!"),lambda:validate_image(b"","image/webp",10),lambda:validate_image(fake_webp(),"image/png",1000),lambda:validate_image(b"RIFFx","image/webp",1000),lambda:validate_image(fake_webp(),"image/webp",5),lambda:validate_image(fake_webp(600,600),"image/webp",1000),lambda:decode_image("data:image/png;base64,eA==","image/webp")]:
   with self.assertRaises(EditorialError):fn()

class S3:
 def __init__(self,head=None):self.head=head;self.calls=[]
 def head_object(self,**kw):
  self.calls.append(("head",kw))
  if self.head is None:e=Exception();e.response={"Error":{"Code":"404"}};raise e
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
