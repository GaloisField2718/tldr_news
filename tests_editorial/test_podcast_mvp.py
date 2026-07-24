from __future__ import annotations
import json,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from tools.tldr_podcast import DEFAULT,DEFAULT_EPISODE_PROFILE_ID,EPISODE_PROFILES,FALLBACK,PodcastError,date_lock,editorial_prompt,editorial_request,estimate_cost,expected_open_close,extract_json_object,generate_script,get_episode_profile,language_scope,load_state,normalize_script,podcast_key,preflight,profile_from_args,script_json_schema,upload_audio,validate_script

PROFILE=get_episode_profile(DEFAULT_EPISODE_PROFILE_ID)

def source(root:Path,date="2026-07-21"):
 p=root/"generated/editorial/2026";p.mkdir(parents=True,exist_ok=True);f=p/f"{date}.json";f.write_text(json.dumps({"date":date,"status":"ai_complete","plan":{"lead":{"article_id":"a","issue_id":"i"},"visual_brief":{"central_subject":"distribution changes through conversational search mechanisms"}}}));return f
def turn_text(length:int)->str:
 # Front-loads the "?" and the causal/contrastive keywords so even short truncated turns
 # (headline-brief-v1 turns can run as short as ~100 characters) still satisfy the
 # ask/explain/nuance requirement checked by validate_script.
 core="Why does this matter? Because the mechanism shifts distribution, but the effect may be limited depending on how quickly the rest of the industry actually adapts to this reported change. "
 return (core*(length//len(core)+1))[:length]
def script(source_hash,date="2026-07-21",n=10,total_chars=1600,pauses=250):
 """Build a headline-brief-v1-shaped script: n turns (even, so opener/closer rotation holds), summing to total_chars spoken characters, with per-turn pauses either a flat int or a list of n ints."""
 assert n%2==0
 pause_list=pauses if isinstance(pauses,list) else [pauses]*n
 base_len=total_chars//n;remainder=total_chars-base_len*n;turns=[]
 for i in range(1,n+1):
  speaker="speaker_a" if i%2 else "speaker_b";length=base_len+(remainder if i==n else 0)
  turns.append({"turn_id":f"t{i:03}","speaker":speaker,"text":turn_text(length),"pause_after_ms":pause_list[i-1]})
 s={"schema_version":"1.0.0","publication_date":date,"locale":"en-US","episode_title":"Daily Index","summary":"Briefing","source_artifact_sha256":source_hash,"estimated_duration_seconds":0,"speakers":{"speaker_a":{"role":"cohost"},"speaker_b":{"role":"cohost"}},"turns":turns}
 s["estimated_duration_seconds"]=round(sum(len(t["text"]) for t in turns)/15.5+sum(t["pause_after_ms"] for t in turns)/1000)
 return s
class PodcastTests(unittest.TestCase):
 def test_key_and_date_rotation(self):
  digest="sha256:"+"a"*64;self.assertEqual(podcast_key("2026-07-21",digest),"podcast/daily/2026/07/21/"+"a"*64+".mp3");self.assertEqual(expected_open_close("2026-07-21"),("speaker_a","speaker_b"));self.assertEqual(expected_open_close("2026-07-22"),("speaker_b","speaker_a"))
 def test_headline_brief_profile_is_selected_and_registered(self):
  self.assertEqual(DEFAULT_EPISODE_PROFILE_ID,"headline-brief-v1");self.assertIn("headline-brief-v1",EPISODE_PROFILES);self.assertIs(get_episode_profile(None),PROFILE);self.assertIs(get_episode_profile("headline-brief-v1"),PROFILE)
  with self.assertRaisesRegex(PodcastError,"profile_unknown"):get_episode_profile("daily-briefing-v1")
 def test_profile_thresholds_match_specification(self):
  self.assertEqual((PROFILE.min_duration,PROFILE.preferred_duration,PROFILE.max_duration),(55,90,130));self.assertEqual((PROFILE.min_turns,PROFILE.max_turns,PROFILE.preferred_turns),(8,16,(8,14)));self.assertEqual((PROFILE.min_chars,PROFILE.max_chars,PROFILE.preferred_chars),(1000,2100,(1200,1900)));self.assertEqual((PROFILE.speaker_share_min,PROFILE.speaker_share_max),(.4,.6));self.assertEqual(PROFILE.max_editorial_calls,3)
 def test_script_schema_balance_and_duration(self):
  with tempfile.TemporaryDirectory() as td:
   f=source(Path(td));s=script("sha256:"+__import__("hashlib").sha256(f.read_bytes()).hexdigest());result=validate_script(s,s["source_artifact_sha256"],PROFILE);self.assertEqual(result["turn_count"],10);self.assertAlmostEqual(result["shares"]["speaker_a"],.5)
 def test_rejects_bad_rotation_markup_and_unbalanced_script(self):
  h="sha256:"+"a"*64;s=script(h);s["turns"][0]["speaker"]="speaker_b"
  with self.assertRaisesRegex(PodcastError,"rotation"):validate_script(s,h,PROFILE)
  s=script(h);s["turns"][0]["text"]="https://private.example"
  with self.assertRaisesRegex(PodcastError,"markup"):validate_script(s,h,PROFILE)
 def test_accepts_at_minimum_turns(self):
  h="sha256:"+"a"*64;s=script(h,n=8,total_chars=1200);result=validate_script(s,h,PROFILE);self.assertEqual(result["turn_count"],8);self.assertTrue(55<=result["duration_seconds"]<=130)
 def test_accepts_at_maximum_turns(self):
  h="sha256:"+"a"*64;s=script(h,n=16,total_chars=1600);result=validate_script(s,h,PROFILE);self.assertEqual(result["turn_count"],16);self.assertTrue(55<=result["duration_seconds"]<=130)
 def test_rejects_below_minimum_turns(self):
  h="sha256:"+"a"*64;s=script(h,n=6,total_chars=1200)
  with self.assertRaisesRegex(PodcastError,"schema_invalid"):validate_script(s,h,PROFILE)
 def test_rejects_above_maximum_turns(self):
  h="sha256:"+"a"*64;s=script(h,n=18,total_chars=1800)
  with self.assertRaisesRegex(PodcastError,"schema_invalid"):validate_script(s,h,PROFILE)
 def test_accepts_at_minimum_spoken_characters(self):
  h="sha256:"+"a"*64;s=script(h,n=10,total_chars=1000,pauses=0);result=validate_script(s,h,PROFILE);self.assertEqual(sum(result["characters"].values()),1000);self.assertGreaterEqual(result["duration_seconds"],55)
 def test_rejects_below_minimum_spoken_characters(self):
  # Isolated on the low end: 999 chars alone already implies ~64s, still above the 55s floor,
  # so this rejection is driven purely by the character minimum, not the duration minimum.
  h="sha256:"+"a"*64;s=script(h,n=10,total_chars=999,pauses=0)
  with self.assertRaisesRegex(PodcastError,"duration_invalid"):validate_script(s,h,PROFILE)
 def test_rejects_above_maximum_spoken_characters(self):
  # Above 2100 characters at ~15.5 chars/second unavoidably also exceeds the 130s duration
  # ceiling (2100/15.5 already exceeds 130s); both bounds fire together by construction.
  h="sha256:"+"a"*64;s=script(h,n=10,total_chars=2200,pauses=0)
  with self.assertRaisesRegex(PodcastError,"duration_invalid"):validate_script(s,h,PROFILE)
 def test_accepts_near_maximum_duration_with_characters_in_range(self):
  h="sha256:"+"a"*64;s=script(h,n=10,total_chars=1900,pauses=500);result=validate_script(s,h,PROFILE);self.assertTrue(1000<=sum(result["characters"].values())<=2100);self.assertLessEqual(result["duration_seconds"],130)
 def test_rejects_above_maximum_duration_with_characters_still_valid(self):
  # Isolated on the high end: characters stay at 1900 (within the 1000-2100 range); only the
  # extra pause budget pushes estimated duration past the 130s ceiling.
  h="sha256:"+"a"*64;s=script(h,n=10,total_chars=1900,pauses=1300)
  with self.assertRaisesRegex(PodcastError,"duration_invalid"):validate_script(s,h,PROFILE)
 def test_speaker_balance_must_stay_within_forty_to_sixty_percent(self):
  h="sha256:"+"a"*64;s=script(h,n=10,total_chars=1600)
  for t in s["turns"]:
   if t["speaker"]=="speaker_a":t["text"]=turn_text(len(t["text"])*3)
  with self.assertRaisesRegex(PodcastError,"balance_invalid"):validate_script(s,h,PROFILE)
 def test_both_speakers_must_ask_explain_and_add_nuance(self):
  h="sha256:"+"a"*64;s=script(h,n=10,total_chars=1600)
  for t in s["turns"]:
   if t["speaker"]=="speaker_b":t["text"]="This is a plain declarative statement without any question or contrast at all whatsoever here."
  with self.assertRaisesRegex(PodcastError,"balance_invalid"):validate_script(s,h,PROFILE)
 def test_rejects_more_than_three_consecutive_turns_by_one_speaker(self):
  h="sha256:"+"a"*64;s=script(h,n=10,total_chars=1600)
  for t in s["turns"][:4]:t["speaker"]="speaker_a"
  with self.assertRaisesRegex(PodcastError,"consecutive"):validate_script(s,h,PROFILE)
 def test_script_json_schema_reflects_profile_turn_bounds(self):
  schema=script_json_schema(PROFILE);self.assertEqual((schema["properties"]["turns"]["minItems"],schema["properties"]["turns"]["maxItems"]),(8,16))
 def test_editorial_prompt_carries_profile_bounds_and_french_adaptation_guidance(self):
  with tempfile.TemporaryDirectory() as td:
   f=source(Path(td));digest="sha256:"+__import__("hashlib").sha256(f.read_bytes()).hexdigest()
  en=editorial_prompt({"plan":{}},digest,"2026-07-21",PROFILE);self.assertIn("8-16",en);self.assertIn("1000-2100",en);self.assertIn("55-130",en);self.assertIn("target 90",en)
  with language_scope("fr"):fr=editorial_prompt({"plan":{}},digest,"2026-07-21",PROFILE)
  self.assertIn("ne traduis pas littéralement",fr);self.assertIn("8-16",fr)
 def test_private_state_conflict_and_lock_refusal(self):
  with tempfile.TemporaryDirectory() as td, patch.dict(__import__('os').environ,{"TLDR_PODCAST_RUNTIME_ROOT":td}),patch('tools.tldr_podcast.git_head',return_value='head'):
   root=Path(td)/'repo';root.mkdir();source(root);digest='sha256:'+__import__('hashlib').sha256(source(root).read_bytes()).hexdigest();profile=profile_from_args(False,1);rd,state=load_state(root,'2026-07-21',digest,profile,DEFAULT_EPISODE_PROFILE_ID);self.assertEqual(__import__('stat').S_IMODE(rd.stat().st_mode),0o700);self.assertEqual(state["episode_profile_id"],"headline-brief-v1")
   with date_lock(rd):
    with self.assertRaisesRegex(PodcastError,'locked'):
     with date_lock(rd):pass
   state['production_code_head']='wrong';(rd/'state.json').write_text(json.dumps(state))
   with self.assertRaisesRegex(PodcastError,'state_conflict'):load_state(root,'2026-07-21',digest,profile,DEFAULT_EPISODE_PROFILE_ID)
 def test_editorial_request_is_json_only_and_no_network_in_test(self):
  class R:
   status_code=200
   def json(self):return {'choices':[{'message':{'content':'{}'}}]}
  self.assertEqual(editorial_request(lambda *a,**k:R(),'key','prompt',PROFILE),'{}')
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
  with language_scope('en'):out=generate_script(post,'key',source_doc,h,'2026-07-21',state,1,PROFILE)
  self.assertEqual((len(calls),state['editorial_attempts']), (3,3));self.assertIn('Concise rewrite only',calls[2]);self.assertIn('1200-1900',calls[2]);self.assertEqual([t['text'] for t in out['turns']],[t['text'] for t in valid['turns']])
 def test_third_call_reachable_after_two_non_duration_failures(self):
  # Regression test for a real production failure: a bounded repair on attempt 2 that fails
  # for a non-duration reason (here, a missing "?" breaks the balance check) must still get
  # the third and final call, instead of the flow giving up after only two attempts.
  h='sha256:'+'a'*64;valid=script(h);unbalanced=json.loads(json.dumps(valid))
  for t in unbalanced['turns']:
   if t['speaker']=='speaker_a':t['text']=t['text'].replace('?','.')
  docs=[unbalanced,unbalanced,valid];calls=[]
  class R:
   status_code=200
   def __init__(self,d):self.d=d
   def json(self):return {'choices':[{'message':{'content':json.dumps(self.d)}}]}
  def post(*a,**k):calls.append(k['json']['messages'][0]['content']);return R(docs[len(calls)-1])
  state={'editorial_attempts':0,'request_attempts':0,'estimated_cost_usd':0.0,'measured_cost_usd':None,'retries':0};source_doc={'plan':{'visual_brief':{'central_subject':'reported change works because mechanism changes distribution'}}}
  with language_scope('en'):out=generate_script(post,'key',source_doc,h,'2026-07-21',state,1,PROFILE)
  self.assertEqual((len(calls),state['editorial_attempts']), (3,3));self.assertIn('each speaker must ask a question',calls[1]);self.assertEqual([t['text'] for t in out['turns']],[t['text'] for t in valid['turns']])
 def test_nuance_detection_recognizes_limitation_language_beyond_the_original_keyword_list(self):
  # Regression test for a real production script where a speaker's turns genuinely stated a
  # caveat ("That limitation is important...") that the original narrow keyword list
  # ("but "/"however"/"although"/"may "/"could "/"not necessarily") failed to recognize.
  h='sha256:'+'a'*64;s=script(h)
  for t in s['turns']:
   if t['speaker']=='speaker_b':t['text']="Why might adoption stall? Because the cost structure differs by region, and that is a real limitation for smaller teams."
  result=validate_script(s,h,PROFILE);self.assertAlmostEqual(result['shares']['speaker_b'],600/1400,places=3)
 def test_default_fallback_and_cost(self):
  self.assertEqual((DEFAULT.model,FALLBACK.model),("x-ai/grok-voice-tts-1.0","mistralai/voxtral-mini-tts-2603"));self.assertEqual(estimate_cost(DEFAULT,1000),.015)
 def test_zero_call_preflight_and_cost_gate(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);source(root);r=preflight(root,"2026-07-21",1);self.assertEqual((r["paid_calls"],r["selected_model"]),(0,DEFAULT.model));self.assertEqual(r["planned_editorial_requests"],2);self.assertFalse(r["cron_active"])
   with self.assertRaisesRegex(PodcastError,"estimated_cost_exceeds"):preflight(root,"2026-07-21",.01)
 def test_preflight_reports_selected_profile_and_limits(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);source(root);r=preflight(root,"2026-07-21",1)
   self.assertEqual(r["episode_profile_id"],"headline-brief-v1");self.assertEqual(r["target_duration_seconds"],90);self.assertEqual(r["valid_duration_range_seconds"],[55,130]);self.assertEqual(r["turn_range"],[8,16]);self.assertEqual(r["preferred_turn_range"],[8,14]);self.assertEqual(r["spoken_character_range"],[1000,2100]);self.assertEqual(r["preferred_spoken_character_range"],[1200,1900]);self.assertEqual(r["maximum_editorial_calls"],3);self.assertEqual(r["maximum_tts_attempts_per_language"],32);self.assertEqual(r["planned_tts_turns_per_language"],"8-16");self.assertEqual(r["cost_ceiling_usd_per_language"],1)
if __name__=="__main__":unittest.main()
