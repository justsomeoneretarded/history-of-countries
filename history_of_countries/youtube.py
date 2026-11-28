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
from . import download_access

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

def _options(route=None):
    result={"quiet":True,"no_warnings":True,"noplaylist":True,"socket_timeout":30,
            "retries":3,"extractor_retries":1,"format_sort":["res","vcodec:h264"],"skip_download":True,"ignoreerrors":False,
            "ignore_no_formats_error":True,"lazy_playlist":True}
    node=shutil.which("node")
    if node:result["js_runtimes"]={"node":{"path":node}}
    return download_access.options(result,route or download_access.routes()[0])

def download_failure_reason(exc):
    """Useful diagnostics without echoing signed URLs, proxies or cookie contents."""
    message=str(exc).casefold()
    if re.search(r"sign in|not a bot|authentication|login required|captcha",message):return "authentication_required"
    if re.search(r"403|forbidden",message):return "http_403"
    if re.search(r"429|too many requests",message):return "rate_limited"
    if re.search(r"requested format|no video formats|no downloadable",message):return "format_unavailable"
    if re.search(r"source exceeds.*duration",message):return "source_duration_budget"
    if re.search(r"byte/time budget|size budget|bounded media|too large|larger than",message):return "source_size_or_time_budget"
    if re.search(r"timed out|timeout",message):return "network_timeout"
    if re.search(r"truncated",message):return "truncated_media"
    if re.search(r"resolution",message):return "resolution_too_low"
    return type(exc).__name__


def download_excerpt(info,start,end,target,height=1080,ydl_factory=None):
    """Retry configured routes and retain safe reasons for each failed attempt."""
    failures=[]
    for route in download_access.routes():
        try:
            path=_download_excerpt_route(info,start,end,target,height,ydl_factory,route)
            download_access.record_route_success(route)
            return path
        except Exception as exc:
            failures.append(route+":"+download_failure_reason(exc))
    raise PipelineError("Public footage download failed ("+", ".join(failures)+")") from None

def _download_excerpt_route(info,start,end,target,height=1080,ydl_factory=None,route="direct"):
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
    # Match Top10: native video+audio first, then cut the approved visual interval locally.
    selector=lambda cap:f"bv[height<={cap}]+ba/b[height<={cap}]"
    settings={**_options(route),"skip_download":False,"format":selector(height),
              "outtmpl":str(target.with_suffix(".%(ext)s")),"merge_output_format":"mp4",
              "download_ranges":download_range_func(None,[(start,end)]),"force_keyframes_at_cuts":True,
              "external_downloader_args":{"ffmpeg_i":["-rw_timeout","15000000"]}}
    access=AccessLog();settings["logger"]=access
    method="range_download";range_error=None
    try:
        if str(settings.get("proxy","")).startswith(("socks5://","socks5h://")):
            raise PipelineError("SOCKS routes use native downloading followed by local cutting")
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
        if not 6<=float(info.get("duration") or 0)<=3600:
            raise PipelineError("Range download unavailable; source exceeds whole-file fallback duration") from None
        target.unlink(missing_ok=True)
        cache=target.parent.parent/"source-cache";cache.mkdir(parents=True,exist_ok=True)
        source=next((p for p in cache.glob(info["id"]+".*") if p.suffix in {".mp4",".webm",".mkv"} and p.stat().st_size>0),None)
        if source is None:
            begun=time.monotonic()
            def bounded_progress(event):
                if event.get("downloaded_bytes",0)>800_000_000 or time.monotonic()-begun>300:
                    raise PipelineError("Whole-source fallback exceeded its byte/time budget")
            whole={**_options(route),"skip_download":False,"format":selector(min(height,1080)),
                   "outtmpl":str(cache/(info["id"]+".%(ext)s")),"merge_output_format":"mp4",
                   "max_filesize":800_000_000,"progress_hooks":[bounded_progress],
                   "postprocessors":[{"key":"FFmpegVideoRemuxer","preferedformat":"mp4"}],
                   "fragment_retries":3,"concurrent_fragment_downloads":1}
            with factory(whole) as ydl:ydl.download(["https://www.youtube.com/watch?v="+info["id"]])
            source=next((p for p in cache.glob(info["id"]+".*") if p.suffix in {".mp4",".webm",".mkv"} and p.stat().st_size>0),None)
        if source is None or source.stat().st_size>800_000_000:
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
              "source_id":info["id"],"start":start,"end":end,"route":route})
    return target

