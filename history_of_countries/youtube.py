"""Bounded YouTube discovery. Download only explicit Creative Commons reuse."""
from pathlib import Path
import hashlib
import re
import time
import shutil
from itertools import islice
from urllib.parse import urlparse,parse_qs,urlencode
from .core import PipelineError,key,read_json,save_json,probe

def video_id(url):
    parsed=urlparse(url)
    host=(parsed.hostname or "").casefold()
    ident=parsed.path.strip("/") if host=="youtu.be" else parse_qs(parsed.query).get("v",[""])[0] if host in {"youtube.com","www.youtube.com","m.youtube.com"} else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}",ident):raise PipelineError("Supply a public YouTube watch URL")
    return ident

def search_url(query):
    # YouTube's Creative Commons search filter; each result is checked again.
    return "https://www.youtube.com/results?"+urlencode({"search_query":query,"sp":"EgIwAQ=="})

def reusable(info):
    license=str(info.get("license","")).casefold()
    return (bool(info.get("id")) and "creative commons" in license and
            "attribution" in license and not any(x in license for x in ("noncommercial","non-commercial","no derivatives")) and
            not info.get("is_live") and info.get("availability") not in {"private","premium_only","subscriber_only"} and
            not info.get("has_drm"))

def related(info,scene):
    """Require a named subject and, for dated archive, a matching period."""
    text=(str(info.get("title",""))+" "+str(info.get("description",""))[:1800]).casefold()
    query=scene.get("asset_search_term","")
    words={w.casefold() for w in re.findall(r"[A-Za-z]{4,}",query)}
    words-= {"historical","history","footage","archive","archival","scene","painting","image","photograph","ethiopian","ethiopia","ancient","medieval","modern","military"}
    if not words or not words.intersection(set(re.findall(r"[a-z]{4,}",text))):return False
    years={int(x) for x in re.findall(r"\b(?:18|19|20)\d{2}\b",str(info.get("title","")))}
    spoken={int(x) for x in re.findall(r"\b(?:18|19|20)\d{2}\b",scene.get("date_label","")+" "+scene.get("narration",""))}
    if years and spoken and min(abs(a-b) for a in years for b in spoken)>5:return False
    if years and not spoken:return False
    # Undated scenic footage can illustrate surviving places, not a named war.
    if not years and re.search(r"\b(?:war|battle|invasion|famine|terror|massacre)\b",scene.get("narration",""),re.I):return False
    return True

