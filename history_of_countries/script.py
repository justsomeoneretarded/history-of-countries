from __future__ import annotations
import json
import re
from .core import PipelineError, save_json, read_json, key

CHAPTERS = ['Hook', 'Roots', 'Catalyst', 'Turning Point', 'Aftermath']
BANNED = ['delve', 'testament', 'tapestry', 'beacon', 'unravel', 'in conclusion', 'little did they know']
SCHEMA = '''Return ONLY an object {"title":str,"summary":str,"scenes":[{"scene_id":int,"chapter":str,"narration":str,"source_ids":[str],"asset_search_term":str,"visual_type":"artwork"|"map"|"photograph","location":str,"date_label":str,"subtitle_highlights":[str],"delivery":"normal"|"calm"|"dramatic","bg_music_mood":"tense"|"reflective"|"resolute"}]}.'''

def validate(script, source_ids, expected_words=None):
    scenes = script.get('scenes', [])
    if not 5 <= len(scenes) <= 150:
        raise PipelineError('Script needs 5–150 scenes')
    seen, ids, narration_words = [], set(), 0
    for scene in scenes:
        chapter = scene.get('chapter')
        if chapter not in CHAPTERS:
            raise PipelineError('Script contains an invalid chapter')
        if not seen or seen[-1] != chapter:
            seen.append(chapter)
        if not isinstance(scene.get('scene_id'), int) or scene['scene_id'] in ids:
            raise PipelineError('Scene IDs must be unique integers')
        ids.add(scene['scene_id'])
        text = scene.get('narration', '')
        if not isinstance(text, str) or not text.strip():
            raise PipelineError('Empty narration')
        if any(re.search(r'\b'+re.escape(word)+r'\b', text, re.I) for word in BANNED):
            raise PipelineError('Script contains a banned phrase')
        citations = scene.get('source_ids', [])
        if not citations or not set(citations) <= set(source_ids):
            raise PipelineError('Every scene must cite existing evidence IDs')
        if scene.get('visual_type') not in {'map','artwork','photograph'}:
            raise PipelineError('Invalid visual type')
        highlights = scene.get('subtitle_highlights', [])
        if not isinstance(highlights, list) or any(not isinstance(x,str) for x in highlights):
            raise PipelineError('Invalid subtitle highlights')
        if any(x.casefold() not in text.casefold() for x in highlights):
            raise PipelineError('Highlights must occur in narration')
        if scene.get('delivery', 'normal') not in {'normal','calm','dramatic'}:
            raise PipelineError('Invalid narration delivery')
        if len(text.split()) > 250:
            raise PipelineError('Split long scenes into smaller narrative beats')
        narration_words += len(text.split())
    if seen != CHAPTERS:
        raise PipelineError('Five chapters must appear once, in the requested order')
    if expected_words and not expected_words*.65 <= narration_words <= expected_words*1.35:
        raise PipelineError(f'Script length {narration_words} is outside target tolerance for {expected_words} words')
    return narration_words

def scene_schema(source_ids,total_words=None,scene_count=None):
    properties={
        'scene_id':{'type':'integer'},
        'chapter':{'type':'string','enum':CHAPTERS},
        'narration':{'type':'string'},
        'source_ids':{'type':'array','minItems':1,'items':{'type':'string','enum':sorted(source_ids)}},
        'asset_search_term':{'type':'string'},
        'visual_type':{'type':'string','enum':['artwork','map','photograph']},
        'location':{'type':'string'},
        'date_label':{'type':'string'},
        'subtitle_highlights':{'type':'array','items':{'type':'string'}},
        'delivery':{'type':'string','enum':['normal','calm','dramatic']},
        'bg_music_mood':{'type':'string','enum':['tense','reflective','resolute']},
    }
    if total_words and scene_count:
        per=total_words/scene_count
        properties['narration'].update(minLength=max(20,round(per*4.2)),maxLength=max(55,round(per*7.0)))
    scenes={'type':'array','items':{'type':'object','required':list(properties),'properties':properties}}
    if scene_count:scenes.update(minItems=scene_count,maxItems=scene_count)
    return {'type':'object','required':['title','summary','scenes'],'properties':{
        'title':{'type':'string'},'summary':{'type':'string'},
        'scenes':scenes}}


def normalize_script(script):
    """Normalize internal IDs and decorative emphasis, never narration or source claims."""
    for index,scene in enumerate(script.get('scenes',[]),1):
        scene['scene_id']=index
        text=scene.get('narration','')
        selected=[x for x in scene.get('subtitle_highlights',[]) if isinstance(x,str) and x.strip() and x.casefold() in text.casefold()]
        if not selected:
            selected=re.findall(r'\b(?:1[0-9]{3}|20[0-9]{2})\b',text)
            names=re.findall(r'\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,2}\b',text)
            common={'The','And','But','Yet','This','That','These','Those','When','After','Before','Their','They','For'}
            for name in names:
                words=name.split()
                if words[0] in common:words=words[1:]
                if words:selected.append(' '.join(words))
        scene['subtitle_highlights']=list(dict.fromkeys(selected))[:6]
    return script
