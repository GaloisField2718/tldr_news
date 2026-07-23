from __future__ import annotations
import json,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from tools.tldr_podcast import DEFAULT,FALLBACK,PodcastError,date_lock,editorial_request,estimate_cost,expected_open_close,extract_json_object,generate_script,initial_state,language_scope,load_state,normalize_script,podcast_key,preflight,profile_from_args,upload_audio,validate_script

def source(root:Path,date="2026-07-21"):
 p=root/"generated/editorial/2026";p.mkdir(parents=True,exist_ok=True);f=p/f"{date}.json";f.write_text(json.dumps({"date":date,"status":"ai_complete","plan":{"lead":{"article_id":"a","issue_id":"i"},"visual_brief":{"central_subject":"distribution changes through conversational search mechanisms"}}}));return f
def script(source_hash,date="2026-07-21"):
 turns=[]
 for i in range(1,25):
  speaker="speaker_a" if i%2 else "speaker_b"
  text=("This explains how the reported change works, because the mechanism changes distribution. But the consequence may be limited, and what evidence would change that interpretation? "+("detail "*10)).strip()
  turns.append({"turn_id":f"t{i:03}","speaker":speaker,"text":text,"pause_after_ms":250})
 return {"schema_version":"1.0.0","publication_date":date,"locale":"en-US","episode_title":"Daily Index","summary":"Briefing","source_artifact_sha256":source_hash,"estimated_duration_seconds":0,"speakers":{"speaker_a":{"role":"cohost"},"speaker_b":{"role":"cohost"}},"turns":turns}