def discover(script,directory,urls=(),max_queries=3,max_clips=5,ydl_factory=None):
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import download_range_func
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    factory=ydl_factory or YoutubeDL
    assets=[];assignments={};status=[];seen=set();started=time.monotonic()
    options={"quiet":True,"no_warnings":True,"noplaylist":True,"socket_timeout":12,
             "retries":1,"extractor_retries":1,"skip_download":True,"ignoreerrors":False,
             "ignore_no_formats_error":True,"playlistend":5,"lazy_playlist":True}
    node=shutil.which("node")
    if node:options["js_runtimes"]={"node":{"path":node}}
    jobs=[("https://www.youtube.com/watch?v="+video_id(u),None) for u in list(urls)[:8]]
    eligible=[];decades=set()
    for scene in script["scenes"]:
        years=[int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b",scene.get("date_label",""))]
        if years and years[0]//10 not in decades:
            eligible.append(scene);decades.add(years[0]//10)
    if not eligible:eligible=script["scenes"]
    country=re.sub(r"^(?:the\s+)?(?:entire\s+)?history\s+of\s+","",script.get("title",""),flags=re.I).split(":")[0]
    # Broad country/year searches find archive releases that do not repeat a
    # scriptwriter's long scene query. Include surviving-landmark footage too.
    places=[s for s in script["scenes"] if re.search(r"\b(?:lalibela|stelae|temple|castle|ruins|pyramid|cathedral|palace)\b",s.get("asset_search_term",""),re.I)]
    selected=eligible[:max_queries-1]+places[:1] if places else eligible[:max_queries]
    for scene in selected:
        year=re.search(r"\b(?:19|20)\d{2}\b",scene.get("date_label",""))
        query=country+" "+year[0] if year else scene["asset_search_term"]
        jobs.append((search_url(query),scene))
    for query,requested_scene in jobs:
        if len(assets)>=max_clips or time.monotonic()-started>180:break
        try:
            settings={**options,**({"extract_flat":"in_playlist"} if requested_scene is not None else {})}
            with factory(settings) as ydl:raw=ydl.extract_info(query,download=False)
            candidates=islice(raw.get("entries") or [],5) if raw and "entries" in raw else [raw]
            count_before=len(assets);candidate_count=0
            for info in candidates:
                candidate_count+=1
                if not isinstance(info,dict) or info.get("id") in seen:continue
                if requested_scene is not None:
                    try:
                        with factory(options) as ydl:info=ydl.extract_info("https://www.youtube.com/watch?v="+info["id"],download=False)
                    except Exception as exc:
                        status.append({"video_id":info.get("id"),"status":"unavailable","reason":type(exc).__name__});continue
                    if not isinstance(info,dict):continue
                seen.add(info.get("id"))
                if not reusable(info):
                    status.append({"video_id":info.get("id"),"status":"skipped","reason":"Explicit reusable CC BY license not established"});continue
                matches=[s for s in script["scenes"] if related(info,s)]
                if not matches:
                    status.append({"video_id":info["id"],"status":"skipped","reason":"Subject/date did not match the spoken story"});continue
                total=float(info.get("duration") or 0)
                if total<4:continue
                beginning=min(8.,max(0.,total-10.));end=min(total,beginning+12.)
                ident="youtube-"+info["id"];path=directory/(ident+".mp4")
                if not path.exists():
                    settings={**options,"skip_download":False,
                      "format":"bestvideo[ext=mp4][height<=1080]/best[ext=mp4][height<=1080]/bestvideo[height<=1080]/best[height<=1080]",
                      "outtmpl":str(directory/(ident+".%(ext)s")),"merge_output_format":"mp4",
                      "download_ranges":download_range_func(None,[(beginning,end)]),
                      "force_keyframes_at_cuts":True,"max_filesize":200*1024*1024}
                    with factory(settings) as ydl:ydl.download(["https://www.youtube.com/watch?v="+info["id"]])
                    alternatives=list(directory.glob(ident+".*"))
                    actual=next((p for p in alternatives if p.suffix in {".mp4",".webm",".mkv"}),None)
                    if actual is None:raise PipelineError("YouTube did not produce a usable excerpt")
                    path=actual
                metadata=probe(path)
                if not any(s["codec_type"]=="video" for s in metadata["streams"]):raise PipelineError("YouTube excerpt has no video")
                record={"id":ident,"path":str(path.resolve()),"subject":info["title"],"title":info["title"],
                  "date":"Dates/context as supplied by uploader; matched to scene before use",
                  "medium":"video","provider":"YouTube Creative Commons","license":"CC BY 3.0",
                  "license_url":"https://creativecommons.org/licenses/by/3.0/",
                  "source_url":"https://www.youtube.com/watch?v="+info["id"],
                  "creator":info.get("uploader") or info.get("channel") or "YouTube uploader",
                  "context":info.get("description","")[:500],"source_start_seconds":beginning,
                  "duration_seconds":float(metadata["format"]["duration"]),
                  "sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
                assets.append(record)
                for scene in matches:assignments.setdefault(str(scene["scene_id"]),[]).append(ident)
                status.append({"video_id":info["id"],"status":"available","scene_ids":[s["scene_id"] for s in matches]})
                if len(assets)>=max_clips:break
            if requested_scene is not None:
                status.append({"provider":"YouTube","query":query,"status":"searched",
                  "candidate_count":candidate_count,"accepted_clips":len(assets)-count_before})
        except Exception as exc:
            status.append({"query":query,"status":"unavailable","reason":type(exc).__name__})
    report={"assets":assets,"scenes":assignments,"provider_status":status,
      "note":"YouTube can reject hosted-runner downloads. No login, DRM, or standard-license bypass is attempted. Available archive photographs/footage remain usable."}
    save_json(directory/"discovery.json",report);return report


def bounded(script,directory,urls=(),timeout=240):
    """Kill a stalled extractor and its FFmpeg children after the whole deadline."""
    import os,signal,subprocess,sys
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    request=directory/"request.json";save_json(request,{"script":script,"urls":list(urls)})
    process=subprocess.Popen([sys.executable,"-m","history_of_countries.youtube","--request",str(request),"--output",str(directory)],
                             start_new_session=True)
    try:
        code=process.wait(timeout=timeout)
        if code==0 and (directory/"discovery.json").exists():return read_json(directory/"discovery.json")
        reason="extractor_process_failed"
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGTERM)
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.wait()
        reason="whole_discovery_deadline"
    result={"assets":[],"scenes":{},"provider_status":[{"provider":"YouTube","status":"unavailable","reason":reason}]}
    save_json(directory/"discovery.json",result);return result

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--request",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    request=read_json(args.request)
    discover(request["script"],args.output,request.get("urls",[]))
