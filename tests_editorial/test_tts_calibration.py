from __future__ import annotations
import json,os,shutil,stat,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.tldr_tts_calibration import (CalibrationError,Candidate,VOICE_PROFILES,assemble,build_request,dialogue,discover_models,estimate,generation_id,paid_gate,probe,request_turn,secure_mapping,validate_audio_response,validate_voices,write_reveal)

def model(slug,provider,pricing=None):
 return {'id':slug,'architecture':{'modality':'text->speech','output_modalities':['speech']},'pricing':pricing or {'prompt':'0.00001','completion':'0'},'supported_parameters':['response_format'],'top_provider':{'context_length':4096},'name':provider}
def models():return {'data':[model('openai/gpt-4o-mini-tts-2025-12-15','OpenAI'),model('google/gemini-3.1-flash-tts-preview','Google',{'prompt':'0.000001','completion':'0.00002'}),model('mistralai/voxtral-mini-tts-2603','Mistral',{'prompt':'0.000016','completion':'0'}),{'id':'text','architecture':{'modality':'text->text','output_modalities':['text']}}]}
class Response:
 def __init__(self,status=200,content=b'I'*100,ctype='audio/mpeg',headers=None):self.status_code=status;self.content=content;self.headers={'content-type':ctype,**(headers or {})}