class PodcastTests(unittest.TestCase):
 def test_key_and_date_rotation(self):
  digest="sha256:"+"a"*64;self.assertEqual(podcast_key("2026-07-21",digest),"podcast/daily/2026/07/21/"+"a"*64+".mp3");self.assertEqual(expected_open_close("2026-07-21"),("speaker_a","speaker_b"));self.assertEqual(expected_open_close("2026-07-22"),("speaker_b","speaker_a"))
 def test_script_schema_balance_and_duration(self):
  with tempfile.TemporaryDirectory() as td:
   f=source(Path(td));s=script("sha256:"+__import__("hashlib").sha256(f.read_bytes()).hexdigest());s["estimated_duration_seconds"]=round(sum(len(x["text"]) for x in s["turns"])/15.5+3);result=validate_script(s,s["source_artifact_sha256"]);self.assertEqual(result["turn_count"],24);self.assertAlmostEqual(result["shares"]["speaker_a"],.5)
 def test_rejects_bad_rotation_markup_and_unbalanced_script(self):
  h="sha256:"+"a"*64;s=script(h);s["turns"][0]["speaker"]="speaker_b"
  with self.assertRaisesRegex(PodcastError,"rotation"):validate_script(s,h)
  s=script(h);s["turns"][0]["text"]="https://private.example"
  with self.assertRaisesRegex(PodcastError,"markup"):validate_script(s,h)
 def test_private_state_conflict_and_lock_refusal(self):
  with tempfile.TemporaryDirectory() as td, patch.dict(__import__('os').environ,{"TLDR_PODCAST_RUNTIME_ROOT":td}),patch('tools.tldr_podcast.git_head',return_value='head'):
   root=Path(td)/'repo';root.mkdir();source(root);digest='sha256:'+__import__('hashlib').sha256(source(root).read_bytes()).hexdigest();profile=profile_from_args(False,1);rd,state=load_state(root,'2026-07-21',digest,profile);self.assertEqual(__import__('stat').S_IMODE(rd.stat().st_mode),0o700)
   with date_lock(rd):
    with self.assertRaisesRegex(PodcastError,'locked'):
     with date_lock(rd):pass
   state['production_code_head']='wrong';(rd/'state.json').write_text(json.dumps(state))
   with self.assertRaisesRegex(PodcastError,'state_conflict'):load_state(root,'2026-07-21',digest,profile)
 def test_editorial_request_is_json_only_and_no_network_in_test(self):
  class R:
   status_code=200
   def json(self):return {'choices':[{'message':{'content':'{}'}}]}
  self.assertEqual(editorial_request(lambda *a,**k:R(),'key','prompt'),'{}')
 def test_upload_reuses_match_and_rejects_conflict(self):
  class S:
   def head_object(self,k):return {'ContentLength':7}
   def build_public_url(self,k):return 'https://assets/'+k
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'a.mp3';p.write_bytes(b'1234567');url,wrote=upload_audio(S(),p,'2026-07-21',{'sha256':'sha256:'+'a'*64,'bytes':7});self.assertFalse(wrote);self.assertTrue(url.startswith('https://assets/'))
  class Bad(S):
   def head_object(self,k):return {'ContentLength':8}
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'a.mp3';p.write_bytes(b'1234567')
   with self.assertRaisesRegex(PodcastError,'r2_conflict'):upload_audio(Bad(),p,'2026-07-21',{'sha256':'sha256:'+'a'*64,'bytes':7})
 def test_safe_editorial_normalization_preserves_spoken_text(self):
  h='sha256:'+'a'*64;raw=script(h);raw['publication_date']=20260721;raw['locale']='en_US';raw['extra']='drop'
  for t in raw['turns']:t.pop('turn_id');t['pause_after_ms']='250.0'
  original=[t['text'] for t in raw['turns']];value=extract_json_object('```json\n'+json.dumps(raw)+'\n```');normalized,changes=normalize_script(value,'2026-07-21',h,'en');self.assertEqual([t['text'] for t in normalized['turns']],original);self.assertEqual(normalized['publication_date'],'2026-07-21');self.assertEqual(normalized['locale'],'en-US');self.assertEqual(normalized['turns'][0]['turn_id'],'t001');self.assertNotIn('extra',normalized);self.assertTrue(changes)
 def test_future_oversized_script_uses_bounded_third_compression_call(self):
  h='sha256:'+'a'*64;valid=script(h);oversized=json.loads(json.dumps(valid))
  for t in oversized['turns']:t['text']+=' redundant secondary detail that must be removed for the concise edition'
  oversized['estimated_duration_seconds']=500;docs=[oversized,oversized,valid];calls=[]
  class R:
   status_code=200
   def __init__(self,d):self.d=d
   def json(self):return {'choices':[{'message':{'content':json.dumps(self.d)}}]}
  def post(*a,**k):calls.append(k['json']['messages'][0]['content']);return R(docs[len(calls)-1])
  state={'editorial_attempts':0,'request_attempts':0,'estimated_cost_usd':0.0,'measured_cost_usd':None,'retries':0};source_doc={'plan':{'visual_brief':{'central_subject':'reported change works because mechanism changes distribution'}}}
  with language_scope('en'):out=generate_script(post,'key',source_doc,h,'2026-07-21',state,1)
  self.assertEqual((len(calls),state['editorial_attempts']), (3,3));self.assertIn('Concise rewrite only',calls[2]);self.assertEqual([t['text'] for t in out['turns']],[t['text'] for t in valid['turns']])
 def test_default_fallback_and_cost(self):
  self.assertEqual((DEFAULT.model,FALLBACK.model),("x-ai/grok-voice-tts-1.0","mistralai/voxtral-mini-tts-2603"));self.assertEqual(estimate_cost(DEFAULT,1000),.015)
 def test_zero_call_preflight_and_cost_gate(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);source(root);r=preflight(root,"2026-07-21",1);self.assertEqual((r["paid_calls"],r["selected_model"]),(0,DEFAULT.model));self.assertEqual(r["planned_editorial_requests"],2);self.assertFalse(r["cron_active"])
   with self.assertRaisesRegex(PodcastError,"estimated_cost_exceeds"):preflight(root,"2026-07-21",.01)
if __name__=="__main__":unittest.main()
