"""YouTube metadata and a readable, authentic-image thumbnail."""
import math,os,re
from pathlib import Path
from PIL import Image,ImageDraw,ImageOps
from .core import ROOT,PipelineError,read_json,save_json,key,ffmpeg

def original_metadata(script):
 ethiopia="ethiop" in script["title"].casefold()
 return {"title":script["title"][:100],
   "thumbnail_subject":"ETHIOPIA" if ethiopia else re.sub(r"^(?:The )?(?:Entire )?History of ","",script["title"],flags=re.I)[:40],
   "thumbnail_hook":"WHY ITALY LOST" if ethiopia else "THE ENTIRE HISTORY",
   "description":script.get("summary","")}

def normalize_metadata(raw,script):
 fields=("title","thumbnail_subject","thumbnail_hook","description")
 if not isinstance(raw,dict) or any(not isinstance(raw.get(k),str) or not raw[k].strip() for k in fields):
  raw=original_metadata(script)
 result={k:raw[k].strip() for k in fields}
 result["title"]=" ".join(result["title"].split())[:100]
 result["thumbnail_subject"]=" ".join(result["thumbnail_subject"].split()[:4])[:40]
 result["thumbnail_hook"]=" ".join(result["thumbnail_hook"].split()[:5])[:65]
 result["description"]=result["description"][:1200]
 return result

class PackagingAPI:
 def __init__(self,api,script):self.api=api;self.script=script
 def text(self,*args,**kwargs):
  if self.api is not None:
   try:return normalize_metadata(self.api.text(*args,**kwargs),self.script)
   except PipelineError as exc:print("Metadata uses original script fields: "+str(exc),flush=True)
  return normalize_metadata(original_metadata(self.script),self.script)

def compact_attribution(assets):
 """Group repeated author/license text; retain each work's title and source."""
 groups={}
 for asset in assets:
  group=(asset.get("creator") or "Creator identified on source page",asset["license"],asset.get("license_url",""))
  entry=(asset["subject"],asset["source_url"])
  if entry not in groups.setdefault(group,[]):groups[group].append(entry)
 return "\n\n".join(
  creator+" — "+license+("\n"+url if url else "")+"\n"+
  "\n".join(title+"\n"+source for title,source in works)
  for (creator,license,url),works in groups.items())

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
 metadata=normalize_metadata(metadata,source_script)
 metadata['fingerprint']=metadata_id;save_json(metadata_path,metadata)
 (output/'title.txt').write_text(metadata['title']+'\n')
 # Authentic large portrait/architecture: purposeful composition, no tiny icon collage.
 from .planning import VIDEO
 photos=[a for a in assets['assets'] if a.get('medium') not in VIDEO]
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
 # Attribution stays in the description; repeated author/license headers are
 # shared across works, with every work title and source URL preserved.
 required=[a for a in assets["assets"] if not any(x in a["license"].casefold() for x in ("public domain","cc0"))]
 changes="Historical images cropped, resized and panned; original media licenses apply."
 attribution=compact_attribution(required)
 description=full
 compacted=False;reference_links=True
 if len(description)>4900:
  compacted=True
  description=text+"\nSOURCES\n"+"\n".join(s["url"] for s in sources["sources"])+"\n\nVISUAL ATTRIBUTION\n"+changes+"\n"+attribution+"\n\nMUSIC\n"+music
 if len(description)>4900:
  # Factual reference links remain in the complete companion credits file.
  # Required image and music credits have priority in limited upload metadata.
  reference_links=False
  intro=metadata["description"][:240]+"\n\n"+"\n".join(chapters)+"\n"
  description=intro+"\nVISUAL ATTRIBUTION\n"+changes+"\n"+attribution+"\n\nMUSIC\n"+music
 if len(description)>4900:
  raise PipelineError(f"Required attribution is {len(description)} characters after grouping; YouTube allows 5000. Reduce distinct licensed works.")
 (output/"description.txt").write_text(description)
 checks={"passed":True,"title_characters":len(metadata["title"]),
   "description_characters":len(description),"description_budget":4900,
   "thumbnail_bytes":(output/"thumbnail.jpg").stat().st_size,
   "required_visual_attributions":len(required),"grouped_credits":compacted,
   "reference_links_in_description":reference_links,
   "complete_credits_file":"sources-and-credits.txt"}
 if checks["thumbnail_bytes"]>=2_000_000:raise PipelineError("Thumbnail exceeds YouTube's 2 MB limit")
 save_json(output/"package-checks.json",checks)