def check_access(factory,urls=()):
    """Test several actual public sources; one video cannot establish a route-wide block."""
    blocked=False
    probes=list(dict.fromkeys(urls))[:3] or ["https://www.youtube.com/watch?v=aqz-KE-bpKQ"]
    for route in download_access.routes():
        for test_url in probes:
            log=AccessLog();raw=None
            try:
                with factory({**_options(route),"logger":log}) as ydl:raw=ydl.extract_info(test_url,download=False)
            except Exception as exc:
                blocked=blocked or bool(re.search(r"confirm you.re not a bot|sign in",str(exc),re.I))
            blocked=blocked or log.auth_required
            if not log.auth_required and isinstance(raw,dict) and any(f.get("url") for f in (raw.get("formats") or [])):
                download_access.record_route_success(route)
                return {"status":"available","route":route}
    return {"status":"authentication_required" if blocked else "unknown","route":None}

def discover(script,directory,urls=(),max_queries=None,max_clips=None,ydl_factory=None,api=None,limits=None,reviewer=None,access_urls=()):
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
    route_check=check_access(factory,list(urls)+list(access_urls))
    if route_check["status"]=="authentication_required":
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
              "unique_candidates":0,"metadata_inspected":0,"access_route":route_check.get("route"),"eligible_cc_candidates":0,
              "video_reviews_started":0,"video_reviews_completed":0}
    def checkpoint():
        summary={**counters,"accepted_clips":len(assets),
                 "accepted_seconds":round(sum(a.get("duration_seconds",0) for a in assets),2),
                 "scenes_with_footage":len(assignments),"total_scenes":len(script["scenes"]),
                 "capacity_results":plan["capacity_results"],"legacy_capacity_results":15,
                 "elapsed_seconds":round(time.monotonic()-started,1),
                 "uncovered_scene_ids":[str(s["scene_id"]) for s in script["scenes"] if not assignments.get(str(s["scene_id"]))],
                 "error_counts":dict(Counter(row.get("reason","") for row in status if row.get("status")=="unavailable"))}
        result={"version":VERSION,"script_fingerprint":key(script),"requested_urls":list(urls),"assets":assets,"scenes":assignments,"provider_status":status,"summary":summary,
                "inspection_reports":reviews,
                "note":"Source inspection and license checks propose camera excerpts. Actual acquired media receives a second inspection in footage-research.json before catalogue acceptance."}
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
            if time.time()-cached.get("checked_at",0)<86400 and cached.get("info",{}).get("player_access")=="available":
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
    from .footage_triage import shortlist as camera_shortlist
    try:
        ordered,triage=camera_shortlist(api,metadata,script,directory/"triage",limits.review_limit)
    except QuotaDeferred as exc:
        status.append({"provider":"Gemini","status":"unavailable","reason":"local_request_budget_deferred" if exc.source=="local_budget" else "Gemini_free_quota_deferred"})
        return checkpoint()
    # Explicit source URLs are useful curated leads. Inspect their real video
    # even when a metadata-only model omitted them; all visual checks still apply.
    pinned=[item for item in metadata if item["id"] in manual_ids]
    ordered=(pinned+[item for item in ordered if item["id"] not in manual_ids])[:limits.review_limit]
    counters["camera_shortlist_count"]=len(ordered)
    counters["camera_shortlist_mode"]=triage.get("mode")
    checkpoint()
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
            status.append({"video_id":info["id"],"status":"unavailable","reason":"local_request_budget_deferred" if exc.source=="local_budget" else "Gemini_free_quota_deferred"})
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

