from __future__ import annotations
import hashlib,json,os,stat,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.tldr_podcast import (DEFAULT,PodcastError,generate,load_state,measure_audio,publish,profile_from_args,run_daily,tts_turn)

class Response:
 def __init__(self,status=200,content=b'',ctype='audio/mpeg',doc=None):self.status_code=status;self.content=content;self.headers={'content-type':ctype,'content-length':str(len(content))};self._doc=doc
 def json(self):return self._doc

def source(root):
 p=root/'generated/editorial/2026';p.mkdir(parents=True);f=p/'2026-07-21.json';f.write_text(json.dumps({'date':'2026-07-21','status':'ai_complete','plan':{'lead':{'article_id':'a','issue_id':'i'},'visual_brief':{'central_subject':'distribution changes through conversational search mechanisms','editorial_idea':'conversational search changes distribution'}}}));return f
def script(digest,n=24):
 turns=[]
 for i in range(1,n+1):
  speaker='speaker_a' if i%2 else 'speaker_b';text=('Search changes distribution because answers stay on the service. But effects may vary, so what evidence would show a durable traffic shift? '+'context '*8).strip();turns.append({'turn_id':f't{i:03}','speaker':speaker,'text':text,'pause_after_ms':250})
 s={'schema_version':'1.0.0','publication_date':'2026-07-21','episode_title':'Daily Index','summary':'A grounded technology briefing.','source_artifact_sha256':digest,'estimated_duration_seconds':0,'speakers':{'speaker_a':{'role':'cohost'},'speaker_b':{'role':'cohost'}},'turns':turns};s['estimated_duration_seconds']=round(sum(len(x['text']) for x in turns)/15.5+6);return s
class FakePost:
 def __init__(self,doc,audio,interrupt_before=None,fail=None):self.doc=doc;self.audio=audio;self.interrupt_before=interrupt_before;self.fail=fail;self.editorial=0;self.tts=0;self.completed=0;self.by_turn={}
 def __call__(self,url,**kw):
  if 'chat/completions' in url:self.editorial+=1;return Response(doc={'choices':[{'message':{'content':json.dumps(self.doc)}}]})
  tid=self.fail[0] if self.fail and self.by_turn.get(self.fail[0],0)==1 else f't{self.completed+1:03}';self.by_turn[tid]=self.by_turn.get(tid,0)+1
  if self.interrupt_before and self.completed+1==self.interrupt_before:raise RuntimeError('controlled interruption')
  self.tts+=1
  if self.fail and tid==self.fail[0] and self.by_turn[tid]==1:return Response(self.fail[1],b'{"error":"controlled"}','application/json')
  self.completed+=1;return Response(200,self.audio)
class FakeClient:
 def __init__(self):self.objects={};self.uploads=0
 def upload_file(self,path,bucket,key,ExtraArgs):self.uploads+=1;self.objects[key]=(Path(path).read_bytes(),ExtraArgs)
class FakeStorage:
 def __init__(self):self.client=FakeClient();self.config=type('C',(),{'r2_bucket':'fake'})()
 def head_object(self,key):
  item=self.client.objects.get(key);return None if item is None else {'ContentLength':len(item[0]),'ContentType':item[1]['ContentType']}
 def build_public_url(self,key):return 'https://fake.invalid/'+key
 def get(self,url,timeout=60):
  item=next(v for k,v in self.client.objects.items() if url.endswith(k));return Response(200,item[0],'audio/mpeg')
