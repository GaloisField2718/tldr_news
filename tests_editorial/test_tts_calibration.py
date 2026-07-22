from __future__ import annotations
import copy,json,os,shutil,stat,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools.tldr_tts_calibration import (CAPABILITIES,CalibrationError,Candidate,SpeechHTTPError,assemble,build_gemini_bonus,build_request,dialogue,discover_models,estimate,generation_id,http_diagnostic,paid_gate,probe,request_turn,secure_mapping,validate_audio_response,validate_voices,write_reveal)

def model(slug,pricing=None,context=4096):return {'id':slug,'architecture':{'modality':'text->speech','output_modalities':['speech']},'pricing':pricing or {'prompt':'0.00001','completion':'0'},'supported_parameters':['response_format'],'top_provider':{'context_length':context}}
def models(include_microsoft=True,include_xai=True):
 data=[model('google/gemini-3.1-flash-tts-preview',{'prompt':'0.000001','completion':'0.00002'},32768),model('mistralai/voxtral-mini-tts-2603',{'prompt':'0.000016','completion':'0'}),{'id':'text','architecture':{'modality':'text->text','output_modalities':['text']}}]
 if include_microsoft:data.append(model('microsoft/mai-voice-2',{'prompt':'0.000022','completion':'0'},0))
 if include_xai:data.append(model('x-ai/grok-voice-tts-1.0',{'prompt':'0.000015','completion':'0'},15000))
 return {'data':data}
class Response:
 def __init__(self,status=200,content=b'I'*100,ctype='audio/mpeg',headers=None):self.status_code=status;self.content=content;self.headers={'content-type':ctype,**(headers or {})}
