from __future__ import annotations
import os
import re
import time
from pathlib import Path
from .core import ROOT, PipelineError, duration, key, save_json, read_json


def clean_words(text):
    return re.findall(r"[\w’'-]+", text.casefold())

def transcript(audio, recognizer):
    segments, _ = recognizer.transcribe(str(audio), language='en', beam_size=3, word_timestamps=True,
        vad_filter=True, condition_on_previous_text=False)
    cues, words = [], []
    for segment in segments:
        cues.append({'start':float(segment.start),'end':float(segment.end),'text':segment.text.strip()})
        for word in segment.words or []:
            words.append({'word':word.word.strip(),'start':float(word.start),'end':float(word.end)})
    return cues, words

def caption_groups(words, maximum=3):
    result, group = [], []
    for word in words:
        # Whisper can return empty/negative/zero duration words. Exclude invalid intervals.
        if not word.get('word','').strip() or word['end']<=word['start']:
            continue
        if group and (len(group)>=maximum or word['start']-group[-1]['end']>.35):
            result.append({'start':group[0]['start'],'end':group[-1]['end'],'text':' '.join(x['word'] for x in group)})
            group=[]
        group.append(word)
        if re.search(r'[.!?;:]$',word['word']):
            result.append({'start':group[0]['start'],'end':group[-1]['end'],'text':' '.join(x['word'] for x in group)})
            group=[]
    if group:
        result.append({'start':group[0]['start'],'end':group[-1]['end'],'text':' '.join(x['word'] for x in group)})
    return result

def align_written(script, words):
    """Map written tokens to ASR timings; preserve names/spelling and monotone timing.

    This is transcript-assisted alignment, not a claim of phoneme-level forced alignment.
    Unmatched spans interpolate only between real ASR anchors, and are reported in QA.
    """
    from difflib import SequenceMatcher
    tokens = script.split()
    left = [re.sub(r'\W','',x.casefold()) for x in tokens]
    right = [re.sub(r'\W','',x['word'].casefold()) for x in words]
    anchors={}
    for block in SequenceMatcher(None,left,right,autojunk=False).get_matching_blocks():
        for i in range(block.size):
            anchors[block.a+i] = words[block.b+i]
    if not words:
        raise PipelineError('Speech recognizer returned no word timings')
    result=[]
    for i, token in enumerate(tokens):
        if i in anchors:
            start,end=anchors[i]['start'],anchors[i]['end']
        else:
            prev=max((j for j in anchors if j<i),default=-1)
            nxt=min((j for j in anchors if j>i),default=len(tokens))
            beginning=anchors[prev]['end'] if prev>=0 else words[0]['start']
            ending=anchors[nxt]['start'] if nxt<len(tokens) else words[-1]['end']
            width=max(.02,(ending-beginning)/max(1,nxt-prev-1))
            start=beginning+(i-prev-1)*width
            end=start+width
        start=max(start,result[-1]['end'] if result else 0)
        result.append({'word':token,'start':start,'end':max(start+.02,end),'interpolated':i not in anchors})
    return result

