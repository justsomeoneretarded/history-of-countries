"""Listen to real mixed-output excerpts; no historical review or invented scores."""
from pathlib import Path
from .core import PipelineError,key,read_json,save_json,ffmpeg,duration

def sample_sections(seconds):
    return [(0.,min(35.,seconds)),(max(0.,seconds*.5-10),min(20.,seconds)),
            (max(0.,seconds-27),min(27.,seconds))]

def review(api,video,speech,script,directory,output):
    from .director_script import audio_review
    directory=Path(directory)/"listening";directory.mkdir(parents=True,exist_ok=True)
    output=Path(output);report=output/"final-listening.json"
    signature=key("mixed-listen-v1",speech.get("fingerprint"),script.get("fingerprint"),Path(video).stat().st_size)
    if report.exists():
        previous=read_json(report)
        if previous.get("fingerprint")==signature:return previous
    seconds=duration(video);parts=[];sections=sample_sections(seconds)
    for index,(start,length) in enumerate(sections):
        path=directory/f"section-{index}.wav"
        ffmpeg("-ss",str(start),"-i",video,"-t",str(length),"-vn","-ar","24000","-ac","1","-c:a","pcm_s16le",path)
        parts.append(path)
    listing=directory/"parts.txt"
    listing.write_text("\n".join("file '"+str(p.resolve()).replace("'","'\\''")+"'" for p in parts))
    sample=output/"listening-sample.wav"
    ffmpeg("-f","concat","-safe","0","-i",listing,"-c:a","copy",sample)
    measured={"sampled_sections":[{"start":a,"seconds":b} for a,b in sections],
      "full_video_seconds":seconds,"voice":speech["voice"],
      "review_edits":"Opening, middle and ending excerpts are joined only for this listening sample.",
      "listen_for":"Natural voice, intelligibility, music masking, harshness, distortion and a calm resolved ending. Do not treat review-sample joins as actual film cuts."}
    try:
        heard=audio_review(api,sample,measured)
        for field in ("naturalness","clarity","rhythm"):
            if type(heard.get(field)) is not int or not 1<=heard[field]<=10:raise PipelineError("Listening model returned an invalid score")
        if type(heard.get("overacted")) is not bool:raise PipelineError("Listening model omitted performance assessment")
        result={"assessed":True,"review":heard,"model_error":None}
    except (PipelineError,ValueError,KeyError,IndexError) as exc:
        result={"assessed":False,"review":None,"model_error":str(exc)}
    result.update(fingerprint=signature,scope="Sampled actual final AAC soundtrack; no historical review",
      sections=measured["sampled_sections"],audio_file=sample.name)
    save_json(report,result);return result
