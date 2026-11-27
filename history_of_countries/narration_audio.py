"""Light chapter-level voice mastering; keep the original Gemini performance."""
import json,re,subprocess
from pathlib import Path
from .core import PipelineError,ffmpeg,duration,key,read_json,save_json

FILTER="highpass=f=70,equalizer=f=2800:t=q:w=0.8:g=1,acompressor=threshold=0.125:ratio=1.8:attack=15:release=120"
VERSION="voice-master-v1"

def master(audio,directory):
    audio=Path(audio);directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    signature=key(VERSION,audio.name,audio.stat().st_size)
    path=directory/(signature+".wav");report=directory/(signature+".json")
    if path.exists() and report.exists():return path,read_json(report)
    result=subprocess.run(["ffmpeg","-hide_banner","-nostdin","-i",str(audio),"-af",
      FILTER+",loudnorm=I=-19:TP=-3:LRA=8:print_format=json","-f","null","-"],
      capture_output=True,text=True,timeout=300)
    matches=re.findall(r'\{\s*"input_i".*?\}',result.stderr,re.S)
    if result.returncode or not matches:raise PipelineError("Cannot measure chapter voice")
    loud=json.loads(matches[-1])
    norm=f'loudnorm=I=-19:TP=-3:LRA=8:measured_I={loud["input_i"]}:measured_TP={loud["input_tp"]}:measured_LRA={loud["input_lra"]}:measured_thresh={loud["input_thresh"]}:offset={loud["target_offset"]}:linear=true'
    ffmpeg("-i",audio,"-af",FILTER+","+norm,"-ar","24000","-ac","1","-c:a","pcm_s16le",path)
    before,after=duration(audio),duration(path)
    if abs(before-after)>.03:raise PipelineError("Voice mastering changed narration timing")
    data={"version":VERSION,"input_seconds":before,"output_seconds":after,
      "target_lufs":-19,"target_true_peak_dbfs":-3,"time_stretch_applied":False,
      "treatment":"70 Hz high-pass, gentle presence EQ, light compression and measured chapter-level normalization",
      "original_audio":audio.name}
    save_json(report,data);return path,data
