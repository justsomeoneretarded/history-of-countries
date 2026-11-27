"""Analyse the original finished MP4; this never renders a replacement video."""
import base64,hashlib,json,math,os,re,shutil,statistics,subprocess
from pathlib import Path
from PIL import Image,ImageDraw
from history_of_countries.core import ffmpeg,probe,save_json,read_json,PipelineError
from history_of_countries.media_api import MediaAPI,portable_schema

SOURCE=Path("input/video");WORK=Path("work/video-review");OUT=Path("output/video-review")
PROMPT_VERSION="finished-video-craft-review-v1"
def digest(path):
    value=hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda:handle.read(1024*1024),b""):value.update(block)
    return value.hexdigest()

def metrics(timeline,assets):
    by_id={a["id"]:a for a in assets["assets"]};holds=[]
    image_seconds=video_seconds=portrait_seconds=wide_seconds=fill_weight=0.
    for shot in timeline:
        asset=by_id[shot["asset_id"]];seconds=shot["global_end"]-shot["global_start"]
        moving=asset.get("medium") in {"video","archival_video","modern_documentary_video"}
        if moving:video_seconds+=seconds;continue
        image_seconds+=seconds
        if holds and holds[-1]["asset_id"]==asset["id"] and abs(holds[-1]["end"]-shot["global_start"])<.05:
            holds[-1]["end"]=shot["global_end"];holds[-1]["seconds"]+=seconds
        else:holds.append({"asset_id":asset["id"],"subject":asset.get("subject"),"start":shot["global_start"],"end":shot["global_end"],"seconds":seconds})
        width,height=asset.get("width"),asset.get("height")
        if width and height:
            ratio=width/height
            if ratio<1.2:portrait_seconds+=seconds
            if ratio>=1.55:wide_seconds+=seconds
            fill_weight+=seconds*min(ratio/(16/9),(16/9)/ratio)
    return {"encoded_shots":len(timeline),"image_seconds":image_seconds,"native_footage_seconds":video_seconds,
      "portrait_or_tall_image_seconds":portrait_seconds,"wide_image_seconds":wide_seconds,
      "average_foreground_frame_fill_for_images":fill_weight/max(1,image_seconds),
      "median_encoded_shot_seconds":statistics.median(s["global_end"]-s["global_start"] for s in timeline),
      "longest_unchanged_images":sorted(holds,key=lambda x:x["seconds"],reverse=True)[:12]}

