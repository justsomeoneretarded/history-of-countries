from __future__ import annotations
import json
import math
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
from .core import PipelineError, duration, ffmpeg, probe, read_json, save_json, public_text
from .typography import font


def review_frames(video,output):
    length=duration(video)
    frames=[]
    for i in range(12):
        target=output/f'review-{i:02}.jpg'
        ffmpeg('-ss',str((i+.5)*length/12),'-i',video,'-frames:v','1','-vf','scale=480:270',target)
        frames.append(target)
    sheet=Image.new('RGB',(480*3,300*4),(10,16,22));draw=ImageDraw.Draw(sheet)
    for i,path in enumerate(frames):
        with Image.open(path) as im:sheet.paste(im,(i%3*480,i//3*300))
        draw.text((i%3*480+10,i//3*300+274),f'{(i+.5)*length/12:.1f}s',font=font(17),fill='white')
        path.unlink()
    sheet.save(output/'contact-sheet.jpg',quality=92)

def inspect(video,script,speech,assets,output):
    metadata=probe(video)
    streams=metadata['streams']
    video_stream=next((s for s in streams if s['codec_type']=='video'),None)
    audio_stream=next((s for s in streams if s['codec_type']=='audio'),None)
    failures=[]
    if not video_stream or not audio_stream:
        failures.append('Missing video or audio stream')
    render_info=read_json(output/'render.json')
    expected=sum(s['duration'] for s in speech['scenes'])+render_info.get('credits_seconds',0)+render_info.get('interlude_seconds',0);actual=float(metadata['format']['duration'])
    if abs(actual-expected)>.5:
        failures.append('Video/audio duration mismatch')
    bad=[s['scene_id'] for s in speech['scenes'] if not s['verification']['accepted']]
    if bad:failures.append('Unverified speech scenes')
    # One complete pass checks decoding, black intervals and actual final AAC loudness.
    import subprocess
    detection=subprocess.run(['ffmpeg','-hide_banner','-nostdin','-i',str(video),'-vf','blackdetect=d=0.6:pix_th=0.10','-af','loudnorm=I=-16:TP=-1:LRA=9:print_format=json','-f','null','-'],capture_output=True,text=True,timeout=max(600,actual*3))
    if detection.returncode:failures.append('Final media decode failed')
    loudness=re.findall(r'\{\s*"input_i".*?\}',detection.stderr,re.S)
    measured=json.loads(loudness[-1]) if loudness else {}
    if not measured:failures.append('Could not measure final encoded soundtrack')
    elif float(measured['input_tp'])>-.05:failures.append('Final soundtrack has insufficient clipping headroom')
    black=[float(x) for x in re.findall(r'black_duration:([\d.]+)',detection.stderr)]
    if any(x>1 for x in black):failures.append('Unexpected black interval over one second')
    unique=len({x['source_url'] for entry in assets.values() for x in entry['assets']})
    report={'passed':not failures,'failures':failures,'duration_seconds':actual,'expected_total_seconds':expected, 'narration_seconds':sum(s['duration'] for s in speech['scenes']), 'credits_seconds':render_info.get('credits_seconds',0),
        'voice':speech['voice'],'scene_count':len(script['scenes']),'unique_licensed_assets':unique,
        'speech_coverage_min':min(s['verification']['coverage'] for s in speech['scenes']),
        'speech_precision_min':min(s['verification']['precision'] for s in speech['scenes']),
        'caption_interpolated_words':sum(w.get('interpolated',False) for s in speech['scenes'] for w in s['words']),
        'black_intervals_seconds':black,'final_audio_lufs':float(measured['input_i']) if measured else None,
        'final_audio_true_peak_dbfs':float(measured['input_tp']) if measured else None,'video':video_stream,'audio':audio_stream,
        'review_needed':['Check historical visual relevance and pronunciation in contact sheet/video.',
                         'Script source references support review; automated checks do not certify historical accuracy.']}
    save_json(output/'quality.json',report)
    if failures:
        raise PipelineError('Final quality gate failed: '+'; '.join(failures))
    review_frames(video,output)
    return report

