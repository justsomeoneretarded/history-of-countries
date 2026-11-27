"""Simple asset ordering with an optional single compact Gemini planning call."""
from pathlib import Path
import math
import os
import re
from .core import PipelineError,key,read_json,save_json

VIDEO={"video","archival_video","modern_documentary_video"}

def validate_order(raw,script,media):
    rows=raw.get("scenes") if isinstance(raw,dict) else None
    if not isinstance(rows,list):raise PipelineError("Shot order needs a scenes array")
    found={}
    for row in rows:
        ident=str(row.get("scene_id",""))
        ids=row.get("asset_ids")
        if ident in found or not isinstance(ids,list) or not 1<=len(ids)<=24:raise PipelineError("Invalid or duplicate scene shot order")
        allowed=set(media["scenes"].get(ident,[]))
        if any(not isinstance(a,str) or a not in allowed for a in ids):raise PipelineError("Shot order selected unrelated/unapproved media")
        found[ident]=list(ids)
    if set(found)!={str(s["scene_id"]) for s in script["scenes"]}:raise PipelineError("Shot order omitted or invented a scene")
    return found

def repair_order(raw,script,media,fallback):
    """Keep valid Gemini choices; replace only missing or unapproved cues."""
    rows=raw.get("scenes") if isinstance(raw,dict) else None
    if not isinstance(rows,list):raise PipelineError("Shot order needs a scenes array")
    found={};repairs=[]
    for row in rows:
        if not isinstance(row,dict):raise PipelineError("Invalid shot-order row")
        ident=str(row.get("scene_id",""))
        if ident in found:raise PipelineError("Duplicate shot-order scene")
        found[ident]=row.get("asset_ids")
    result={}
    for scene in script["scenes"]:
        ident=str(scene["scene_id"]);base=fallback[ident];proposed=found.get(ident)
        allowed=set(media["scenes"][ident])
        if not isinstance(proposed,list) or len(proposed)!=len(base):
            result[ident]=list(base)
            repairs.append({"scene_id":ident,"reason":"missing_or_wrong_cue_count"})
            continue
        result[ident]=[]
        for index,aid in enumerate(proposed):
            if isinstance(aid,str) and aid in allowed:
                result[ident].append(aid)
            else:
                result[ident].append(base[index])
                repairs.append({"scene_id":ident,"cue":index,"reason":"unapproved_asset_id"})
    validate_order({"scenes":[{"scene_id":k,"asset_ids":v} for k,v in result.items()]},script,media)
    return result,repairs


def compact_ids(payload):
    """Short transport IDs save tokens; only this exact table can decode them."""
    aliases={a["id"]:"A"+str(i+1) for i,a in enumerate(payload["media"])}
    compact={**payload,
      "media":[{**a,"id":aliases[a["id"]]} for a in payload["media"]],
      "scenes":[{**row,"allowed_asset_ids":[aliases[aid] for aid in row["allowed_asset_ids"]]} for row in payload["scenes"]]}
    return compact,{short:original for original,short in aliases.items()}

def restore_ids(raw,aliases):
    if not isinstance(raw,dict) or not isinstance(raw.get("scenes"),list):return raw
    return {**raw,"scenes":[{**row,"asset_ids":[aliases.get(aid,aid) if isinstance(aid,str) else aid for aid in row["asset_ids"]]}
      if isinstance(row,dict) and isinstance(row.get("asset_ids"),list) else row for row in raw["scenes"]]}


