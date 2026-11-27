"""Title and short brief to a simple narrated archival video on GitHub Actions."""
from pathlib import Path
import argparse
import json
import os
import shutil
from .core import ROOT,PipelineError,read_json,save_json,ffmpeg,duration
from .gemini import QuotaDeferred
from .media_api import MediaAPI,VOICES
from . import director_script,bootstrap,media,planning,editing,packaging,quality,sourcing
from .audio_edit import mix
from .director_sound import compose

DEFAULT_BRIEF="Tell an original, absorbing history of Ethiopia from Aksum through the November 2022 Pretoria agreement. Begin inside the Adwa reversal, connect centuries through decisions and consequences, and pay off the opening question at the end. Conversational, clear, lightly ironic about rulers' mistakes, sober about suffering. Real historical photographs and footage only. Preserve complete source images, prefer widescreen compositions, use minimal on-screen dates and no animated graphics."

def validate_request(raw):
    if not isinstance(raw,dict):raise PipelineError("Request must be an object")
    request={"title":"The Entire History of Ethiopia","brief":DEFAULT_BRIEF,"voice":"Charon","minutes":8.75,"youtube":True,"youtube_urls":[],"phase":"full","editorial_draft":None,**raw}
    if not isinstance(request["title"],str) or not 1<=len(request["title"].strip())<=200:raise PipelineError("Supply a title of 1–200 characters")
    if not isinstance(request["brief"],str) or not 1<=len(request["brief"].strip())<=6000:raise PipelineError("Supply a brief of 1–6000 characters")
    if request["voice"] not in (*VOICES,"auto"):raise PipelineError("Choose a supported Gemini voice")
    if type(request["minutes"]) not in (int,float) or not .5<=request["minutes"]<=10:raise PipelineError("Choose 0.5–10 minutes")
    if type(request["youtube"]) is not bool:raise PipelineError("youtube must be true or false")
    if request["phase"] not in {"full","preview","voice"}:raise PipelineError("Choose full or preview")
    if not isinstance(request["youtube_urls"],list) or len(request["youtube_urls"])>8:raise PipelineError("Supply at most eight YouTube URLs")
    if request["editorial_draft"] not in {None,"ethiopia"}:raise PipelineError("Unknown editorial draft")
    for url in request["youtube_urls"]:media.youtube.video_id(url)
    return request