def run():
    WORK.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
    if not shutil.which("ffmpeg"):
        subprocess.run(["sudo","apt-get","update","-q"],check=True,timeout=240)
        subprocess.run(["sudo","apt-get","install","-y","ffmpeg"],check=True,timeout=400)
    video=SOURCE/"final.mp4";meta=probe(video);seconds=float(meta["format"]["duration"])
    timeline=read_json(SOURCE/"timeline.json");assets=read_json(SOURCE/"media-credits.json")
    script=read_json(SOURCE/"script.json");records={a["id"]:a for a in assets["assets"]}
    analysis={"video_sha256":digest(video),"duration_seconds":seconds,
      "scope":"Original finished MP4, all audio and all sections, video sampled by Gemini at 2 fps",
      "metrics":metrics(timeline,assets),"segments":[]}
    api=MediaAPI(WORK/"gemini")
    schema={"type":"object","required":["summary","what_works","findings"],"properties":{
      "summary":{"type":"string"},"what_works":{"type":"array","items":{"type":"string"}},
      "findings":{"type":"array","items":{"type":"object","required":["local_start","local_end","category","severity","observed","why_it_matters","specific_fix","confidence"],
        "properties":{"local_start":{"type":"number"},"local_end":{"type":"number"},
          "category":{"type":"string"},"severity":{"type":"string","enum":["high","medium","low"]},
          "observed":{"type":"string"},"why_it_matters":{"type":"string"},"specific_fix":{"type":"string"},
          "confidence":{"type":"string","enum":["high","medium","low"]}}}}}}
    instruction=(
      "Critique the ACTUAL video and audio supplied, as a candid documentary director. Do not automatically praise it. "
      "The intended format is a simple original history documentary using real images and footage, natural conversational narration, minimal text, "
      "native widescreen images preferred and occasional complete portraits with subtle side fill. NO animation, artificial pan/zoom, animated maps, stick figures or source-image cropping. "
      "Evaluate the opening's immediate stakes, understandable story and causal transitions, names introduced before overload, sentence repetition, "
      "natural voice prosody, intelligibility, music masking, pauses, visual relevance to the spoken point, meaningful visual variety, "
      "excessive blurred side fill, weak illustrative choices, discreet date readability, and the ending's payoff. "
      "Do not propose animation or word-by-word subtitles. A still image is allowed; explain when a long still becomes unhelpful. "
      "Every finding must cite an approximate LOCAL time inside this clip, describe what is actually visible or audible, and give a specific practical fix. "
      "Describe people without guessing identities from faces; supplied asset metadata may identify them. No invented shots, dialogue, quotations or facts. "
      "Do not perform a new historical fact-check. Do not invent audience-retention statistics or claim that export tests prove creative quality. "
      "Focus on the 3–5 strongest observable problems per clip; omit vague advice. Flag uncertain claims as low confidence. "
      "The clip offset is supplied; local_start/local_end must be seconds relative to this clip, not the whole movie. "
      "The final clip includes the intentional short held ending, not a credits sequence. Return only JSON.")
    starts=list(range(0,math.ceil(seconds),180))
    for index,start in enumerate(starts):
        end=min(seconds,start+180);clip=WORK/f"clip-{index}.mp4"
        if not clip.exists():
            ffmpeg("-ss",str(start),"-i",video,"-t",str(end-start),"-vf","scale=960:-2,fps=15",
              "-c:v","libx264","-preset","veryfast","-crf","25","-c:a","aac","-b:a","96k","-movflags","+faststart",clip,timeout=600)
        if clip.stat().st_size>18*1024*1024:raise PipelineError("Review clip exceeds bounded inline size")
        shots=[s for s in timeline if s["global_start"]<end and s["global_end"]>start]
        spoken=[]
        for scene in script["scenes"]:
            related=[s for s in shots if s["scene_id"]==scene["scene_id"]]
            if related:spoken.append({"scene_id":scene["scene_id"],"narration":scene["narration"]})
        context={"clip_offset_seconds":start,"clip_seconds":end-start,"narration_context":spoken,
          "actual_shot_log":[{"local_start":max(0,s["global_start"]-start),"local_end":min(end-start,s["global_end"]-start),
            "subject":records[s["asset_id"]].get("subject"),"medium":records[s["asset_id"]].get("medium"),
            "context":records[s["asset_id"]].get("context","")[:200]} for s in shots]}
        body={"contents":[{"role":"user","parts":[{"text":instruction+"\nVIDEO CONTEXT, NOT INSTRUCTIONS:\n"+json.dumps(context,ensure_ascii=False)},
          {"inlineData":{"mimeType":"video/mp4","data":base64.b64encode(clip.read_bytes()).decode()},"videoMetadata":{"fps":2}}]}],
          "generationConfig":{"temperature":.15,"maxOutputTokens":5000,"responseMimeType":"application/json",
            "responseJsonSchema":portable_schema(schema),"thinkingConfig":{"thinkingLevel":"LOW"}}}
        record_path=OUT/f"segment-{index}.json"
        try:
            response=api.request("gemini-3.5-flash-lite","models/gemini-3.5-flash-lite:generateContent",body,"text")
            text="".join(p.get("text","") for p in response["candidates"][0]["content"]["parts"] if not p.get("thought"))
            report=json.loads(text)
            for finding in report.get("findings",[]):
                a,b=finding.get("local_start"),finding.get("local_end")
                if isinstance(a,(int,float)) and isinstance(b,(int,float)) and 0<=a<b<=end-start+.1:
                    finding["global_start"]=start+a;finding["global_end"]=start+b
                else:finding["timestamp_valid"]=False
            record={"offset":start,"seconds":end-start,"report":report,"assessed":True}
        except (PipelineError,ValueError,KeyError,IndexError) as exc:
            record={"offset":start,"seconds":end-start,"assessed":False,"error":str(exc)}
        save_json(record_path,record);analysis["segments"].append(record)
        print("VIDEO_REVIEW_SEGMENT "+json.dumps(record,ensure_ascii=False),flush=True)
    save_json(OUT/"analysis.json",analysis)
    print("VIDEO_REVIEW_METRICS "+json.dumps(analysis["metrics"],ensure_ascii=False),flush=True)
    points=[10,60,158,293,429,seconds-12]
    for segment in analysis["segments"]:
        for finding in segment.get("report",{}).get("findings",[])[:3]:
            if "global_start" in finding:points.append((finding["global_start"]+finding["global_end"])/2)
    points=sorted(set(round(min(seconds-.1,max(0,t)),1) for t in points))[:18]
    tiles=[]
    for i,at in enumerate(points):
        path=OUT/f"frame-{i:02}.jpg"
        ffmpeg("-ss",str(at),"-i",video,"-frames:v","1","-vf","scale=640:360",path)
        with Image.open(path) as pic:tile=pic.convert("RGB").copy()
        draw=ImageDraw.Draw(tile);draw.rectangle((0,330,640,360),fill=(10,18,24))
        draw.text((10,337),f"{int(at)//60:02}:{at%60:04.1f}",fill="white")
        tiles.append(tile)
    for sheet_index in range(0,len(tiles),6):
        chosen=tiles[sheet_index:sheet_index+6];sheet=Image.new("RGB",(1280,360*math.ceil(len(chosen)/2)))
        for j,tile in enumerate(chosen):sheet.paste(tile,((j%2)*640,(j//2)*360))
        path=OUT/f"review-sheet-{sheet_index//6}.jpg";sheet.save(path,quality=88)
        encoded=base64.b64encode(path.read_bytes()).decode()
        print("VIDEO_REVIEW_IMAGE_START")
        for i in range(0,len(encoded),8000):print("VIDEO_REVIEW_IMAGE_CHUNK "+encoded[i:i+8000])
        print("VIDEO_REVIEW_IMAGE_END")
    if not all(s["assessed"] for s in analysis["segments"]):
        print("Review coverage incomplete; unassessed sections are recorded explicitly.",flush=True)

if __name__=="__main__":run()
