"""Coordinate YouTube discovery with directly downloadable open footage."""
from pathlib import Path
import os
from .core import save_json
from . import youtube,open_footage,footage_verify
from .media_api import MediaAPI

def discover(script,directory,urls=()):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    yt=youtube.bounded(script,directory/"youtube",urls)
    combined={"assets":list(yt["assets"]),"scenes":{k:list(v) for k,v in yt["scenes"].items()},
              "provider_status":list(yt["provider_status"]),"inspection_reports":list(yt.get("inspection_reports",[]))}
    api=MediaAPI(directory.parent/"gemini")
    expected=sum(len(s["narration"].split()) for s in script["scenes"])/165*60
    supplied=sum(a.get("duration_seconds",0) for a in yt["assets"])
    direct={"summary":{}}
    if supplied<expected*.35:
        direct=open_footage.discover(api,script,directory/"open-footage",
                                    max_reviews=int(os.getenv("OPEN_FOOTAGE_REVIEW_LIMIT","8")))
        combined["assets"]+=direct["assets"]
        combined["provider_status"]+=direct["provider_status"]
        combined["inspection_reports"]+=direct.get("inspection_reports",[])
        for ident,ids in direct["scenes"].items():
            combined["scenes"].setdefault(ident,[]).extend(ids)
    acquired=list(combined["assets"])
    verified,checks=footage_verify.verify(api,acquired,directory/"excerpt-verification")
    ids={asset["id"] for asset in verified}
    combined["assets"]=verified
    combined["scenes"]={scene:[aid for aid in assigned if aid in ids] for scene,assigned in combined["scenes"].items()
                         if any(aid in ids for aid in assigned)}
    combined["excerpt_verification"]=checks
    combined["provider_status"]+=[{"provider":"Actual-excerpt inspection","source_id":row["asset_id"],
        "status":"available" if row["passed"] else "skipped","reason":row["reason"]} for row in checks]
    youtube_ids={asset["id"] for asset in yt["assets"]}
    yt_final=[asset for asset in verified if asset["id"] in youtube_ids]
    open_final=[asset for asset in verified if asset["id"] not in youtube_ids]
    def verified_summary(source,final):
        covered={str(asset.get("inspection",{}).get("scene_id")) for asset in final if asset.get("inspection",{}).get("scene_id") is not None}
        return {**source,"acquired_clips":source.get("accepted_clips",0),"acquired_seconds":source.get("accepted_seconds",0),
                "accepted_clips":len(final),"accepted_seconds":round(sum(asset.get("duration_seconds",0) for asset in final),2),
                "actual_excerpt_check":True,
                "scenes_with_footage":len(covered),
                "uncovered_scene_ids":[str(scene["scene_id"]) for scene in script["scenes"] if str(scene["scene_id"]) not in covered]}
    combined["summary"]={"youtube":verified_summary(yt.get("summary",{}),yt_final),
        "open_sources":verified_summary(direct.get("summary",{}),open_final),"acquired_clips":len(acquired),
        "accepted_clips":len(combined["assets"]),"accepted_seconds":round(sum(a.get("duration_seconds",0) for a in combined["assets"]),2),
        "scenes_with_footage":len(combined["scenes"]),"total_scenes":len(script["scenes"])}
    save_json(directory/"footage-research.json",combined)
    return combined