class TTSCalibrationTests(unittest.TestCase):
 def candidate(self,provider='openai'):
  slug={'openai':'openai/gpt-4o-mini-tts-2025-12-15','google':'google/gemini-3.1-flash-tts-preview','mistral':'mistralai/voxtral-mini-tts-2603'}[provider];p=VOICE_PROFILES[provider];return Candidate(provider,slug,{'host':p['host'],'analyst':p['analyst']},{'prompt':'0.00001','completion':'0'},('speech',),('response_format',),4096)
 def test_model_discovery_filters_speech_and_selects_current_google(self):
  found,missing=discover_models(models());self.assertEqual(missing,[]);self.assertEqual([x.provider for x in found],['openai','google','mistral']);self.assertEqual(found[1].model,'google/gemini-3.1-flash-tts-preview')
 def test_missing_required_model_blocks_candidate_set(self):
  doc=models();doc['data']=doc['data'][1:];found,missing=discover_models(doc);self.assertEqual(missing,['openai']);self.assertEqual(len(found),2)
 def test_voice_validation_requires_supported_distinct_pair(self):
  validate_voices(VOICE_PROFILES['google'],['Kore','Aoede'])
  for voices in (['Kore','Kore'],['Kore','unknown']):
   with self.assertRaises(CalibrationError):validate_voices(VOICE_PROFILES['google'],voices)
 def test_request_shape_and_openai_only_instructions(self):
  turn={'speaker':'host','text':'Calm report'};openai=build_request(self.candidate(),turn);google=build_request(self.candidate('google'),turn);self.assertEqual((openai['response_format'],openai['speed'],openai['voice']),('mp3',1.0,'alloy'));self.assertIn('instructions',openai);self.assertNotIn('instructions',google)
 def test_response_content_type_and_json_error_rejected(self):
  self.assertEqual(len(validate_audio_response(Response())),100)
  for r in (Response(200,b'{"error":"bad"}','application/json'),Response(200,b'['+b'x'*100,'audio/mpeg')):
   with self.assertRaisesRegex(CalibrationError,'not_audio'):validate_audio_response(r)
 def test_generation_id_capture(self):self.assertEqual(generation_id(Response(headers={'X-Generation-Id':'safe-id'})),'safe-id')
 def test_retry_bound_and_retry_count(self):
  calls=[]
  def post(*a,**k):calls.append(1);return Response(500) if len(calls)==1 else Response(headers={'x-generation-id':'g'})
  audio,meta=request_turn(post,'secret',{'x':1},1);self.assertEqual((len(calls),meta['retry_count'],meta['generation_id']),(2,1,'g'));self.assertNotIn('secret',str(meta))
  with self.assertRaisesRegex(CalibrationError,'retry_bound'):request_turn(post,'x',{},2)
 def test_http_400_never_retries(self):
  calls=[]
  with self.assertRaises(CalibrationError):request_turn(lambda *a,**k:(calls.append(1) or Response(400)), 'x',{},1)
  self.assertEqual(len(calls),1)
 def test_dialogue_turn_order_and_required_terms(self):
  d=dialogue(Path('calibration/tts/blind-test-v1/dialogue.json'));text=' '.join(x['text'] for x in d['turns']);self.assertEqual([x['turn_id'] for x in d['turns']],[f't{i:02}' for i in range(1,9)])
  for term in ('Google AI Search','independent websites','traffic','conversational interface','S E O'):self.assertIn(term,text)
 @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg is enforced by paid preflight')
 def test_assembly_pause_decodability_and_metadata_stripping(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);turns=[]
   for i in range(2):
    p=root/f'in{i}.mp3';subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'sine=frequency={440+i*100}:duration=0.1','-metadata','artist=provider','-q:a','9',str(p)],check=True);turns.append(p)
   out=root/'candidate-a.mp3';assemble(turns,[100,0],out);info=probe(out);self.assertGreater(info['duration_seconds'],.25);self.assertNotIn('artist',{k.lower() for k in info['metadata_tags']});self.assertTrue(info['sha256'].startswith('sha256:'))
 def test_assembly_rejects_order_mismatch(self):
  with self.assertRaisesRegex(CalibrationError,'assembly_order'):assemble([Path('a')],[] ,Path('x'))
 def test_anonymous_secure_mapping(self):
  cs=[self.candidate(),self.candidate('google'),self.candidate('mistral')];mapping=secure_mapping(cs);self.assertEqual(set(mapping),{'candidate-a','candidate-b','candidate-c'});self.assertEqual({x.model for x in mapping.values()},{x.model for x in cs})
 def test_reveal_mode_is_private_and_public_names_are_anonymous(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'tts-reveal.json';write_reveal(p,{'candidate-a':self.candidate()});self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600);self.assertIn('openai',p.read_text());self.assertNotIn('openai','candidate-a.mp3')
 def test_cost_estimation(self):
  x=estimate([self.candidate()],1000);self.assertEqual(x['input_cost_upper_bound_usd'],.01)
 def test_paid_authorization_gate(self):
  cs=[self.candidate(),self.candidate('google'),self.candidate('mistral')]
  with self.assertRaisesRegex(CalibrationError,'explicit_paid'):paid_gate(authorized=False,candidates=cs,estimated_total=.1,output=Path('/tmp/out'))
  with patch.dict(os.environ,{'OPENROUTER_API_KEY':'private'}),patch('tools.tldr_tts_calibration.shutil.which',return_value='/bin/tool'),patch('tools.tldr_tts_calibration.subprocess.run') as run:
   run.return_value.stdout='';paid_gate(authorized=True,candidates=cs,estimated_total=.1,output=Path('/tmp/out'))
 def test_cost_and_candidate_gates_precede_paid_work(self):
  with self.assertRaisesRegex(CalibrationError,'three_candidates'):paid_gate(authorized=True,candidates=[],estimated_total=.1,output=Path('/tmp/out'))
  with self.assertRaisesRegex(CalibrationError,'estimated_cost'):paid_gate(authorized=True,candidates=[self.candidate()]*3,estimated_total=1.01,output=Path('/tmp/out'))
 def test_module_has_no_r2_or_production_artifact_write_path(self):
  source=Path('tools/tldr_tts_calibration.py').read_text().lower();self.assertNotIn('r2storage',source);self.assertNotIn('generated/editorial',source);self.assertNotIn('frontend',source.replace('frontend_writes',''))

if __name__=='__main__':unittest.main()
