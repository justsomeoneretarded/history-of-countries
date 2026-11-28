"""Direct reusable archive movies and Commons videos; inspect actual camera footage."""
from pathlib import Path
from urllib.parse import quote,urlparse
import hashlib
import html
import re
import time
import requests
from .core import ROOT,PipelineError,key,read_json,save_json,probe,ffmpeg
from .footage_search import context,source_priority,scene_review_order,words,PLACE_WORDS,country,dated_event_evidence
from .footage_review import inspect,validate_segments
from .gemini import QuotaDeferred

MAX_BYTES=180*1024*1024
UA="HistoryOfCountries/2.0 (reusable documentary footage; provenance retained)"

def clean(value):
    return " ".join(html.unescape(re.sub(r"<[^>]+>"," ",str(value))).split())

def license_record(value):
    text=" ".join(map(str,value)) if isinstance(value,list) else str(value or "")
    if re.search(r"creativecommons\.org/(?:publicdomain/(?:mark|zero)|licenses/publicdomain)",text,re.I):
        return {"license":"Public domain","license_url":text.split()[0]}
    match=re.search(r"https?://creativecommons\.org/licenses/by/(\d\.\d)/?",text,re.I)
    if match:return {"license":"CC BY "+match[1],"license_url":match[0]}
    return None

def fetch_json(session,url,params,cache):
    if cache.exists():return read_json(cache)
    result=session.get(url,params=params,timeout=(8,25));result.raise_for_status()
    data=result.json();save_json(cache,data);return data

def stream_file(session,url,target):
    if target.exists() and target.stat().st_size:return target
    response=session.get(url,timeout=(8,25),stream=True);response.raise_for_status()
    if int(response.headers.get("Content-Length","0"))>MAX_BYTES:raise PipelineError("Open footage source exceeds byte budget")
    target.parent.mkdir(parents=True,exist_ok=True);temporary=target.with_suffix(target.suffix+".part")
    started=time.monotonic();size=0
    try:
        with temporary.open("wb") as out:
            for chunk in response.iter_content(65536):
                size+=len(chunk)
                if size>MAX_BYTES or time.monotonic()-started>180:raise PipelineError("Open source download exceeded byte/time budget")
                out.write(chunk)
        temporary.replace(target)
    finally:temporary.unlink(missing_ok=True)
    return target

def archive_seeds(script):
    if "ethiop" not in script["title"].casefold():return {}
    path=ROOT/"assets/footage/catalog.json";result={}
    if not path.exists():return result
    for row in read_json(path):
        parsed=urlparse(row.get("source_url",""))
        if parsed.hostname!="archive.org" or not parsed.path.startswith("/details/"):continue
        ident=parsed.path.split("/")[2]
        item=result.setdefault(ident,{"context":[],"years":set()})
        item["context"].append(row.get("title","")+" "+row.get("context",""))
        item["years"].update(dated_event_evidence({"title":row.get("date","")}))
    return {ident:{"context":" ".join(v["context"]),"years":sorted(v["years"])} for ident,v in result.items()}

