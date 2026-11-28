"""Coordinate YouTube discovery with directly downloadable open footage."""
from pathlib import Path
import os
from .core import save_json
from . import youtube,open_footage
from .media_api import MediaAPI

def discover(script,directory,urls=()):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    yt=youtube.bounded(script,directory/"youtube",urls)
    combined={"assets":list(yt["assets"]),"scenes":{k:list(v) for k,v in yt["scenes"].items()},
              "provider_status":list(yt["provider_status"]),"inspection_reports":list(yt.get("inspection_reports",[]))}
    expected=sum(len(s["narration"].split()) for s in script["scenes"])/165*60
    supplied=sum(a.get("duration_seconds",0) for a in yt["assets"])
    direct={"summary":{}}
    if supplied<expected*.35:
        api=MediaAPI(directory.parent/"gemini")
        direct=open_footage.discover(api,script,directory/"open-footage",
                                    max_reviews=int(os.getenv("OPEN_FOOTAGE_REVIEW_LIMIT","8")))
        combined["assets"]+=direct["assets"]
        combined["provider_status"]+=direct["provider_status"]
        combined["inspection_reports"]+=direct.get("inspection_reports",[])
        for ident,ids in direct["scenes"].items():
            combined["scenes"].setdefault(ident,[]).extend(ids)
    combined["summary"]={"youtube":yt.get("summary",{}),"open_sources":direct.get("summary",{}),
        "accepted_clips":len(combined["assets"]),"accepted_seconds":round(sum(a.get("duration_seconds",0) for a in combined["assets"]),2),
        "scenes_with_footage":len(combined["scenes"]),"total_scenes":len(script["scenes"])}
    save_json(directory/"footage-research.json",combined)
    return combined
