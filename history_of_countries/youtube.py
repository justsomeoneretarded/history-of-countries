"""Deep, checkpointed YouTube research; only inspected reusable footage is accepted."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from dataclasses import replace
import hashlib
import os
import re
import shutil
import time
from itertools import islice
from urllib.parse import urlparse,parse_qs,urlencode
from .core import PipelineError,key,read_json,save_json,probe
from .footage_search import Limits,VERSION,context,related,plan_queries,fair_shortlist
from .gemini import QuotaDeferred

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


class AccessLog:
    def __init__(self):self.auth_required=False
    def debug(self,message):pass
    def warning(self,message):
        if re.search(r"sign in to confirm|not a bot|authentication required|login required",str(message),re.I):
            self.auth_required=True
    def error(self,message):self.warning(message)

def _options():
    result={"quiet":True,"no_warnings":True,"noplaylist":True,"socket_timeout":12,
            "retries":1,"extractor_retries":1,"skip_download":True,"ignoreerrors":False,
            "ignore_no_formats_error":True,"lazy_playlist":True}
    node=shutil.which("node")
    if node:result["js_runtimes"]={"node":{"path":node}}
    return result

def download_excerpt(info,start,end,target,height=1080,ydl_factory=None):
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import download_range_func
    from .core import ffmpeg
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        try:
            meta=probe(target)
            if abs(float(meta["format"]["duration"])-(end-start))<1:return target
        except (PipelineError,ValueError,KeyError):pass
        target.unlink(missing_ok=True)
    factory=ydl_factory or YoutubeDL
    selector=lambda cap:f"bestvideo[ext=mp4][height<={cap}]/best[ext=mp4][height<={cap}]/bestvideo[height<={cap}]/best[height<={cap}]"
    settings={**_options(),"skip_download":False,"format":selector(height),
              "outtmpl":str(target.with_suffix(".%(ext)s")),"merge_output_format":"mp4",
              "download_ranges":download_range_func(None,[(start,end)]),"force_keyframes_at_cuts":True,
              "external_downloader_args":{"ffmpeg_i":["-rw_timeout","15000000"]}}
    access=AccessLog();settings["logger"]=access
    method="range_download";range_error=None
    try:
        with factory(settings) as ydl:ydl.download(["https://www.youtube.com/watch?v="+info["id"]])
        actual=next((p for p in target.parent.glob(target.stem+".*") if p.suffix in {".mp4",".webm",".mkv"} and p.stat().st_size>0),None)
        if actual is None:raise PipelineError("YouTube did not produce an excerpt")
        if actual.stat().st_size>180*1024*1024:raise PipelineError("Excerpt exceeded the local size budget")
        if actual!=target:
            ffmpeg("-i",actual,"-an","-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",target,timeout=180)
            actual.unlink()
        meta=probe(target)
        if float(meta["format"]["duration"])<end-start-.35:raise PipelineError("Range excerpt is truncated")
    except Exception as exc:
        if access.auth_required:raise PipelineError("YouTube requested authentication on this runner; download not attempted further") from None
        range_error=type(exc).__name__
        # yt-dlp's native whole-file path can work when FFmpeg HTTP range requests fail.
        # Bound duration, bytes and elapsed download time independently.
        if not 6<=float(info.get("duration") or 0)<=1800:
            raise PipelineError("Range download unavailable; source exceeds whole-file fallback duration") from None
        target.unlink(missing_ok=True)
        cache=target.parent.parent/"source-cache";cache.mkdir(parents=True,exist_ok=True)
        source=next((p for p in cache.glob(info["id"]+".*") if p.suffix in {".mp4",".webm",".mkv"} and p.stat().st_size>0),None)
        if source is None:
            begun=time.monotonic()
            def bounded_progress(event):
                if event.get("downloaded_bytes",0)>180*1024*1024 or time.monotonic()-begun>180:
                    raise PipelineError("Whole-source fallback exceeded its byte/time budget")
            whole={**_options(),"skip_download":False,"format":selector(min(height,720)),
                   "outtmpl":str(cache/(info["id"]+".%(ext)s")),"merge_output_format":"mp4",
                   "max_filesize":180*1024*1024,"progress_hooks":[bounded_progress],
                   "fragment_retries":1,"concurrent_fragment_downloads":1}
            with factory(whole) as ydl:ydl.download(["https://www.youtube.com/watch?v="+info["id"]])
            source=next((p for p in cache.glob(info["id"]+".*") if p.suffix in {".mp4",".webm",".mkv"} and p.stat().st_size>0),None)
        if source is None or source.stat().st_size>180*1024*1024:
            raise PipelineError("Whole-source fallback did not produce bounded media")
        ffmpeg("-ss",str(start),"-i",source,"-t",str(end-start),"-an","-c:v","libx264",
               "-preset","veryfast","-crf","20","-pix_fmt","yuv420p","-movflags","+faststart",target,timeout=180)
        method="native_whole_download_then_local_cut"
    meta=probe(target)
    stream=next((s for s in meta["streams"] if s.get("codec_type")=="video"),None)
    if stream is None:raise PipelineError("Excerpt has no decodable video")
    if float(meta["format"]["duration"])<end-start-.35:raise PipelineError("Downloaded excerpt is truncated")
    if int(stream.get("width",0))<480 or int(stream.get("height",0))<270:raise PipelineError("Excerpt resolution is too low")
    save_json(target.with_suffix(".acquisition.json"),{"method":method,"range_error":range_error,
              "source_id":info["id"],"start":start,"end":end})
    return target

def discover(script,directory,urls=(),max_queries=None,max_clips=None,ydl_factory=None,api=None,limits=None,reviewer=None):
    from yt_dlp import YoutubeDL
    from .footage_review import inspect
    from .media_api import MediaAPI
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    limits=limits or Limits.environment()
    if max_queries is not None:limits=replace(limits,max_queries=max_queries)
    if max_clips is not None:limits=replace(limits,max_clips=max_clips)
    factory=ydl_factory or YoutubeDL
    if api is None and (os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY")):
        api=MediaAPI(directory.parent.parent/"gemini")
    started=time.monotonic();deadline=started+limits.total_seconds
    # An explicit sign-in challenge is an access boundary, not a reason to try other clients.
    access=AccessLog()
    try:
        test_url=list(urls)[0] if urls else "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
        with factory({**_options(),"logger":access}) as ydl:ydl.extract_info(test_url,download=False)
    except Exception:pass
    if access.auth_required:
        result={"version":VERSION,"script_fingerprint":key(script),"assets":[],"scenes":{},
                "provider_status":[{"provider":"YouTube","status":"unavailable","reason":"authentication_required_on_hosted_runner"}],
                "summary":{"planned_queries":0,"attempted_queries":0,"accepted_clips":0,"accepted_seconds":0,
                           "video_reviews_started":0,"authentication_blocked_candidates":1,
                           "search_skipped_reason":"authentication_required_on_hosted_runner",
                           "capacity_results":limits.max_queries*limits.results_per_query},
                "inspection_reports":[]}
        save_json(directory/"discovery.json",result)
        print("YouTube requires sign-in on this runner; using direct open footage without bypassing the challenge.",flush=True)
        return result
    queries,plan=plan_queries(api,script,directory,limits)
    assets=[];assignments={};status=[];candidates={};metadata=[];reviews=[]
    counters={"planned_queries":len(queries),"attempted_queries":0,"cached_queries":0,"search_result_rows":0,
              "unique_candidates":0,"metadata_inspected":0,"eligible_cc_candidates":0,
              "video_reviews_started":0,"video_reviews_completed":0}
    def checkpoint():
        summary={**counters,"accepted_clips":len(assets),
                 "accepted_seconds":round(sum(a.get("duration_seconds",0) for a in assets),2),
                 "scenes_with_footage":len(assignments),"total_scenes":len(script["scenes"]),
                 "capacity_results":plan["capacity_results"],"legacy_capacity_results":15,
                 "elapsed_seconds":round(time.monotonic()-started,1),
                 "uncovered_scene_ids":[str(s["scene_id"]) for s in script["scenes"] if not assignments.get(str(s["scene_id"]))],
                 "error_counts":dict(Counter(row.get("reason","") for row in status if row.get("status")=="unavailable"))}
        result={"version":VERSION,"script_fingerprint":key(script),"assets":assets,"scenes":assignments,"provider_status":status,"summary":summary,
                "inspection_reports":reviews,
                "note":"Only explicit reusable rights plus actual Gemini video inspection qualify a clip. Missing footage remains visible; no login or DRM bypass."}
        save_json(directory/"discovery.json",result)
        return result
    options=_options()
    def search(row):
        path=directory/"search"/(key(VERSION,row["query"],limits.results_per_query)+".json")
        if path.exists():return row,read_json(path),True,None
        try:
            settings={**options,"extract_flat":"in_playlist","playlistend":limits.results_per_query}
            with factory(settings) as ydl:
                raw=ydl.extract_info(search_url(row["query"]),download=False)
                entries=list(islice((raw or {}).get("entries") or [],limits.results_per_query))
            values=[{k:e.get(k) for k in ("id","title","description","duration","url","channel","uploader")}
                    for e in entries if isinstance(e,dict) and re.fullmatch(r"[A-Za-z0-9_-]{11}",str(e.get("id","")))]
            save_json(path,values);return row,values,False,None
        except Exception as exc:return row,[],False,type(exc).__name__
    # Small batches retain scene fairness, checkpoint every response and avoid a request burst.
    failed_streak=0
    with ThreadPoolExecutor(max_workers=limits.workers) as pool:
        for index in range(0,len(queries),limits.workers):
            if time.monotonic()-started>limits.search_seconds or time.monotonic()>deadline:break
            batch=queries[index:index+limits.workers]
            for row,values,cached,error in pool.map(search,batch):
                counters["attempted_queries"]+=1;counters["cached_queries"]+=int(cached)
                counters["search_result_rows"]+=len(values)
                if error:
                    failed_streak+=1
                    status.append({"provider":"YouTube","query":row["query"],"scene_id":row["scene_id"],
                                   "status":"unavailable","reason":error})
                else:
                    failed_streak=0
                    status.append({"provider":"YouTube","query":row["query"],"scene_id":row["scene_id"],
                                   "status":"searched","candidate_count":len(values),"cached":cached})
                for item in values:
                    old=candidates.setdefault(item["id"],{**item,"query_scene_ids":[]})
                    if row["scene_id"] not in old["query_scene_ids"]:old["query_scene_ids"].append(row["scene_id"])
                counters["unique_candidates"]=len(candidates);checkpoint()
            print(f'YouTube research: {counters["attempted_queries"]}/{len(queries)} queries, {len(candidates)} unique candidates',flush=True)
            if failed_streak>=12:
                status.append({"provider":"YouTube","status":"unavailable","reason":"persistent_search_failure_circuit_breaker"})
                break
    for url in list(urls)[:8]:
        ident=video_id(url)
        candidates.setdefault(ident,{"id":ident,"title":"","query_scene_ids":[str(s["scene_id"]) for s in script["scenes"]]})
    manual_ids={video_id(url) for url in list(urls)[:8]}
    counters["unique_candidates"]=len(candidates)
    shortlist=fair_shortlist(list(candidates.values()),script,limits.metadata_limit)
    shortlist=([candidates[i] for i in sorted(manual_ids)]+[item for item in shortlist if item["id"] not in manual_ids])[:limits.metadata_limit]
    def metadata_for(item):
        path=directory/"metadata"/(item["id"]+".json")
        if path.exists():
            cached=read_json(path)
            if time.time()-cached.get("checked_at",0)<86400 and "player_access" in cached.get("info",{}):
                return {**cached["info"],"query_scene_ids":item["query_scene_ids"]},None
        try:
            access=AccessLog()
            with factory({**options,"logger":access}) as ydl:raw=ydl.extract_info("https://www.youtube.com/watch?v="+item["id"],download=False)
            if not isinstance(raw,dict):raise PipelineError("No video metadata")
            fields=("id","title","description","duration","license","is_live","availability","has_drm","chapters","uploader","channel","upload_date")
            info={k:raw.get(k) for k in fields};info["query_scene_ids"]=item["query_scene_ids"]
            info["public_format_count"]=sum(bool(f.get("url")) and not f.get("has_drm") for f in (raw.get("formats") or []))
            info["player_access"]="authentication_required" if access.auth_required else "available" if info["public_format_count"] else "no_public_formats"
            save_json(path,{"checked_at":time.time(),"info":info});return info,None
        except Exception as exc:return {**item,"player_access":"authentication_required" if access.auth_required else "unknown"},type(exc).__name__
    blocked=0
    with ThreadPoolExecutor(max_workers=limits.workers) as pool:
        for index in range(0,len(shortlist),limits.workers):
            if time.monotonic()>deadline:break
            for info,error in pool.map(metadata_for,shortlist[index:index+limits.workers]):
                counters["metadata_inspected"]+=1
                if info.get("player_access")=="authentication_required":
                    blocked+=1;status.append({"provider":"YouTube","video_id":info["id"],"status":"unavailable","reason":"authentication_required_on_hosted_runner"})
                elif error:status.append({"video_id":info["id"],"status":"unavailable","reason":error})
                elif not reusable(info):status.append({"video_id":info["id"],"status":"skipped","reason":"Explicit reusable CC BY license not established"})
                elif not isinstance(info.get("duration"),(int,float)) or not 6<=info["duration"]<=7200:
                    status.append({"video_id":info["id"],"status":"skipped","reason":"Source outside bounded inspection duration"})
                elif not info.get("public_format_count"):
                    status.append({"provider":"YouTube","video_id":info["id"],"status":"unavailable","reason":"no_downloadable_public_formats"})
                else:metadata.append(info);counters["eligible_cc_candidates"]+=1
                checkpoint()
            if blocked>=3:
                print("YouTube requires authentication on this hosted runner; preserving search results and using direct open sources.",flush=True)
                break
    counters["authentication_blocked_candidates"]=blocked
    ordered=fair_shortlist(metadata,script,limits.review_limit)
    def download(info,a,b,path,height=1080):
        return download_excerpt(info,a,b,path,height,ydl_factory=factory)
    review_function=reviewer or inspect
    for info in ordered:
        if len(assets)>=limits.max_clips or time.monotonic()>deadline:break
        shutil.rmtree(directory/"source-cache",ignore_errors=True)
        queried=set(info.get("query_scene_ids",[]))
        matches=[s for s in script["scenes"] if str(s["scene_id"]) in queried or context(info,s,script["title"])["subject_terms"]]
        matches=sorted(matches,key=lambda s:(
            -int(str(s["scene_id"]) in queried),-context(info,s,script["title"])["score"]))[:5]
        if api is None and reviewer is None:
            status.append({"video_id":info["id"],"status":"unavailable","reason":"Gemini video inspection unavailable"});continue
        counters["video_reviews_started"]+=1;checkpoint()
        try:
            reviewed=review_function(api,info,matches,directory/"reviews",download)
            counters["video_reviews_completed"]+=1
            reviews.append(reviewed);checkpoint()
        except QuotaDeferred as exc:
            status.append({"video_id":info["id"],"status":"unavailable","reason":"Gemini_free_quota_deferred"})
            print("Footage inspection paused; accepted clips and searches preserved: "+str(exc),flush=True);break
        except (PipelineError,ValueError,KeyError,TypeError,OSError) as exc:
            status.append({"video_id":info["id"],"status":"unavailable","reason":type(exc).__name__,"stage":"video_inspection"})
            print("Candidate video inspection failed: "+str(exc)[:240],flush=True);continue
        for segment in reviewed["segments"]:
            if len(assets)>=limits.max_clips or time.monotonic()>deadline:break
            a,b=segment["start"],segment["end"]
            ident="youtube-"+info["id"]+"-"+str(round(a*1000))+"-"+str(round(b*1000))
            try:
                path=download(info,a,b,directory/"clips"/(ident+".mp4"))
                meta=probe(path);stream=next(s for s in meta["streams"] if s["codec_type"]=="video")
                record={"id":ident,"path":str(path.resolve()),"subject":segment["observed"],"title":info["title"],
                        "date":"Historical period and filming date distinguished in inspection metadata",
                        "medium":"video","provider":"YouTube Creative Commons","license":"CC BY 3.0",
                        "license_url":"https://creativecommons.org/licenses/by/3.0/",
                        "source_url":"https://www.youtube.com/watch?v="+info["id"],
                        "creator":info.get("uploader") or info.get("channel") or "YouTube uploader",
                        "context":segment["observed"]+" Supports: "+segment["narration_anchor"],
                        "source_start_seconds":a,"source_end_seconds":b,"filming_or_upload_date":info.get("upload_date"),
                        "footage_presentation":segment["presentation"],"inspection":segment,"inspection_mode":reviewed["mode"],
                        "width":int(stream["width"]),"height":int(stream["height"]),
                        "acquisition":read_json(path.with_suffix(".acquisition.json")) if path.with_suffix(".acquisition.json").exists() else {},
                        "duration_seconds":min(b-a,float(meta["format"]["duration"])),
                        "sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
                assets.append(record);assignments.setdefault(str(segment["scene_id"]),[]).append(ident)
                status.append({"video_id":info["id"],"status":"available","scene_id":segment["scene_id"],
                               "source_start":a,"source_end":b,"presentation":segment["presentation"]})
                checkpoint()
            except Exception as exc:
                status.append({"video_id":info["id"],"status":"unavailable","reason":type(exc).__name__,"stage":"excerpt_download"})
                print("Selected footage download unavailable: "+str(exc)[:180],flush=True)
    # Keep selected excerpts, not large complete source movies, in Actions artifacts.
    shutil.rmtree(directory/"source-cache",ignore_errors=True)
    result=checkpoint()
    print("YOUTUBE_DEEP_SEARCH "+__import__("json").dumps(result["summary"]),flush=True)
    return result

def bounded(script,directory,urls=(),timeout=None):
    """Whole-process deadline includes search, Gemini pacing and download children."""
    import signal,subprocess,sys
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    request=directory/"request.json";save_json(request,{"script":script,"urls":list(urls)})
    # A failed new attempt must never publish an old country/script discovery.
    save_json(directory/"discovery.json",{"version":VERSION,"script_fingerprint":key(script),
              "assets":[],"scenes":{},"provider_status":[]})
    timeout=timeout or Limits.environment().total_seconds+120
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
    shutil.rmtree(directory/"source-cache",ignore_errors=True)
    path=directory/"discovery.json"
    result=read_json(path) if path.exists() else {"assets":[],"scenes":{},"provider_status":[]}
    result["provider_status"].append({"provider":"YouTube","status":"unavailable","reason":reason})
    save_json(path,result);return result

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--request",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    request=read_json(args.request);discover(request["script"],args.output,request.get("urls",[]))