def archive_candidates(session,script,directory,status,limit=36):
    seeds=archive_seeds(script);rows={ident:{"identifier":ident} for ident in seeds}
    name=country(script["title"])
    aliases=[name]+(["Abyssinia"] if "ethiop" in name.casefold() else [])
    queries=["mediatype:movies AND licenseurl:* AND ("+" OR ".join('"'+a.replace('"',"")+'"' for a in aliases)+")"]
    order=scene_review_order(script);by_id={str(s["scene_id"]):s for s in script["scenes"]}
    for ident in order:
        scene=by_id[ident]
        subject=scene.get("asset_search_term","")
        if "portrait" in subject.casefold():continue
        query="mediatype:movies AND "+'"'+name.replace('"',"")+'" AND ('+" OR ".join(sorted(words(subject)-words(name))[:5])+")"
        if query not in queries:queries.append(query)
        if len(queries)>=6:break
    for query in queries:
        try:
            data=fetch_json(session,"https://archive.org/advancedsearch.php",
                {"q":query,"output":"json","rows":12,"fl[]":["identifier","title","description","licenseurl","date"]},
                directory/"search"/(key(query)+".json"))
            found=data.get("response",{}).get("docs",[])
            for row in found:
                ident=row.get("identifier")
                if isinstance(ident,str) and re.fullmatch(r"[A-Za-z0-9_.-]+",ident):rows.setdefault(ident,row)
            status.append({"provider":"Internet Archive","status":"searched","query":query,"candidates":len(found)})
        except (requests.RequestException,ValueError) as exc:
            status.append({"provider":"Internet Archive","status":"unavailable","reason":type(exc).__name__})
    result=[]
    for ident,row in list(rows.items())[:limit]:
        try:
            data=fetch_json(session,"https://archive.org/metadata/"+quote(ident,safe=""),None,directory/"metadata"/(ident+".json"))
            meta=data.get("metadata",{});rights=license_record(meta.get("licenseurl"))
            if not rights:continue
            title=clean(meta.get("title",ident));description=clean(meta.get("description",""))
            if source_priority({"title":title,"description":description})<=-100:continue
            files=[f for f in data.get("files",[]) if str(f.get("name","")).casefold().endswith(".mp4") and 0<int(f.get("size") or 0)<=MAX_BYTES]
            if not files:continue
            chosen=max(files,key=lambda f:("512" not in str(f.get("format","")),int(f.get("width") or 0),int(f.get("size") or 0)))
            years=seeds.get(ident,{}).get("years",[])
            # Explicit retrospective titles distinguish publication year from the event.
            retro=re.search(r"\b(\d{1,3}) years ago\b",title,re.I)
            dates=dated_event_evidence({"title":title})
            if not years and retro and dates:years=[max(dates)-int(retro[1])]
            description+=" "+seeds.get(ident,{}).get("context","")
            result.append({"id":"archive-"+ident,"provider":"Internet Archive","title":title,"description":description,
                "source_url":"https://archive.org/details/"+ident,
                "download_url":"https://archive.org/download/"+quote(ident,safe="")+"/"+quote(chosen["name"],safe="/"),
                "curated_source":ident in seeds,"creator":clean(meta.get("creator") or meta.get("collection") or "Creator identified on source page"),
                "upload_date":meta.get("date"),"depicted_years":years,"source_extension":".mp4",**rights})
        except (requests.RequestException,ValueError,KeyError,TypeError) as exc:
            status.append({"provider":"Internet Archive","source_id":ident,"status":"unavailable","reason":type(exc).__name__})
    return result

def commons_candidates(session,script,directory,status):
    result={};order=scene_review_order(script);by_id={str(s["scene_id"]):s for s in script["scenes"]}
    used=set()
    physical=[s for s in script["scenes"] if words(s.get("asset_search_term",""))&PLACE_WORDS]
    ordered=[str(s["scene_id"]) for s in physical]+order
    for ident in ordered:
        scene=by_id[ident];query=scene.get("asset_search_term","")
        if "portrait" in query.casefold():continue
        if words(query)&PLACE_WORDS:
            location=scene.get("location","").split(" and ")[0].strip()
            if location:query=location
        else:
            query=re.sub(r"\b(?:painting|photograph|historical|countryside|portrait)\b","",query,flags=re.I).strip()
        query+=" filetype:video"
        if query in used:continue
        used.add(query)
        if len(used)>10:break
        params={"action":"query","format":"json","formatversion":2,"generator":"search","gsrsearch":query,
                "gsrnamespace":6,"gsrlimit":5,"prop":"imageinfo","iiprop":"url|size|mime|extmetadata"}
        try:
            raw=fetch_json(session,"https://commons.wikimedia.org/w/api.php",params,directory/"search"/(key(params)+".json"))
            pages=raw.get("query",{}).get("pages",[])
            for page in pages:
                info=(page.get("imageinfo") or [{}])[0];meta=info.get("extmetadata",{})
                value=lambda k:clean(meta.get(k,{}).get("value",""))
                rights=license_record(value("LicenseUrl"))
                if not rights and ("public domain" in value("LicenseShortName").casefold() or value("LicenseShortName").casefold()=="cc0"):
                    rights={"license":"Public domain","license_url":value("LicenseUrl")}
                if not rights or not str(info.get("mime","")).startswith(("video/","application/ogg")):continue
                if int(info.get("size") or 0)>MAX_BYTES:continue
                url=info.get("url","")
                if urlparse(url).hostname!="upload.wikimedia.org":continue
                aid="commons-video-"+str(page["pageid"])
                result[aid]={"id":aid,"provider":"Wikimedia Commons video","title":clean(page["title"]).removeprefix("File:"),
                    "description":value("ImageDescription"),"source_url":"https://commons.wikimedia.org/?curid="+str(page["pageid"]),
                    "download_url":url,"creator":value("Artist"),"upload_date":value("DateTimeOriginal"),
                    "source_extension":Path(urlparse(url).path).suffix,**rights}
            status.append({"provider":"Wikimedia Commons video","query":query,"status":"searched","candidates":len(pages)})
        except (requests.RequestException,ValueError,KeyError,TypeError) as exc:
            status.append({"provider":"Wikimedia Commons video","query":query,"status":"unavailable","reason":type(exc).__name__})
    return list(result.values())

