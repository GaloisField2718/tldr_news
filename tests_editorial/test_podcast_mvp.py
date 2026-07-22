from __future__ import annotations
import json,tempfile,unittest
from pathlib import Path
from tools.tldr_podcast import DEFAULT,FALLBACK,PodcastError,estimate_cost,expected_open_close,podcast_key,preflight,validate_script

def source(root:Path,date="2026-07-21"):
 p=root/"generated/editorial/2026";p.mkdir(parents=True);f=p/f"{date}.json";f.write_text(json.dumps({"date":date,"status":"ai_complete","plan":{"lead":{"article_id":"a","issue_id":"i"}}}));return f
def script(source_hash,date="2026-07-21"):
 turns=[]
 for i in range(1,13):
  speaker="speaker_a" if i%2 else "speaker_b"
  text=("This explains how the reported change works, because the mechanism changes distribution. But the consequence may be limited, and what evidence would change that interpretation? "+("detail "*32)).strip()
  turns.append({"turn_id":f"t{i:03}","speaker":speaker,"text":text,"pause_after_ms":250})
 return {"schema_version":"1.0.0","publication_date":date,"episode_title":"Daily Index","summary":"Briefing","source_artifact_sha256":source_hash,"estimated_duration_seconds":0,"speakers":{"speaker_a":{"role":"cohost"},"speaker_b":{"role":"cohost"}},"turns":turns}
class PodcastTests(unittest.TestCase):
 def test_key_and_date_rotation(self):
  digest="sha256:"+"a"*64;self.assertEqual(podcast_key("2026-07-21",digest),"podcast/daily/2026/07/21/"+"a"*64+".mp3");self.assertEqual(expected_open_close("2026-07-21"),("speaker_a","speaker_b"));self.assertEqual(expected_open_close("2026-07-22"),("speaker_b","speaker_a"))
 def test_script_schema_balance_and_duration(self):
  with tempfile.TemporaryDirectory() as td:
   f=source(Path(td));s=script("sha256:"+__import__("hashlib").sha256(f.read_bytes()).hexdigest());s["estimated_duration_seconds"]=round(sum(len(x["text"]) for x in s["turns"])/15.5+3);result=validate_script(s,s["source_artifact_sha256"]);self.assertEqual(result["turn_count"],12);self.assertAlmostEqual(result["shares"]["speaker_a"],.5)
 def test_rejects_bad_rotation_markup_and_unbalanced_script(self):
  h="sha256:"+"a"*64;s=script(h);s["turns"][0]["speaker"]="speaker_b"
  with self.assertRaisesRegex(PodcastError,"rotation"):validate_script(s,h)
  s=script(h);s["turns"][0]["text"]="https://private.example"
  with self.assertRaisesRegex(PodcastError,"markup"):validate_script(s,h)
 def test_default_fallback_and_cost(self):
  self.assertEqual((DEFAULT.model,FALLBACK.model),("x-ai/grok-voice-tts-1.0","mistralai/voxtral-mini-tts-2603"));self.assertEqual(estimate_cost(DEFAULT,1000),.015)
 def test_zero_call_preflight_and_cost_gate(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);source(root);r=preflight(root,"2026-07-21",False,1);self.assertEqual((r["paid_calls"],r["turns_planned"],r["selected_model"]),(0,24,DEFAULT.model));self.assertFalse(r["cron_active"])
   with self.assertRaisesRegex(PodcastError,"estimated_cost_exceeds"):preflight(root,"2026-07-21",False,.01)
if __name__=="__main__":unittest.main()