def reusable_discovery(previous,script,directory):
    """Reuse only this exact script's inspected, unchanged camera excerpts."""
    if previous.get("script_fingerprint")!=key(script) or not previous.get("assets"):return False
    reports={r.get("source_id"):r for r in previous.get("inspection_reports",[])}
    root=Path(directory).resolve()
    try:
        for asset in previous["assets"]:
            path=Path(asset["path"]).resolve()
            if not path.is_relative_to(root) or not path.is_file():return False
            if hashlib.sha256(path.read_bytes()).hexdigest()!=asset.get("sha256"):return False
            inspected=asset.get("inspection",{})
            if inspected.get("camera_origin")!="recorded_camera" or inspected.get("clean_frame") is not True:return False
            source=video_id(asset["source_url"])
            if reports.get(source,{}).get("source_kind") not in {"camera","mixed"}:return False
        return True
    except (KeyError,ValueError,TypeError,OSError,PipelineError):return False

def merge_cached_discovery(current,previous,script,directory):
    """A blocked research retry must not erase previously inspected local clips."""
    if not previous or not reusable_discovery(previous,script,directory):return current
    if current.get("script_fingerprint")!=key(script):return current
    new_ids={asset["id"] for asset in current.get("assets",[])}
    retained=[asset for asset in previous["assets"] if asset["id"] not in new_ids]
    if not retained:return current
    merged={**current,"assets":list(current.get("assets",[]))+retained,
            "scenes":{ident:list(ids) for ident,ids in current.get("scenes",{}).items()}}
    retained_ids={asset["id"] for asset in retained}
    for ident,ids in previous.get("scenes",{}).items():
        kept=[aid for aid in ids if aid in retained_ids]
        if kept:merged["scenes"][ident]=list(dict.fromkeys(merged["scenes"].get(ident,[])+kept))
    reports={row.get("source_id"):row for row in previous.get("inspection_reports",[])}
    reports.update({row.get("source_id"):row for row in current.get("inspection_reports",[])})
    merged["inspection_reports"]=list(reports.values())
    summary=current.get("summary",{})
    merged["summary"]={**summary,"reused_clips":len(retained),"accepted_clips":len(merged["assets"]),
        "accepted_seconds":round(sum(asset.get("duration_seconds",0) for asset in merged["assets"]),2),
        "scenes_with_footage":len(merged["scenes"]),"total_scenes":len(script["scenes"]),
        "uncovered_scene_ids":[str(scene["scene_id"]) for scene in script["scenes"] if str(scene["scene_id"]) not in merged["scenes"]]}
    print("Preserved "+str(len(retained))+" inspected local excerpts from the same script after research retry.",flush=True)
    return merged


def bounded(script,directory,urls=(),timeout=None):
    """Whole-process deadline includes search, Gemini pacing and download children."""
    import signal,subprocess,sys
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    previous=None
    cached=directory/"discovery.json"
    if cached.exists():
        previous=read_json(cached)
        if os.getenv("YOUTUBE_FORCE_RESEARCH")!="true" and reusable_discovery(previous,script,directory) and previous.get("requested_urls",[])==list(urls):
            print("Reusing inspected camera footage for the same script; hashes and paths verified.",flush=True)
            return previous
    request=directory/"request.json"
    probes=[asset["source_url"] for asset in (previous or {}).get("assets",[])] if previous and reusable_discovery(previous,script,directory) else []
    save_json(request,{"script":script,"urls":list(urls),"access_urls":list(dict.fromkeys(probes))[:3]})
    # A failed new attempt must never publish an old country/script discovery.
    save_json(directory/"discovery.json",{"version":VERSION,"script_fingerprint":key(script),
              "assets":[],"scenes":{},"provider_status":[]})
    timeout=timeout or Limits.environment().total_seconds+120
    process=subprocess.Popen([sys.executable,"-m","history_of_countries.youtube","--request",str(request),"--output",str(directory)],
                             start_new_session=True)
    try:
        code=process.wait(timeout=timeout)
        if code==0 and (directory/"discovery.json").exists():
            result=merge_cached_discovery(read_json(directory/"discovery.json"),previous,script,directory)
            save_json(directory/"discovery.json",result)
            return result
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
    result=merge_cached_discovery(result,previous,script,directory)
    save_json(path,result);return result

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--request",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    request=read_json(args.request);discover(request["script"],args.output,request.get("urls",[]),access_urls=request.get("access_urls",[]))