def discover(api,script,directory,max_reviews=8):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    signature=key("direct-footage-v2-subject-searches",script,max_reviews)
    previous=directory/"discovery.json"
    if previous.exists():
        cached=read_json(previous)
        if cached.get("fingerprint")==signature and cached.get("assets") and all(
            Path(a["path"]).exists() and Path(a["path"]).resolve().is_relative_to(directory.resolve()) and
            hashlib.sha256(Path(a["path"]).read_bytes()).hexdigest()==a.get("sha256") for a in cached["assets"]):
            return cached
    session=requests.Session();session.headers.update({"User-Agent":UA})
    status=[];assets=[];mapping={};reports=[];started=time.monotonic()
    candidates=archive_candidates(session,script,directory/"archive",status)
    candidates+=commons_candidates(session,script,directory/"commons",status)
    ranked=[]
    for item in candidates:
        scored=[(context(item,s,script["title"]),s) for s in script["scenes"]]
        matches=[s for m,s in scored if not m["period_conflict"] and (m["subject_terms"] or item.get("depicted_years"))]
        if not matches:continue
        value=max((m["score"] for m,s in scored if s in matches),default=0)+source_priority(item)+(50 if item.get("curated_source") else 0)
        ranked.append((value,item,matches))
    ranked.sort(key=lambda row:-row[0])
    reviewed=0
    def checkpoint():
        result={"fingerprint":signature,"assets":assets,"scenes":mapping,"provider_status":status,"inspection_reports":reports,
                "summary":{"candidate_sources":len(candidates),"video_reviews":reviewed,"accepted_clips":len(assets),
                           "accepted_seconds":round(sum(a["duration_seconds"] for a in assets),2),
                           "scenes_with_footage":len(mapping),"elapsed_seconds":round(time.monotonic()-started,1)}}
        save_json(directory/"discovery.json",result);return result
    checkpoint()
    for score,info,matches in ranked:
        if reviewed>=max_reviews or time.monotonic()-started>1500:break
        source=None
        try:
            source=stream_file(session,info["download_url"],directory/"sources"/(key(info["id"])+info["source_extension"]))
            measured=probe(source);info={**info,"local_path":str(source.resolve()),"duration":float(measured["format"]["duration"])}
            if not 6<=info["duration"]<=3600:continue
            matches=sorted(matches,key=lambda s:-context(info,s,script["title"])["score"])[:5]
            reviewed+=1
            def unused(*args,**kwargs):raise PipelineError("Local source should not invoke YouTube downloading")
            report=inspect(api,info,matches,directory/"reviews",unused)
            reports.append(report);checkpoint()
            for segment in report["segments"]:
                a,b=segment["start"],segment["end"];aid=info["id"]+"-"+key(a,b)
                target=directory/"clips"/(aid+".mp4");target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists():
                    ffmpeg("-ss",str(a),"-i",source,"-t",str(b-a),"-an","-c:v","libx264",
                           "-preset","veryfast","-crf","19","-pix_fmt","yuv420p","-movflags","+faststart",target,timeout=180)
                data=probe(target);stream=next(s for s in data["streams"] if s["codec_type"]=="video")
                assets.append({"id":aid,"path":str(target.resolve()),"title":info["title"],"subject":segment["observed"],
                    "provider":info["provider"],"source_url":info["source_url"],"creator":info["creator"],
                    "license":info["license"],"license_url":info["license_url"],"medium":"video",
                    "date":"Source filming/depicted date retained in inspection evidence","context":segment["observed"]+" Supports: "+segment["narration_anchor"],
                    "footage_presentation":segment["presentation"],"inspection":segment,"inspection_mode":report["mode"],
                    "source_start_seconds":a,"source_end_seconds":b,"duration_seconds":min(b-a,float(data["format"]["duration"])),
                    "width":int(stream["width"]),"height":int(stream["height"]),"sha256":hashlib.sha256(target.read_bytes()).hexdigest()})
                mapping.setdefault(str(segment["scene_id"]),[]).append(aid)
                status.append({"provider":info["provider"],"source_id":info["id"],"status":"available","scene_id":segment["scene_id"]})
                checkpoint()
        except QuotaDeferred:
            status.append({"provider":"Gemini","status":"unavailable","reason":"free_quota_deferred"});break
        except (PipelineError,requests.RequestException,ValueError,KeyError,TypeError,OSError) as exc:
            status.append({"provider":info["provider"],"source_id":info["id"],"status":"unavailable","reason":type(exc).__name__,"detail":str(exc)[:250]})
            print("Open footage candidate unavailable: "+str(exc)[:250],flush=True)
        finally:
            if source is not None:source.unlink(missing_ok=True)
    result=checkpoint()
    print("OPEN_FOOTAGE_SEARCH "+__import__("json").dumps(result["summary"]),flush=True)
    return result
