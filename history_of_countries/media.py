"""Relevant archive selection, Commons discovery and optional YouTube excerpts."""
from pathlib import Path
import html
import hashlib
import re
import time
import requests
from .core import ROOT,PipelineError,key,read_json,save_json
from .documentary_assets import catalog,_download_image
from .generic_assets import subject_terms,GENERIC_SUBJECT
from . import youtube

def clean(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>"," ",str(text))).split())

def allowed_license(label):
    text=label.casefold().strip()
    return ("public domain" in text or "cc0" in text or
            bool(re.match(r"cc by(?:-sa)? \d",text))) and not any(x in text for x in ("-nc","-nd","noncommercial","non-commercial","no derivatives"))

def country_name(title):
    return re.sub(r"^(?:the\s+)?(?:entire\s+)?history\s+of\s+","",title,flags=re.I).split(":")[0].strip()

def commons(script,directory,current,session=None,max_queries=20):
    directory=Path(directory)/"commons";directory.mkdir(parents=True,exist_ok=True)
    session=session or requests.Session()
    session.headers.update({"User-Agent":"HistoryOfCountries/1.0 (licensed documentary media)"})
    assets=[];mapping={};status=[];seen=set();queries=0
    deadline=time.monotonic()+240
    country=country_name(script["title"])
    for scene in script["scenes"]:
        ident=str(scene["scene_id"])
        if len(current.get(ident,[]))>=3:continue
        if queries>=max_queries or time.monotonic()>deadline:break
        query=(scene.get("asset_search_term") or scene.get("location") or country).strip()
        # A named cross-border event must not be over-restricted by the title country.
        params={"action":"query","format":"json","formatversion":2,"generator":"search",
          "gsrsearch":query+" filetype:bitmap","gsrnamespace":6,"gsrlimit":5,
          "prop":"imageinfo","iiprop":"url|extmetadata","iiurlwidth":1920}
        cache=directory/(key(params)+".json")
        try:
            if cache.exists():raw=read_json(cache)
            else:
                queries+=1
                response=session.get("https://commons.wikimedia.org/w/api.php",params=params,timeout=(8,20))
                response.raise_for_status();raw=response.json();save_json(cache,raw)
            for page in raw.get("query",{}).get("pages",[]):
                info=(page.get("imageinfo") or [{}])[0];meta=info.get("extmetadata",{})
                value=lambda k:clean(meta.get(k,{}).get("value",""))
                license=value("LicenseShortName")
                if not allowed_license(license):continue
                title=clean(page.get("title","")).removeprefix("File:")
                description=value("ImageDescription")
                if re.search(r"\b(?:montage|collage|contact sheet)\b",title,re.I):continue
                matching=subject_terms(title+" "+description)
                required=subject_terms(scene.get("asset_search_term",""))-GENERIC_SUBJECT
                if required and len(required&matching)<min(2,len(required)):continue
                aid="commons-"+str(page["pageid"])
                if aid not in seen:
                    target=directory/(aid+".jpg")
                    _download_image(session,info.get("thumburl") or info["url"],target)
                    record={"id":aid,"path":str(target.resolve()),"subject":title,"title":title,
                      "date":value("DateTimeOriginal") or "Date not supplied",
                      "medium":"historical_artwork" if re.search(r"paint|manuscript|engraving",title+" "+description,re.I) else "documentary_photo",
                      "license":license,"license_url":value("LicenseUrl"),
                      "source_url":"https://commons.wikimedia.org/?curid="+str(page["pageid"]),
                      "creator":value("Artist") or "Creator identified on the source page",
                      "provider":"Wikimedia Commons","context":description[:650],
                      "tags":sorted(required&matching)}
                    assets.append(record);seen.add(aid)
                mapping.setdefault(ident,[]).append(aid)
                if len(mapping[ident])>=3:break
            status.append({"provider":"Wikimedia Commons","query":query,"accepted":len(mapping.get(ident,[]))})
        except (requests.RequestException,ValueError,KeyError,OSError) as exc:
            status.append({"provider":"Wikimedia Commons","query":query,"status":"unavailable","reason":type(exc).__name__})
    return {"assets":assets,"scenes":mapping,"provider_status":status}

def build(script,directory,use_youtube=True,youtube_urls=(),fetch=True):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    result=catalog(script,directory,fetch=fetch)
    if fetch:
        _merge(result,curated(script,directory))
        extra=commons(script,directory,result["scenes"])
        _merge(result,extra)
        missing=[s for s in script["scenes"] if not result["scenes"].get(str(s["scene_id"]))]
        if missing:
            contextual={**script,"scenes":[{**s,"asset_search_term":(s.get("location","").split(" and ")[0] or country_name(script["title"]))} for s in missing]}
            _merge(result,commons(contextual,directory/"context",{},max_queries=8))
        if use_youtube:_merge(result,youtube.bounded(script,directory/"youtube",youtube_urls))
    # Every spoken scene must have real relevant media. No generated placeholder.
    missing=[s["scene_id"] for s in script["scenes"] if not result["scenes"].get(str(s["scene_id"]))]
    for asset in result["assets"]:
        asset["sha256"]=hashlib.sha256(Path(asset["path"]).read_bytes()).hexdigest()
    save_json(directory/"media.json",result)
    if missing:raise PipelineError("No relevant reusable media for scenes "+", ".join(map(str,missing))+". See work/media/media.json; add licensed URLs or refine those searches.")
    return result

def _merge(target,extra):
    known={a["id"] for a in target["assets"]}
    target["assets"].extend(a for a in extra["assets"] if a["id"] not in known)
    for ident,ids in extra["scenes"].items():
        target["scenes"][ident]=list(dict.fromkeys(target["scenes"].get(ident,[])+ids))
    target["provider_status"].extend(extra["provider_status"])


def curated(script,directory):
    path=ROOT/"assets/curation/extra.json"
    result={"assets":[],"scenes":{},"provider_status":[]}
    if not path.exists():return result
    session=requests.Session()
    session.headers.update({"User-Agent":"HistoryOfCountries/1.0 (https://github.com/justsomeoneretarded/history-of-countries)"})
    for row in read_json(path):
        matches=[s for s in script["scenes"] if all(t in s["narration"].casefold() for t in row["required_terms"]) and row["required_year"] in s.get("date_label","")]
        if not matches:continue
        try:
            target=Path(directory)/"curated"/(row["id"]+".jpg")
            _download_image(session,row["image_url"],target)
            result["assets"].append({**row,"path":str(target.resolve()),"provider":"Curated reusable historical media"})
            for scene in matches:result["scenes"].setdefault(str(scene["scene_id"]),[]).append(row["id"])
            result["provider_status"].append({"provider":"Curated media","id":row["id"],"status":"available"})
        except (requests.RequestException,ValueError,KeyError,OSError) as exc:
            result["provider_status"].append({"provider":"Curated media","id":row["id"],"status":"unavailable","reason":type(exc).__name__})
    return result