def _cuts(spoken,fps=30,frames=None):
    frames=round(float(spoken["duration"])*fps) if frames is None else frames
    if frames<=6*fps:return [0,frames]
    boundaries=[0];words=spoken.get("words",[])
    while frames-boundaries[-1]>6*fps:
        start=boundaries[-1];desired=start+round(4.4*fps);candidates=[]
        for i,word in enumerate(words):
            end=round(float(word["end"])*fps)
            if not start+3*fps<=end<=min(start+6*fps,frames-3*fps):continue
            punct=bool(re.search(r"[.!?;:]$",word.get("word",word.get("text",""))))
            pause=float(words[i+1]["start"])-float(word["end"]) if i+1<len(words) else 0
            score=abs(end-desired)-(30 if punct else 14 if pause>.16 else 0)
            candidates.append((score,end))
        end=min(candidates)[1] if candidates else desired
        boundaries.append(min(max(start+3*fps,end),frames-3*fps))
    return boundaries+[frames]

def _cues(spoken):
    cuts=_cuts(spoken);words=spoken.get("words",[])
    return [{"index":i,"start":a/30,"end":b/30,"text":" ".join(w.get("word",w.get("text","")) for w in words
       if float(w["start"])<b/30 and float(w["end"])>a/30)}
       for i,(a,b) in enumerate(zip(cuts,cuts[1:]))]

def _local_order(script,media,speech):
    records={a["id"]:a for a in media["assets"]};by_id={str(s["scene_id"]):s for s in speech["scenes"]}
    result={}
    for scene in script["scenes"]:
        ident=str(scene["scene_id"]);allowed=media["scenes"].get(ident,[])
        if not allowed:raise PipelineError("Missing media for scene "+ident)
        sequence=[]
        for cue in _cues(by_id[ident]):
            terms=set(re.findall(r"[a-z]{4,}",cue["text"].casefold()))
            military=bool(terms&{"army","troops","columns","battle","advance","march","invading","attack"})
            def score(aid):
                asset=records[aid];title=asset.get("subject","").casefold()
                labels=set(re.findall(r"[a-z]{4,}",title+" "+" ".join(asset.get("tags",[]))))
                value=3*len(terms&labels)
                if military and asset.get("medium") in {"historical_artwork","archival_video"}:value+=4
                if asset.get("medium") in VIDEO:
                    value+=4
                    anchor=set(re.findall(r"[a-z]{4,}",asset.get("inspection",{}).get("narration_anchor","").casefold()))
                    if anchor:value+=5*len(terms&anchor)/max(1,len(terms))
                if asset.get("height"):
                    ratio=asset.get("width",0)/asset["height"]/(16/9)
                    if ratio>0:value+=1.2*min(ratio,1/ratio)
                if "portrait" in title and not terms&labels:value-=1
                return value
            sequence.append(max(allowed,key=score))
        result[ident]=sequence
    return result

