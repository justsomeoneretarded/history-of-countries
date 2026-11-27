"""Complete source images and genuine footage; clean editorial cuts, no animation."""
from pathlib import Path
from PIL import Image,ImageOps,ImageFilter,ImageDraw
from .core import PipelineError,ffmpeg,duration,key
from .planning import VIDEO
from .typography import font

PROFILES={"cinematic":(1920,1080,30),"preview":(960,540,30)}

def fit_rect(source_size,frame_size):
    sw,sh=source_size;fw,fh=frame_size
    if min(sw,sh,fw,fh)<=0:raise PipelineError("Invalid source dimensions")
    scale=min(fw/sw,fh/sh)
    width,height=max(1,round(sw*scale)),max(1,round(sh*scale))
    return ((fw-width)//2,(fh-height)//2,width,height)

def complete_image(source,size,side_fill="subtle"):
    """The foreground always contains the entire original; never cover/crop it."""
    source=ImageOps.exif_transpose(source).convert("RGB")
    width,height=size;x,y,w,h=fit_rect(source.size,size)
    if side_fill=="plain":canvas=Image.new("RGB",size,"#111a20")
    else:
        canvas=ImageOps.fit(source,size,method=Image.Resampling.LANCZOS)
        canvas=canvas.filter(ImageFilter.GaussianBlur(max(12,width/45)))
        canvas=Image.blend(canvas,Image.new("RGB",size,"#111a20"),.48)
    canvas.paste(source.resize((w,h),Image.Resampling.LANCZOS),(x,y))
    return canvas

def date_overlay(size,label):
    layer=Image.new("RGBA",size)
    if not label:return layer
    width,height=size;face=font(max(10,round(width*.017)),True)
    label=" ".join(str(label).split())[:50];draw=ImageDraw.Draw(layer)
    margin=round(width*.03);pad=round(width*.009);box=draw.textbbox((0,0),label,font=face)
    w=box[2]-box[0];h=box[3]-box[1]
    draw.rounded_rectangle((margin,margin,margin+w+pad*2,margin+h+pad*2),radius=max(3,round(width*.003)),fill=(12,20,27,175))
    draw.text((margin+pad-box[0],margin+pad-box[1]),label,font=face,fill=(248,248,246,255))
    return layer

def render_image(asset,shot,path,profile):
    width,height,fps=PROFILES[profile]
    with Image.open(asset["path"]) as source:
        frame=complete_image(source,(width,height),shot.get("side_fill","subtle"))
    frame=Image.alpha_composite(frame.convert("RGBA"),date_overlay((width,height),shot.get("year_label","")))
    still=path.with_suffix(".png");frame.convert("RGB").save(still)
    try:
        ffmpeg("-loop","1","-framerate",str(fps),"-i",still,"-frames:v",str(shot["frames"]),"-an",
          "-c:v","libx264","-preset","veryfast","-tune","stillimage","-crf","18",
          "-pix_fmt","yuv420p","-threads","2","-movflags","+faststart",path)
    finally:still.unlink(missing_ok=True)

def render_shot(asset,shot,directory,profile="cinematic"):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    identity=key("simple-shot-v3-complete-source",asset["id"],asset.get("sha256",""),shot,profile)
    output=directory/(identity+".mp4")
    expected=shot["frames"]/PROFILES[profile][2]
    if output.exists() and abs(duration(output)-expected)<.05:return output
    if asset.get("medium") in VIDEO:
        width,height,fps=PROFILES[profile]
        filters=f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x111a20,setsar=1,fps={fps},tpad=stop_mode=clone:stop_duration=0.04,format=yuv420p"
        inputs=["-ss",str(shot.get("source_start",0)),"-i",asset["path"]]
        year=str(shot.get("year_label","")).strip()
        if year:
            png=directory/(identity+"-date.png");date_overlay((width,height),year).save(png)
            inputs+=["-i",png]
            video_filter=["-filter_complex",f"[0:v]{filters}[picture];[picture][1:v]overlay=0:0:format=auto[v]","-map","[v]"]
        else:video_filter=["-vf",filters];png=None
        try:
            ffmpeg(*inputs,*video_filter,"-frames:v",str(shot["frames"]),"-an","-c:v","libx264","-preset","veryfast",
              "-crf","18","-pix_fmt","yuv420p","-threads","2","-movflags","+faststart",output)
        finally:
            if png:png.unlink(missing_ok=True)
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
    lines=[];position=0
    by_id={str(s["scene_id"]):s for s in speech["scenes"]}
    for scene in script["scenes"]:
        spoken=by_id[str(scene["scene_id"])]
        for cue in spoken["captions"]:
            lines.extend([str(len(lines)//4+1),_clock(position+cue["start"])+" --> "+_clock(position+cue["end"]),cue["text"],""])
        position+=spoken["duration"]
    (output/"captions.srt").write_text("\n".join(lines))
