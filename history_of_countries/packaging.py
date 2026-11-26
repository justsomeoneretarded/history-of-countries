"""YouTube metadata and a readable, authentic-image thumbnail."""
import math,os,re
from PIL import Image,ImageDraw,ImageOps
from .core import ROOT,PipelineError,read_json,save_json,key,ffmpeg

class PackagingAPI:
 def __init__(self,api,script):self.api=api;self.script=script
 def text(self,*args,**kwargs):
  if self.api is not None:
   try:return self.api.text(*args,**kwargs)
   except PipelineError as exc:print("Metadata uses original script fields: "+str(exc),flush=True)
  ethiopia="ethiop" in self.script["title"].casefold()
  return {"title":self.script["title"][:100],"thumbnail_subject":"ETHIOPIA" if ethiopia else re.sub(r"^(?:The )?(?:Entire )?History of ","",self.script["title"],flags=re.I)[:40],
   "thumbnail_hook":"WHY ITALY LOST" if ethiopia else "THE ENTIRE HISTORY",
   "description":self.script.get("summary","")}

def package(api,script,speech,assets,output,work):
 api=PackagingAPI(api,script)
 from .typography import font
 save_json(output/'script.json',script);save_json(output/'media-credits.json',assets)
 (output/'script.txt').write_text('\n\n'.join(s['chapter'].upper()+'\n'+s['narration'] for s in script['scenes']))
 metadata_path=work/'directed-packaging.json'
 source_script=read_json(work/'script.json') if (work/'script.json').exists() else script
 metadata_id=key('directed-packaging-v4-concrete-hook-and-portrait',source_script['title'],[s['narration'] for s in source_script['scenes']])
 metadata_schema={'type':'object','required':['title','thumbnail_subject','thumbnail_hook','description'], 'properties':{'title':{'type':'string'},'thumbnail_subject':{'type':'string'},'thumbnail_hook':{'type':'string'},'description':{'type':'string'}}}
 previous=read_json(metadata_path) if metadata_path.exists() else {}
 metadata=previous if previous.get('fingerprint')==metadata_id else api.text(
  'Package this original history video for YouTube. Return a searchable title of at most100characters, thumbnail_subject naming the actual entity in1–4words, a concrete truthful thumbnail curiosity hook of2–4short words (not the full title), and a concise description of the actual scope and endpoint. No fake quotes, sensational invented claims, marketing filler, channel branding or technical implementation details. The hook must name a concrete choice, reversal or unanswered question, not an abstract theme heading such as Power and Sovereignty. It should be readily legible on a mobile thumbnail. If the supplied film is about Ethiopia, focus on why Italy lost at Adwa while acknowledging that the whole film also covers later occupation and revolution. Do not imply a country was never conquered or occupied when this film covers an occupation. Do not copy any reference title.',
  {'working_title':source_script['title'],'summary':source_script['summary'],'opening':source_script['scenes'][0]['narration'],'ending':source_script['scenes'][-1]['narration'],'scope':[{'date':s['date_label'],'passage':s['narration'][:180]} for s in source_script['scenes']]},metadata_schema,max_output=1200,model=os.getenv('GEMINI_PACKAGE_MODEL','gemini-3.5-flash-lite'))
 if 'ethiop' in source_script['title'].casefold() and re.search(r'never (?:colon[izs]+ed|conquered|occupied)|unconquered',metadata['thumbnail_hook'],re.I):metadata['thumbnail_hook']='AN EMPIRE REFUSES'
 if 'ethiop' in source_script['title'].casefold():
  metadata['thumbnail_subject']='ETHIOPIA'
  if re.search(r'\b(?:power|sovereignty|legacy|journey)\b',metadata['thumbnail_hook'],re.I):
   metadata['thumbnail_hook']='WHEN ITALY LOST'
 metadata['fingerprint']=metadata_id;save_json(metadata_path,metadata)
 (output/'title.txt').write_text(metadata['title']+'\n')
 # Authentic large portrait/architecture: purposeful composition, no tiny icon collage.
 photos=[a for a in assets['assets'] if a.get('medium') not in ('video','archival_video')]
 subjects=sorted(photos,key=lambda a:('menelik' not in a.get('subject','').lower(), 'adwa' not in a.get('subject','').lower()))
 im=Image.new('RGB',(1280,720),'#102934')
 if subjects:
  p=Path(subjects[0]['path']);p=p if p.is_absolute() else ROOT/p
  with Image.open(p) as picture:
   portrait=picture.convert('RGB')
   if 'ethiop' in source_script['title'].casefold() and 'menelik' in subjects[0].get('subject','').casefold():
    # Deliberately crop the identified full-length portrait to head/shoulders.
    w,h=portrait.size;portrait=portrait.crop((round(w*.12),0,round(w*.92),round(h*.62)))
   im.paste(ImageOps.fit(portrait,(760,720),centering=(.5,.3)),(520,0))
 elif (output/'final.mp4').exists():
  still=output/'thumbnail-art.jpg';ffmpeg('-ss','2','-i',output/'final.mp4','-frames:v','1',still)
  with Image.open(still) as picture:im.paste(ImageOps.fit(picture.convert('RGB'),(760,720),centering=(.6,.4)),(520,0))
 shade=Image.new('RGBA',im.size)
 d=ImageDraw.Draw(shade)
 for x in range(1280):d.line((x,0,x,720),fill=(9,27,34,255 if x<420 else max(0,255-int((x-420)*.6))))
 im=Image.alpha_composite(im.convert('RGBA'),shade);d=ImageDraw.Draw(im)
 topic=re.sub(r'^(?:the\s+)?(?:entire\s+)?history\s+of\s+','',source_script['title'],flags=re.I)
 title=str(metadata.get('thumbnail_subject') or topic.split(':')[0]).upper().strip()
 size=76
 while size>28 and d.textlength(title,font=font(size,True))>580:size-=2
 d.text((58,115),title,font=font(size,True),fill='#F4D588')
 words=metadata['thumbnail_hook'].upper().split()[:5];middle=max(1,math.ceil(len(words)/2))
 for i,line in enumerate([' '.join(words[:middle]),' '.join(words[middle:])]):
  size=88
  while size>36 and d.textlength(line,font=font(size,True))>620:size-=2
  d.text((58,255+i*105),line,font=font(size,True),fill='white')
 im.convert('RGB').save(output/'thumbnail.jpg',quality=95)
 chapters=[];position=0;seen=set()
 for scene,spoken in zip(script['scenes'],speech['scenes']):
  if scene['chapter'] not in seen:
   seen.add(scene['chapter']);n=int(position);chapters.append(f'{n//60:02}:{n%60:02} {scene["chapter"]}')
  position+=spoken['duration']
 text=metadata['description']+'\n\n'+'\n'.join(chapters)+'\n\nOriginal narration with licensed historical photographs and footage.\n'
 credits='\n\n'.join(f'{a["subject"]} — {a.get("creator","Historical archive")} — {a["license"]}\n{a["source_url"]}\n{a.get("license_url","")}' for a in assets['assets'])
 sources=read_json(output/'sources.json') if (output/'sources.json').exists() else {'sources':[]}
 evidence='\n'.join(s['title']+'\n'+s['url'] for s in sources['sources'])
 music=(output/'music-credits.txt').read_text() if (output/'music-credits.txt').exists() else ''
 full=text+'\nSOURCES\n'+evidence+'\n\nHISTORICAL MEDIA\n'+credits+'\n\nMUSIC\n'+music
 (output/'sources-and-credits.txt').write_text(full)
 # Attribution must remain accessible in upload metadata; no in-frame credit clutter.
 description=full
 if len(description)>4900:
  # PD/CC0 attribution is retained in full delivery credits; preserve required CC BY attribution in upload metadata.
  required=[a for a in assets['assets'] if not any(x in a['license'].casefold() for x in ['public domain','cc0'])]
  compact='\n\n'.join(f'{a["subject"]} — {a.get("creator","Historical archive")} — {a["license"]}\n{a["source_url"]}\n{a.get("license_url","")}' for a in required)
  description=text+'\nSOURCES\n'+'\n'.join(s['url'] for s in sources['sources'])+'\n\nVISUAL ATTRIBUTION\n'+compact+'\n\nMUSIC\n'+music
 if len(description)>4900:raise PipelineError('Required attribution exceeds YouTube description budget; reduce used CC BY assets')
 (output/'description.txt').write_text(description)
