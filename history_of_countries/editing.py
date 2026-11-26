"""Subpixel image motion and ordinary footage cuts; no character animation."""
from pathlib import Path
import math
import subprocess
import numpy as np
import cairocffi as cairo
from PIL import Image,ImageOps,ImageFilter
from .core import PipelineError,ffmpeg,duration,key,save_json
from .planning import VIDEO

PROFILES={"cinematic":(1920,1080,30),"preview":(960,540,30)}

def pose(progress,motion):
    p=max(0.,min(1.,float(progress)));u=p*p*(3-2*p)
    zoom=1.045-.045*u if motion=="out" else 1.+.045*u if motion=="in" else 1.045
    pan=(-1 if motion=="left" else 1)*(.5-u)*.035 if motion in {"left","right"} else 0.
    return zoom,pan

def _surface(image):
    rgb=np.asarray(image.convert("RGB"),dtype=np.uint8)
    data=np.empty((image.height,image.width,4),dtype=np.uint8)
    data[:,:,:3]=rgb[:,:,::-1];data[:,:,3]=255
    return cairo.ImageSurface.create_for_data(data,cairo.FORMAT_RGB24,image.width,image.height),data

def render_image(asset,shot,path,profile):
    width,height,fps=PROFILES[profile];frames=shot["frames"]
    with Image.open(asset["path"]) as source:
        source=ImageOps.exif_transpose(source).convert("RGB")
        source.thumbnail((2600,2000),Image.Resampling.LANCZOS)
        portrait=source.width/source.height<1.35
        backdrop=ImageOps.fit(source,(width,height),method=Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(max(8,width/80)))
        backdrop=Image.blend(backdrop,Image.new("RGB",backdrop.size,"#12232a"),.35)
        art=source.copy()
    image,data=_surface(art);background,bg_data=_surface(backdrop)
    canvas=cairo.ImageSurface(cairo.FORMAT_RGB24,width,height);context=cairo.Context(canvas)
    base=min(width/art.width,height/art.height) if portrait else max(width/art.width,height/art.height)
    command=["ffmpeg","-hide_banner","-loglevel","error","-nostdin","-y","-f","rawvideo","-pix_fmt","bgr0",
      "-s",f"{width}x{height}","-r",str(fps),"-i","pipe:0","-frames:v",str(frames),"-an",
      "-c:v","libx264","-preset","veryfast","-crf","19","-pix_fmt","yuv420p","-threads","2","-movflags","+faststart",str(path)]
    errors=path.with_suffix(".stderr")
    with errors.open("wb") as stderr:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=stderr)
        try:
            for index in range(frames):
                zoom,pan=pose(index/max(1,frames-1),shot["motion"]);scale=base*zoom
                context.set_source_surface(background,0,0);context.paint()
                context.save()
                context.translate((width-art.width*scale)/2+pan*width,(height-art.height*scale)/2)
                context.scale(scale,scale);pattern=cairo.SurfacePattern(image);pattern.set_filter(cairo.FILTER_BILINEAR)
                context.set_source(pattern);context.paint();context.restore();canvas.flush()
                process.stdin.write(canvas.get_data())
            process.stdin.close()
            if process.wait(timeout=max(120,frames/fps*8)):raise PipelineError(errors.read_text()[-2000:])
        except BaseException:
            if process.poll() is None:process.kill();process.wait()
            raise
    errors.unlink(missing_ok=True)

def render_shot(asset,shot,directory,profile="cinematic"):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    identity=key("simple-shot-v1",asset["id"],asset.get("sha256",""),shot,profile)
    output=directory/(identity+".mp4")
    expected=shot["frames"]/PROFILES[profile][2]
    if output.exists() and abs(duration(output)-expected)<.05:return output
    if asset.get("medium") in VIDEO:
        width,height,fps=PROFILES[profile]
        filters=f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x12232a,setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration=0.04,format=yuv420p"
        ffmpeg("-ss",str(shot.get("source_start",0)),"-i",asset["path"],"-vf",filters,
          "-frames:v",str(shot["frames"]),"-an","-c:v","libx264","-preset","veryfast",
          "-crf","19","-threads","2","-movflags","+faststart",output)
    else:render_image(asset,shot,output,profile)
    if abs(duration(output)-expected)>.05:raise PipelineError("A visual shot did not preserve the frame duration")
    return output

def concat(paths,output):
    listing=output.with_suffix(".concat.txt")
    listing.write_text("\n".join("file '"+str(Path(p).resolve()).replace("'","'\\''")+"'" for p in paths))
    ffmpeg("-f","concat","-safe","0","-i",listing,"-c","copy",output)

def _clock(seconds,separator=","):
    ms=round(float(seconds)*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f"{h:02}:{m:02}:{s:02}{separator}{ms:03}"

def captions(script,speech,output,width,height):
    lines=[];years=[];position=0
    by_id={str(s["scene_id"]):s for s in speech["scenes"]}
    for scene in script["scenes"]:
        spoken=by_id[str(scene["scene_id"])]
        for cue in spoken["captions"]:
            lines.extend([str(len(lines)//4+1),_clock(position+cue["start"])+" --> "+_clock(position+cue["end"]),cue["text"],""])
        start=position;position+=spoken["duration"]
        safe=str(scene["date_label"]).replace("{","").replace("}","").replace("\\","").replace("\n"," ")
        def ass(t):
            cs=round(t*100);h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100)
            return f"{h}:{m:02}:{s:02}.{cs:02}"
        years.append(f"Dialogue: 0,{ass(start)},{ass(position)},Date,,0,0,0,,{safe}")
    (output/"captions.srt").write_text("\n".join(lines))
    header=f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Date,DejaVu Sans,{round(width*.021)},&H00FFFFFF,&H00FFFFFF,&H80122129,&H80122129,-1,0,0,0,100,100,0,0,1,2,0,7,{round(width*.035)},0,{round(height*.035)},1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    (output/"years.ass").write_text(header+"\n".join(years)+"\n")