def render(script,speech,catalog,work,output,profile,api=None,full_script=None,request=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    work=Path(work);directory=work/"simple-render";directory.mkdir(parents=True,exist_ok=True)
    shots,storyboard=planning.make(api,script,speech,catalog,work)
    outro=1.2 if profile=="cinematic" else 0.
    if outro:
        shots[-1]["outro_hold_seconds"]=outro
        shots[-1]["frames"]+=round(outro*editing.PROFILES[profile][2])
        shots[-1]["global_end"]+=outro
    save_json(output/"storyboard.json",storyboard);save_json(output/"timeline.json",shots)
    records={a["id"]:a for a in catalog["assets"]}
    sourcing_report=sourcing.assess(script,catalog,shots,required=bool((request or {}).get("youtube",False)))
    save_json(output/"sourcing.json",sourcing_report)
    paths=[]
    for index,shot in enumerate(shots):
        print(f'Editing shot {index+1}/{len(shots)}, scene {shot["scene_id"]}: {records[shot["asset_id"]]["subject"][:75]}',flush=True)
        paths.append(editing.render_shot(records[shot["asset_id"]],shot,directory/"shots",profile))
        save_json(work/"progress.json",{"stage":"visuals","rendered_shots":index+1,"shot_count":len(shots),"seconds":shot["global_end"],"complete":False})
    silent=directory/"picture.mp4";editing.concat(paths,silent)
    width,height,fps=editing.PROFILES[profile]
    editing.captions(script,speech,output,width,height)
    mixed,filters,timing=mix(speech,shots,work/"speech",directory,[{"before_scene_id":None,"seconds":outro}] if outro else [],output,soundtrack_builder=compose)
    for name in ("music-credits.json","music-credits.txt","soundtrack.json"):
        shutil.copy2(directory/name,output/name)
    narration_seconds=sum(s["duration"] for s in speech["scenes"])
    expected=narration_seconds+outro
    final=output/"final.mp4"
    # Dates are already present in each visual part. Preserve the encoded
    # picture instead of recompressing the entire film a second time.
    ffmpeg("-i",silent,"-i",mixed,"-af",filters,
      "-map","0:v:0","-map","1:a:0","-t",str(expected),"-c:v","copy",
      "-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart",final,timeout=max(900,expected*3))
    used={s["asset_id"] for s in shots}
    save_json(output/"render.json",{"style":"simple-archival-editor","duration":duration(final),"profile":profile,
      "voice":speech["voice"],"credits_seconds":0,"interlude_seconds":0,"outro_seconds":outro,"source_crop":False,"image_animation":False})
    report=quality.inspect(final,script,speech,{"film":{"assets":[{"source_url":records[i]["source_url"]} for i in used]}},output)
    evidence=read_json(work/"research.json") if (work/"research.json").exists() else {"sources":[]}
    save_json(output/"sources.json",evidence)
    selected={**catalog,"assets":[a for a in catalog["assets"] if a["id"] in used]}
    packaging.package(api,script,speech,selected,output,work)
    if (work/"editorial-writing.json").exists():shutil.copy2(work/"editorial-writing.json",output/"story-notes.json")
    save_json(output/"media-discovery.json",{"provider_status":catalog.get("provider_status",[]),
      "used_images":len([i for i in used if records[i].get("medium") not in planning.VIDEO]),
      "used_videos":len([i for i in used if records[i].get("medium") in planning.VIDEO]),
      "used_youtube_videos":len([i for i in used if records[i].get("provider")=="YouTube Creative Commons"]),
      "deep_search":catalog.get("footage_research",{})})
    full=profile=="cinematic" and (request or {}).get("phase")=="full"
    if full and not .9*float(request["minutes"])*60<=narration_seconds<=1.1*float(request["minutes"])*60:raise PipelineError("The full narration missed the target duration")
    save_json(output/"delivery.json",{"upload_ready":bool(full and report["passed"] and sourcing_report["passed"]),"preview":not full,
      "duration_seconds":expected,"voice":speech["voice"],"technical_passed":report["passed"],"sourcing_passed":sourcing_report["passed"],
      "status":"upload_ready" if full and report["passed"] and sourcing_report["passed"] else "needs_sourcing" if not sourcing_report["passed"] else "preview",
      "visual_style":"Complete historical images and real footage, phrase-aligned cuts, discreet dates and no animation",
      "source_crop":False,"image_animation":False,"outro_seconds":outro,
      "youtube_published":False,"quality_scope":"Encoded-media, timing, speech-verification and provenance checks; no animation-score approval stage"})
    save_json(output/"framing.json",{"source_crop":False,"image_animation":False,
      "fit":"Complete foreground contained proportionally within the output frame; prefer native widescreen media",
      "frame_size":[width,height],
      "date_only_overlay":True,"shots":len(shots),
      "video_continuity":"Consecutive footage cuts use increasing source offsets"})
    if api is not None and full:
        from .listening import review as listen
        listen(api,final,speech,script,work,output)
    if full and not sourcing_report["passed"]:
        save_json(work/"progress.json",{"stage":"needs_sourcing","complete":False,"output":str(output),"failures":sourcing_report["failures"]})
        raise PipelineError("Draft video saved; insufficient moving footage. See sourcing.json: "+"; ".join(sourcing_report["failures"]))
    save_json(work/"progress.json",{"stage":"complete","complete":True,"output":str(output)})
    return final

def run(request,work,output):
    request=validate_request(request);work=Path(work);output=Path(output)
    work.mkdir(parents=True,exist_ok=True);output.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault("GEMINI_SCHEMA_MODE","prompt")
    os.environ.setdefault("GEMINI_MODEL",os.getenv("GEMINI_WRITER_MODEL","gemini-3.1-flash-lite"))
    os.environ.setdefault("GEMINI_TTS_MODEL","gemini-3.8-flash-tts")
    os.environ.setdefault("GEMINI_PACKAGE_MODEL","gemini-3.5-flash-lite")
    os.environ.setdefault("GEMINI_INPUT_TOKEN_BUDGET","40000")
    os.environ.setdefault("SCRIPT_TARGET_WPM","160")
    draft_args=["--draft",request["editorial_draft"]] if request["editorial_draft"] else []
    code=director_script.main(["--stage","all","--title",request["title"],"--brief",request["brief"],
      "--voice",request["voice"],"--minutes",str(request["minutes"]),"--work",str(work),*draft_args])
    if code:
        if code==75:raise QuotaDeferred("Gemini free quota deferred; resume the saved countries-checkpoint after the quota reset")
        raise PipelineError("Writing or narration failed; see checkpoint failure.json")
    script=read_json(work/"script.json");speech=read_json(work/"speech/speech.json")
    if {str(s["scene_id"]) for s in speech["scenes"]}!={str(s["scene_id"]) for s in script["scenes"]}:raise PipelineError("Speech/script scene IDs do not match")
    if any(s.get("verification",{}).get("accepted") is not True for s in speech["scenes"]):raise PipelineError("Unverified narration cannot be exported")
    audition=work/"voice-auditions/audition.json"
    if audition.exists():
        shutil.copy2(audition,output/"voice-comparison.json")
        for source in (work/"voice-auditions").glob("*.wav"):
            target=output/"voice-samples"/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    if request["phase"]=="voice":
        save_json(output/"delivery.json",{"upload_ready":False,"stage":"narration","voice":speech["voice"],"duration_seconds":sum(s["duration"] for s in speech["scenes"])})
        save_json(work/"progress.json",{"complete":True,"stage":"narration"})
        shutil.copy2(work/"script.txt",output/"script.txt")
        return work/"speech/speech.json"
    if request["phase"]=="preview":
        selected={s["scene_id"] for s in script["scenes"][:3]}
        script={**script,"scenes":[s for s in script["scenes"] if s["scene_id"] in selected]}
        speech={**speech,"scenes":[s for s in speech["scenes"] if s["scene_id"] in selected]}
    bootstrap.ensure(script["title"])
    catalogue=media.build(script,work/"media",use_youtube=request["youtube"],youtube_urls=request["youtube_urls"])
    return render(script,speech,catalogue,work,output,"cinematic" if request["phase"]=="full" else "preview",
      api=MediaAPI(work/"gemini"),request=request)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request",type=Path)
    parser.add_argument("--title",default="The Entire History of Ethiopia")
    parser.add_argument("--brief",default=DEFAULT_BRIEF)
    parser.add_argument("--voice",default="Charon")
    parser.add_argument("--minutes",type=float,default=8.75)
    parser.add_argument("--work",type=Path,default=ROOT/"work/countries")
    parser.add_argument("--output",type=Path,default=ROOT/"output/countries")
    parser.add_argument("--no-youtube",action="store_true")
    parser.add_argument("--preview",action="store_true")
    args=parser.parse_args(argv)
    request=read_json(args.request) if args.request else {"title":args.title,"brief":args.brief,"voice":args.voice,"minutes":args.minutes,
      "youtube":not args.no_youtube,"phase":"preview" if args.preview else "full"}
    try:
        result=run(request,args.work,args.output)
        print("COUNTRIES_VIDEO "+str(result),flush=True);return 0
    except (PipelineError,ValueError,KeyError,OSError) as exc:
        save_json(args.output/"failure.json",{"error":str(exc),"upload_ready":False})
        print("Production stopped: "+str(exc),flush=True)
        return 75 if isinstance(exc,QuotaDeferred) else 1

if __name__=="__main__":raise SystemExit(main())