def make(api,script,speech,media,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    fingerprint=key("simple-order-v6-inspected-footage",script,[s["duration"] for s in speech["scenes"]],
      [{k:a.get(k) for k in ("id","subject","date","context","sha256","width","height")} for a in media["assets"]],media["scenes"])
    path=directory/"storyboard.json"
    if path.exists():
        previous=read_json(path)
        if previous.get("fingerprint")==fingerprint:
            orders=validate_order(previous,script,media)
            return shots(script,speech,media,orders),previous
    orders=_local_order(script,media,speech);mode="local_relevant_media";failure=None;repairs=[]
    if api is not None:
        schema={"type":"object","required":["scenes"],"properties":{"scenes":{"type":"array","items":{
          "type":"object","required":["scene_id","asset_ids"],"properties":{"scene_id":{"type":"string"},
          "asset_ids":{"type":"array","items":{"type":"string"},"minItems":1,"maxItems":24}}}}}}
        spoken_by_id={str(s["scene_id"]):s for s in speech["scenes"]}
        payload={"scenes":[{"scene_id":str(s["scene_id"]),"narration":s["narration"],"date":s["date_label"],
          "shot_cues":_cues(spoken_by_id[str(s["scene_id"])]),
          "allowed_asset_ids":media["scenes"][str(s["scene_id"])]} for s in script["scenes"]],
          "media":[{k:a.get(k) for k in ("id","subject","date","medium","context","width","height","inspection","footage_presentation","duration_seconds")} for a in media["assets"]]}
        payload,aliases=compact_ids(payload)
        try:
            raw=api.text("Return exactly one allowed asset ID per shot_cue, in cue order, for every passage. Avoid an unchanged still beyond two cues when another equally relevant source exists. Use the inspected moving segments at their exact narration anchors; never substitute generic scenery just to increase a footage score. Match the words of each individual cue; do not just cycle portraits across an entire scene. Order only the allowed real images and footage for each passage. Choose what is being spoken about, in the order it is spoken. Prefer relevant moving footage where date and subject match. Prefer native widescreen views among equally relevant sources; all images are displayed whole, without artificial camera motion; use portraits for named people and surviving objects/places for ancient history. Do not treat modern views as contemporary footage of ancient events. Do not invent IDs, narration, or visual content. Return only JSON.",payload,schema,max_output=14000,
              model=os.getenv("GEMINI_PLANNER_MODEL","gemini-3.1-flash-lite"))
            raw=restore_ids(raw,aliases)
            orders,repairs=repair_order(raw,script,media,orders)
            mode="Gemini_spoken_cue_media_order" if not repairs else "Gemini_spoken_cue_media_order_repaired"
            if repairs:print(f"Preserved valid Gemini media choices; repaired {len(repairs)} cues/rows against approved media.",flush=True)
        except PipelineError as exc:
            # Simple editing remains possible using the same approved catalogue.
            failure=str(exc);print("Shot ordering uses the validated local catalogue: "+failure,flush=True)
    result={"fingerprint":fingerprint,"mode":mode,"model_error":failure,"repairs":repairs,
            "scenes":[{"scene_id":ident,"asset_ids":ids} for ident,ids in orders.items()]}
    save_json(path,result)
    return shots(script,speech,media,orders),result

def shots(script,speech,media,orders,fps=30):
    spoken={str(s["scene_id"]):s for s in speech["scenes"]}
    records={a["id"]:a for a in media["assets"]}
    result=[];position=0.;cursor=0;video_offsets={}
    for scene in script["scenes"]:
        ident=str(scene["scene_id"]);audio=spoken[ident]
        seconds=float(audio["duration"]);end=round((position+seconds)*fps);frame_count=end-cursor
        cuts=_cuts(audio,fps,frame_count);ids=orders.get(ident,[])
        if not ids:raise PipelineError("Missing media for scene "+ident)
        for index,(a,b) in enumerate(zip(cuts,cuts[1:])):
            begin=cursor+a;finish=cursor+b;length=(b-a)/fps
            options=ids[index%len(ids):]+ids[:index%len(ids)]
            options=list(dict.fromkeys(options+media.get("scenes",{}).get(ident,[])))
            def fresh(aid):
                asset=records[aid]
                return asset.get("medium") not in VIDEO or float(asset.get("duration_seconds",asset.get("duration",0)))-video_offsets.get(aid,0)>=length-.02
            available=[aid for aid in options if fresh(aid)]
            if not available:raise PipelineError("Approved excerpts do not cover this passage without restarting the same footage")
            aid=available[0];source_start=video_offsets.get(aid,0)
            if records[aid].get("medium") in VIDEO:video_offsets[aid]=source_start+length
            result.append({"scene_id":scene["scene_id"],"asset_id":aid,"global_start":begin/fps,
              "global_end":finish/fps,"frames":b-a,"chapter":scene["chapter"],
              "narration_context":scene["narration"],"year_label":scene["date_label"],
              "motion":"hold","source_crop":False,"side_fill":"subtle",
              "music_mood":"neutral" if scene["chapter"]=="Roots" else "somber" if scene.get("bg_music_mood")=="reflective" else "tense" if scene.get("bg_music_mood")=="tense" else "neutral",
              "events":[],"source_start":source_start})
        position+=seconds;cursor=end
    return result
