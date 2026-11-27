"""Chapter-sized Gemini TTS, checked locally and split at aligned scene boundaries."""
from __future__ import annotations
import os,time,re
from pathlib import Path
from .core import PipelineError,duration,ffmpeg,key,read_json,save_json
from .script import CHAPTERS
from .speech import transcript,align_written,caption_groups
from .speech_verify import speech_check

def name_vocabulary(scenes):
 terms=[]
 for scene in scenes:
  # Supply proper-name vocabulary, never the expected narration, to the ASR.
  text=scene.get("asset_search_term","")+" "+scene.get("location","")
  terms.extend(re.findall(r"\b[A-Z][A-Za-zÀ-ÿ’'-]+\b",text))
 return ", ".join(dict.fromkeys(terms))[:500]

def produce(api,script,voice,directory):
 directory.mkdir(parents=True,exist_ok=True)
 identity=key('gemini-speech-v3-mastered',script,voice,os.getenv('GEMINI_TTS_MODEL','gemini-3.8-flash-tts'),os.getenv('GEMINI_SPEECH_STYLE','default'))
 index=directory/'speech.json'
 if index.exists():
  old=read_json(index)
  if old.get('fingerprint')==identity and all((directory/s['audio']).exists() for s in old['scenes']):return old
 from faster_whisper import WhisperModel
 recognizer=WhisperModel(os.getenv('WHISPER_MODEL','base.en'),device='cpu',compute_type='int8',cpu_threads=2,download_root=os.getenv('HF_HOME',str(directory.parent/'models'))+'/whisper')
 results=[];backup_recognizer=None
 for chapter in CHAPTERS:
  scenes=[s for s in script['scenes'] if s['chapter']==chapter];text=' '.join(s['narration'] for s in scenes)
  if len(text.split())>450:raise PipelineError('Chapter exceeds bounded TTS intake (450 words); reduce runtime')
  vocabulary=name_vocabulary(scenes)
  signature=key(identity,chapter,text);audio=directory/(signature+'.wav');checkpoint=directory/(signature+'.json')
  if checkpoint.exists() and audio.exists():record=read_json(checkpoint)
  else:
   print('Gemini narration: '+chapter,flush=True);started=time.monotonic()
   for attempt in range(2):
    meta=api.speech(text,voice,audio,attempt=attempt)
    cues,heard=transcript(audio,recognizer,vocabulary);check=speech_check(text,cues)
    base_check=dict(check)
    if not check["accepted"]:
     if backup_recognizer is None:
      backup_recognizer=WhisperModel("small.en",device="cpu",compute_type="int8",cpu_threads=2,download_root=os.getenv("HF_HOME",str(directory.parent/"models"))+"/whisper")
     cues,heard=transcript(audio,backup_recognizer,vocabulary);check=speech_check(text,cues)
     check["recognizer"]="small.en_with_name_vocabulary"
     check["first_recognizer_reason"]=base_check["reason"]
    save_json(directory/(signature+f'-asr-{attempt}.json'),{'cues':cues,'words':heard,'verification':check})
    if check['accepted']:break
    print(f'Gemini speech completeness retry: {chapter}: {check["reason"]}',flush=True)
   else:raise PipelineError(f'Gemini {chapter} speech failed verification after two takes. Checkpoint retained for inspection.')
   aligned=align_written(text,heard)
   record={'words':aligned,'duration':duration(audio),'verification':check,'generation_seconds':round(time.monotonic()-started,2),**meta}
   save_json(checkpoint,record)
  from .narration_audio import master
  mastered,mastering=master(audio,directory/"masters")
  # Split only at natural inter-word boundaries; keep the original recording too.
  cursor=0;start=0
  for i,scene in enumerate(scenes):
   count=len(scene['narration'].split());endword=cursor+count
   end=(record['words'][endword-1]['end']+record['words'][endword]['start'])/2 if i<len(scenes)-1 else record['duration']
   target=directory/f'scene-{scene["scene_id"]}-{signature}.wav'
   if not target.exists():ffmpeg('-ss',str(start),'-i',mastered,'-t',str(end-start),'-ar','24000','-ac','1','-c:a','pcm_s16le',target)
   words=[{**w,'start':max(0,w['start']-start),'end':min(end-start,max(.02,w['end']-start))} for w in record['words'][cursor:endword]]
   results.append({'scene_id':scene['scene_id'],'audio':target.name,'duration':duration(target),'words':words,'captions':caption_groups(words),'verification':record['verification'],'generation_seconds':record['generation_seconds'],'provider':'Gemini','model':record['model']})
   start=end;cursor=endword
 models=sorted({s["model"] for s in results})
 final={'fingerprint':identity,'voice':voice,'provider':'Gemini','model':models[0] if len(models)==1 else 'mixed_Gemini_TTS','models_used':models,'scenes':results}
 save_json(index,final);return final