class TTSCalibrationTests(unittest.TestCase):
 def candidate(self,slug='x-ai/grok-voice-tts-1.0'):
  cap=CAPABILITIES[slug];pricing={'prompt':'0.000001','completion':'0.00002'} if cap['pricing_unit']=='mixed_tokens' else {'prompt':'0.000016' if slug.startswith('mistralai/') else '0.000015','completion':'0'}
  return Candidate(cap['provider'],slug,{'host':cap['host'],'analyst':cap['analyst']},pricing,cap['pricing_unit'],cap['source'],tuple(sorted(cap['formats'])),('speech',),('response_format',),cap['max_input'])
 def test_openai_absent_does_not_block_three_candidates(self):
  found,missing=discover_models(models(),300);self.assertEqual(missing,[]);self.assertEqual([x.model for x in found],['google/gemini-3.1-flash-tts-preview','mistralai/voxtral-mini-tts-2603','x-ai/grok-voice-tts-1.0'])
 def test_ordered_challenger_selects_microsoft_when_valid(self):
  cap=copy.deepcopy(CAPABILITIES['microsoft/mai-voice-2']);cap.update(analyst='en-US-Analyst:MAI-Voice-2',english_voices={'en-US-Harper:MAI-Voice-2','en-US-Analyst:MAI-Voice-2'},max_input=4000)
  with patch.dict(CAPABILITIES,{'microsoft/mai-voice-2':cap}):self.assertEqual(discover_models(models(),300)[0][2].model,'microsoft/mai-voice-2')
 def test_xai_selected_when_microsoft_is_invalid_or_absent(self):
  self.assertEqual(discover_models(models(),300)[0][2].model,'x-ai/grok-voice-tts-1.0');self.assertEqual(discover_models(models(False),300)[0][2].model,'x-ai/grok-voice-tts-1.0')
 def test_ordered_fallback_selects_deepgram(self):
  doc=models(False,False);doc['data'].append(model('deepgram/aura-2',{'prompt':'0.00003','completion':'0'}));self.assertEqual(discover_models(doc,300)[0][2].model,'deepgram/aura-2')
 def test_challenger_without_two_voices_is_rejected(self):
  bad=copy.deepcopy(CAPABILITIES['x-ai/grok-voice-tts-1.0']);bad['analyst']=bad['host']
  with patch.dict(CAPABILITIES,{'x-ai/grok-voice-tts-1.0':bad}):self.assertEqual(discover_models(models(False),300)[1],['challenger'])
 def test_missing_pricing_and_unsupported_endpoint_rejected(self):
  doc=models(False);next(x for x in doc['data'] if x['id'].startswith('x-ai'))['pricing']={}
  self.assertEqual(discover_models(doc,300)[1],['challenger'])
  bad=copy.deepcopy(CAPABILITIES['x-ai/grok-voice-tts-1.0']);bad['speech_endpoint']=False
  with patch.dict(CAPABILITIES,{'x-ai/grok-voice-tts-1.0':bad}):self.assertEqual(discover_models(models(False),300)[1],['challenger'])
 def test_input_limit_and_speech_filtering(self):
  self.assertEqual(discover_models(models(False),16000)[1],['mistral','challenger']);doc=models(False);doc['data'][-1]['architecture']['output_modalities']=[];self.assertEqual(discover_models(doc,300)[1],['challenger'])
 def test_voice_validation_and_request_are_provider_neutral(self):
  validate_voices(CAPABILITIES['x-ai/grok-voice-tts-1.0'],['eve','rex']);body=build_request(self.candidate('mistralai/voxtral-mini-tts-2603'),{'speaker':'host','text':'Report'});self.assertEqual(body,{'model':'mistralai/voxtral-mini-tts-2603','input':'Report','voice':'en_paul_neutral','response_format':'mp3'});self.assertNotIn('instructions',body);self.assertNotIn('speed',body)
  with self.assertRaisesRegex(CalibrationError,'canary_not_proven'):build_request(self.candidate(),{'speaker':'host','text':'Report'})
 def test_proven_gemini_pcm_capability(self):
  body=build_request(self.candidate('google/gemini-3.1-flash-tts-preview'),{'speaker':'host','text':'Report'});self.assertEqual(body['response_format'],'pcm');cap=CAPABILITIES['google/gemini-3.1-flash-tts-preview'];self.assertEqual((cap['accepted_mime'],cap['native_codec'],cap['sample_rate'],cap['channels']),('audio/pcm;rate=24000;channels=1','pcm_s16le',24000,1))
 def test_gemini_bonus_is_disabled_while_passthrough_contract_is_unproven(self):
  with self.assertRaisesRegex(CalibrationError,'bonus_contract_unproven'):build_gemini_bonus(self.candidate('google/gemini-3.1-flash-tts-preview'),dialogue(Path('calibration/tts/blind-test-v1/dialogue.json'))['turns'])
 def test_response_content_type_json_error_generation_id_and_retry(self):
  self.assertEqual(len(validate_audio_response(Response())),100);self.assertEqual(generation_id(Response(headers={'X-Generation-Id':'safe'})),'safe')
  with self.assertRaises(CalibrationError):validate_audio_response(Response(200,b'{"error":1}','application/json'))
  calls=[]
  def post(*a,**k):calls.append(1);return Response(500) if len(calls)==1 else Response()
  _,meta=request_turn(post,'secret',{},1);self.assertEqual((len(calls),meta['retry_count']),(2,1))
  with self.assertRaises(CalibrationError):request_turn(post,'x',{},2)
 def test_http_400_never_retries(self):
  calls=[]
  with self.assertRaises(SpeechHTTPError):request_turn(lambda *a,**k:(calls.append(1) or Response(400,b'{"error":{"code":"bad_voice","message":"invalid voice"}}','application/json')),'x',{'model':'m','voice':'v','response_format':'mp3','input':'safe'},1,turn_id='t01')
  self.assertEqual(len(calls),1)
 def test_json_and_text_http_diagnostics_are_retained(self):
  body={'model':'m','voice':'v','response_format':'mp3','input':'do not persist'};j=http_diagnostic(Response(400,b'{"error":{"code":"bad","message":"wrong voice"}}','application/json',{'x-request-id':'r'}),body,'t01',1,'secret');self.assertEqual((j['error_code'],j['error_message'],j['safe_response_headers']['x-request-id']),('bad','wrong voice','r'));self.assertNotIn('do not persist',json.dumps(j));text=http_diagnostic(Response(400,b'plain failure','text/plain'),body,'t01',1,'secret');self.assertEqual(text['response_body'],'plain failure');self.assertIsNone(text['error_code'])
 def test_oversized_malformed_and_secret_diagnostics_are_safe(self):
  raw=(b'api_key=secret Bearer secret '+b'x'*17000);x=http_diagnostic(Response(400,raw,'text/plain'),{'model':'m','voice':'v','response_format':'pcm','input':'x'},'t01',1,'secret');self.assertTrue(x['response_body_truncated']);self.assertNotIn('secret',json.dumps(x));self.assertLessEqual(len(x['response_body'].encode()),16384)
 def test_diagnostic_directory_and_file_permissions(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)/'private'
   with self.assertRaises(SpeechHTTPError):request_turn(lambda *a,**k:Response(400,b'bad','text/plain'),'key',{'model':'m','voice':'v','response_format':'mp3','input':'x'},0,turn_id='t01',diagnostic_dir=root)
   self.assertEqual(stat.S_IMODE(root.stat().st_mode),0o700);self.assertEqual(stat.S_IMODE(next(root.iterdir()).stat().st_mode),0o600)
 def test_dialogue_order_terms_and_deterministic_request_count(self):
  d=dialogue(Path('calibration/tts/blind-test-v1/dialogue.json'));self.assertEqual(len(d['turns'])*3,24);self.assertEqual([x['turn_id'] for x in d['turns']],[f't{i:02}' for i in range(1,9)]);text=' '.join(x['text'] for x in d['turns']);self.assertTrue(all(x in text for x in ('Google AI Search','independent websites','traffic','conversational interface')))
 @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'FFmpeg is enforced by paid preflight')
 def test_assembly_pause_decodability_and_metadata_stripping(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);turns=[]
   for i in range(2):
    p=root/f'in{i}.mp3';subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'sine=frequency={440+i*100}:duration=0.1','-metadata','artist=provider','-q:a','9',str(p)],check=True);turns.append(p)
   out=root/'candidate-a.mp3';assemble(turns,[100,0],out);info=probe(out);self.assertGreater(info['duration_seconds'],.25);self.assertNotIn('artist',{k.lower() for k in info['metadata_tags']})
 def test_secure_mapping_and_bonus_excluded_from_reveal_ranking(self):
  cs=[self.candidate('google/gemini-3.1-flash-tts-preview'),self.candidate('mistralai/voxtral-mini-tts-2603'),self.candidate()];mapping=secure_mapping(cs);self.assertEqual(set(mapping),{'candidate-a','candidate-b','candidate-c'});self.assertNotIn('candidate-bonus',mapping)
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'tts-reveal.json';write_reveal(p,mapping,{'candidate-bonus':[{'model':'google'}]});doc=json.loads(p.read_text());self.assertNotIn('candidate-bonus',doc['mapping']);self.assertIn('candidate-bonus',doc['generation_records']);self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600)
 def test_complete_mixed_cost_accounting(self):
  cs=[self.candidate('google/gemini-3.1-flash-tts-preview'),self.candidate('mistralai/voxtral-mini-tts-2603'),self.candidate()];x=estimate(cs,1264);self.assertEqual(x['candidates'][0]['estimated_audio_tokens'],2880);self.assertEqual(x['main_cost_upper_bound_usd'],.097206);self.assertEqual(x['gemini_bonus_cost_upper_bound_usd'],.058022);self.assertEqual(x['total_upper_bound_usd'],.155228)
 def test_paid_and_separate_bonus_authorization_gates(self):
  cs=[self.candidate('google/gemini-3.1-flash-tts-preview'),self.candidate('mistralai/voxtral-mini-tts-2603'),self.candidate()]
  with self.assertRaisesRegex(CalibrationError,'explicit_paid'):paid_gate(authorized=False,candidates=cs,estimated_total=.2,output=Path('/tmp/out'))
  with self.assertRaisesRegex(CalibrationError,'all_three_canaries'):paid_gate(authorized=True,candidates=cs,estimated_total=.2,output=Path('/tmp/out'))
  proven={k:{**v,'canary_proven':True} for k,v in CAPABILITIES.items()}
  with patch.dict(CAPABILITIES,proven,clear=True):
   with self.assertRaisesRegex(CalibrationError,'bonus_contract_unproven'):paid_gate(authorized=True,candidates=cs,estimated_total=.2,output=Path('/tmp/out'),bonus=True)
   with patch.dict(os.environ,{'OPENROUTER_API_KEY':'private'}),patch('tools.tldr_tts_calibration.shutil.which',return_value='/bin/tool'),patch('tools.tldr_tts_calibration.subprocess.run') as run:
    run.return_value.stdout='';paid_gate(authorized=True,candidates=cs,estimated_total=.2,output=Path('/tmp/out'))
 def test_discovery_and_preflight_code_has_no_paid_or_production_side_effect(self):
  source=Path('tools/tldr_tts_calibration.py').read_text().lower();self.assertNotIn('r2storage',source);self.assertNotIn('generated/editorial',source);self.assertEqual(discover_models(models(),300)[0][2].model,'x-ai/grok-voice-tts-1.0')

if __name__=='__main__':unittest.main()
