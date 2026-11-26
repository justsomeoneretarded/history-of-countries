"""Simple asset ordering with an optional single compact Gemini planning call."""
from pathlib import Path
import math
import os
from .core import PipelineError,key,read_json,save_json

VIDEO={"video","archival_video","modern_documentary_video"}

def validate_order(raw,script,media):
    rows=raw.get("scenes") if isinstance(raw,dict) else None
    if not isinstance(rows,list):raise PipelineError("Shot order needs a scenes array")
    found={}
    for row in rows:
        ident=str(row.get("scene_id",""))
        ids=row.get("asset_ids")
        if ident in found or not isinstance(ids,list) or not 1<=len(ids)<=8:raise PipelineError("Invalid or duplicate scene shot order")
        allowed=set(media["scenes"].get(ident,[]))
        if any(not isinstance(a,str) or a not in allowed for a in ids):raise PipelineError("Shot order selected unrelated/unapproved media")
        found[ident]=list(dict.fromkeys(ids))
    if set(found)!={str(s["scene_id"]) for s in script["scenes"]}:raise PipelineError("Shot order omitted or invented a scene")
    return found

def _local_order(script,media):
    records={a["id"]:a for a in media["assets"]}
    result={}
    for scene in script["scenes"]:
        ident=str(scene["scene_id"]);allowed=media["scenes"].get(ident,[])
        # Real moving footage first when its approved subject/date matches.
        result[ident]=sorted(allowed,key=lambda a:(records[a].get("medium") not in VIDEO,allowed.index(a)))
    return result

def make(api,script,speech,media,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    fingerprint=key("simple-order-v1",script,[s["duration"] for s in speech["scenes"]],
      [{k:a.get(k) for k in ("id","subject","date","context","sha256")} for a in media["assets"]],media["scenes"])
    path=directory/"storyboard.json"
    if path.exists():
        previous=read_json(path)
        if previous.get("fingerprint")==fingerprint:
            orders=validate_order(previous,script,media)
            return shots(script,speech,media,orders),previous
    orders=_local_order(script,media);mode="local_relevant_media";failure=None
    if api is not None:
        schema={"type":"object","required":["scenes"],"properties":{"scenes":{"type":"array","items":{
          "type":"object","required":["scene_id","asset_ids"],"properties":{"scene_id":{"type":"string"},
          "asset_ids":{"type":"array","items":{"type":"string"},"minItems":1,"maxItems":8}}}}}}
        payload={"scenes":[{"scene_id":str(s["scene_id"]),"narration":s["narration"],"date":s["date_label"],
          "allowed_asset_ids":media["scenes"][str(s["scene_id"])]} for s in script["scenes"]],
          "media":[{k:a.get(k) for k in ("id","subject","date","medium","context")} for a in media["assets"]]}
        try:
            raw=api.text("Order only the allowed real images and footage for each passage. Choose what is being spoken about, in the order it is spoken. Prefer relevant moving footage where date and subject match; use portraits for named people and surviving objects/places for ancient history. Do not treat modern views as contemporary footage of ancient events. Do not invent IDs, narration, or visual content. Return only JSON.",payload,schema,max_output=3500,
              model=os.getenv("GEMINI_PLANNER_MODEL","gemini-3.1-flash-lite"))
            orders=validate_order(raw,script,media);mode="Gemini_asset_order"
        except PipelineError as exc:
            # Simple editing remains possible using the same approved catalogue.
            failure=str(exc);print("Shot ordering uses the validated local catalogue: "+failure,flush=True)
    result={"fingerprint":fingerprint,"mode":mode,"model_error":failure,
            "scenes":[{"scene_id":ident,"asset_ids":ids} for ident,ids in orders.items()]}
    save_json(path,result)
    return shots(script,speech,media,orders),result

def shots(script,speech,media,orders,fps=30):
    spoken={str(s["scene_id"]):s for s in speech["scenes"]}
    records={a["id"]:a for a in media["assets"]}
    result=[];position=0.;cursor=0;previous=None
    for scene in script["scenes"]:
        ident=str(scene["scene_id"]);audio=spoken[ident]
        seconds=float(audio["duration"]);end=round((position+seconds)*fps);frame_count=end-cursor
        count=max(1,math.ceil(frame_count/(4.5*fps)))
        ids=orders.get(ident,[])
        if not ids:raise PipelineError("Missing media for scene "+ident)
        for index in range(count):
            begin=cursor+round(frame_count*index/count);finish=cursor+round(frame_count*(index+1)/count)
            length=(finish-begin)/fps
            options=ids[index%len(ids):]+ids[:index%len(ids)]
            available=[aid for aid in options if records[aid].get("medium") not in VIDEO or float(records[aid].get("duration_seconds",records[aid].get("duration",0)))>=length-.02]
            if not available:raise PipelineError("Approved video excerpts are shorter than the requested shot")
            aid=next((a for a in available if a!=previous),available[0]);previous=aid
            result.append({"scene_id":scene["scene_id"],"asset_id":aid,"global_start":begin/fps,
              "global_end":finish/fps,"frames":finish-begin,"chapter":scene["chapter"],
              "narration_context":scene["narration"],"year_label":scene["date_label"],
              "motion":("in","left","out","right")[(len(result))%4],
              "music_mood":"somber" if scene.get("bg_music_mood")=="reflective" else "tense" if scene.get("bg_music_mood")=="tense" else "neutral",
              "events":[],"source_start":0.})
        position+=seconds;cursor=end
    return result