class RuntimeIntegration(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();cls.audio=Path(cls.temp.name)/'tone.mp3';subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:duration=12','-ar','24000','-ac','1','-c:a','libmp3lame','-b:a','128k',str(cls.audio)],check=True);cls.bytes=cls.audio.read_bytes()
 @classmethod
 def tearDownClass(cls):cls.temp.cleanup()
 def case(self):
  td=tempfile.TemporaryDirectory();root=Path(td.name)/'repo';root.mkdir();f=source(root);digest='sha256:'+hashlib.sha256(f.read_bytes()).hexdigest();return td,root,digest,script(digest)
 def run_generate(self,root,post):
  with patch.dict(os.environ,{'TLDR_PODCAST_RUNTIME_ROOT':str(root/'runtime')}),patch('tools.tldr_podcast.git_head',return_value='test-head'):
   return generate(root,'2026-07-21','key',post=post)
 def run_publish(self,root,storage):
  with patch.dict(os.environ,{'TLDR_PODCAST_RUNTIME_ROOT':str(root/'runtime')}),patch('tools.tldr_podcast.git_head',return_value='test-head'):
   return publish(root,'2026-07-21',storage,True,storage.get)
 def test_complete_orchestration_publish_and_no_duplicate_calls(self):
  td,root,digest,s=self.case()
  try:
   post=FakePost(s,self.bytes);out=self.run_generate(root,post);self.assertEqual((post.editorial,post.tts),(1,24));m=measure_audio(Path(out['private_audio']));self.assertTrue(270<=m['duration_seconds']<=390);self.assertEqual((m['codec'],m['sample_rate'],m['channels']),('mp3',24000,1));self.assertEqual(stat.S_IMODE((root/'runtime/2026-07-21').stat().st_mode),0o700);self.assertEqual(stat.S_IMODE((root/'runtime/2026-07-21/state.json').stat().st_mode),0o600);self.assertFalse((root/'runtime/2026-07-21/.state.json.tmp').exists())
   storage=FakeStorage();doc=self.run_publish(root,storage);self.assertEqual(storage.client.uploads,1);self.assertEqual(doc['status'],'published');self.assertNotRegex(json.dumps(doc),'x-ai|eve|rex|cost|generation|runtime')
   again=FakePost(s,self.bytes);self.run_generate(root,again);self.run_publish(root,storage);self.assertEqual((again.editorial,again.tts,storage.client.uploads),(0,0,1))
  finally:td.cleanup()
 def test_interruption_after_script_and_turn_seven_resumes(self):
  td,root,digest,s=self.case()
  try:
   first=FakePost(s,self.bytes,interrupt_before=1)
   with self.assertRaises(RuntimeError):self.run_generate(root,first)
   second=FakePost(s,self.bytes);self.run_generate(root,second);self.assertEqual((first.editorial,first.tts,second.editorial,second.tts),(1,0,0,24))
   td2,root2,digest2,s2=self.case();first=FakePost(s2,self.bytes,interrupt_before=8)
   with self.assertRaises(RuntimeError):self.run_generate(root2,first)
   second=FakePost(s2,self.bytes);self.run_generate(root2,second);self.assertEqual((first.tts,second.tts), (7,17));td2.cleanup()
  finally:td.cleanup()
 def test_retry_400_and_budget_boundary(self):
  td,root,digest,s=self.case()
  try:
   retry=FakePost(s,self.bytes,fail=('t012',500));self.run_generate(root,retry);self.assertEqual((retry.tts,retry.by_turn['t012']), (25,2))
   td2,root2,digest2,s2=self.case();bad=FakePost(s2,self.bytes,fail=('t012',400))
   with self.assertRaisesRegex(PodcastError,'unrecoverable'):self.run_generate(root2,bad)
   self.assertEqual((bad.tts,bad.by_turn['t012']), (12,1));self.assertNotIn('t013',bad.by_turn);td2.cleanup()
   with patch.dict(os.environ,{'TLDR_PODCAST_RUNTIME_ROOT':str(root/'runtime')}),patch('tools.tldr_podcast.git_head',return_value='test-head'):
    rd,state=load_state(root,'2026-07-21',digest,profile_from_args(False,1));state['planned_turns']=[f't{i:03}' for i in range(1,37)];state['tts_attempts']=72
    with self.assertRaisesRegex(PodcastError,'attempt_budget'):tts_turn(retry,'key',DEFAULT,s['turns'][0],rd,state,1)
  finally:td.cleanup()
 def test_full_mocked_bilingual_run_daily_is_atomic(self):
  td,root,digest,en=self.case()
  try:
   fr=json.loads(json.dumps(en));fr['episode_title']='L’Index du jour';fr['summary']='Une analyse technologique en français.'
   for t in fr['turns']:t['text']=('La distribution change parce que la recherche conversationnelle garde les réponses sur le service. Mais les effets pourraient varier, alors quelles preuves montreraient un changement durable du trafic? '+'contexte '*4).strip()
   fr['estimated_duration_seconds']=round(sum(len(x['text']) for x in fr['turns'])/15.5+6)
   audio=self.bytes
   class Multi:
    def __init__(self):self.editorial={'en':0,'fr':0};self.tts=0
    def __call__(self,url,**kw):
     if 'chat/completions' in url:
      language='fr' if 'français naturel' in kw['json']['messages'][0]['content'] else 'en';self.editorial[language]+=1;doc=fr if language=='fr' else en;return Response(doc={'choices':[{'message':{'content':json.dumps(doc)}}]})
     self.tts+=1;return Response(200,audio)
   post=Multi();storage=FakeStorage()
   with patch.dict(os.environ,{'TLDR_PODCAST_RUNTIME_ROOT':str(root/'runtime')}),patch('tools.tldr_podcast.git_head',return_value='test-head'):
    result=run_daily(root,'2026-07-21','key',storage,post,storage.get)
   self.assertEqual((post.editorial,post.tts,storage.client.uploads),({'en':1,'fr':1},50,2));self.assertEqual(set(result['artifact']['languages']),{'en','fr'});self.assertTrue((root/'generated/podcast/2026/2026-07-21.json').exists())
  finally:td.cleanup()
 def test_upload_conflict_and_private_artifact_gate(self):
  td,root,digest,s=self.case()
  try:
   post=FakePost(s,self.bytes);self.run_generate(root,post);self.assertFalse((root/'generated/podcast/2026/2026-07-21.json').exists());storage=FakeStorage();storage.client.objects['podcast/daily/2026/07/21/'+('a'*64)+'.mp3']=(b'wrong',{'ContentType':'audio/mpeg'})
   # A normal publish writes only after verified upload; an invalid public response is rejected before artifact creation.
   storage.get=lambda *a,**k:Response(500,b'', 'text/plain')
   with self.assertRaisesRegex(PodcastError,'public_verify'):self.run_publish(root,storage)
   self.assertEqual(storage.client.uploads,1);self.assertFalse((root/'generated/podcast/2026/2026-07-21.json').exists())
   storage.get=FakeStorage.get.__get__(storage,FakeStorage);self.run_publish(root,storage);self.assertEqual(storage.client.uploads,1);self.assertTrue((root/'generated/podcast/2026/2026-07-21.json').exists())
  finally:td.cleanup()
if __name__=='__main__':unittest.main()
