"""A complete original director's draft, with one bounded Gemini spoken edit."""
from pathlib import Path
import copy,os,re
from .core import ROOT,PipelineError,key,read_json,save_json
from .script import CHAPTERS,validate,normalize_script

FILLER=re.compile(r"\b(?:little did they know|a ticking (?:time )?bomb|the answers lie deep|the plan fails|no one coordinates properly|the cycle of power remained unbroken)\b",re.I)

def validate_edit(script,evidence,target):
    validate(script,[s["id"] for s in evidence["sources"]],target)
    words=sum(len(s["narration"].split()) for s in script["scenes"])
    if not .9*target<=words<=1.1*target:raise PipelineError("Spoken edit changed the runtime budget")
    for chapter in CHAPTERS:
        count=sum(len(s["narration"].split()) for s in script["scenes"] if s["chapter"]==chapter)
        if not 1<=count<=450:raise PipelineError("Spoken chapter exceeds the Gemini TTS intake")
    if FILLER.search(" ".join(s["narration"] for s in script["scenes"])):raise PipelineError("Remove repeated summary filler")
    return words

def apply_edit(draft,raw):
    if not isinstance(raw,dict) or not isinstance(raw.get("scenes"),list):raise PipelineError("Editor returned no scenes")
    expected={s["scene_id"] for s in draft["scenes"]};found={}
    for row in raw["scenes"]:
        if not isinstance(row,dict):raise PipelineError("Invalid spoken edit")
        ident=row.get("scene_id")
        if type(ident) is not int or ident not in expected or ident in found:raise PipelineError("Editor changed or duplicated scene IDs")
        text=row.get("narration")
        if not isinstance(text,str) or not text.strip():raise PipelineError("Empty spoken edit")
        found[ident]=" ".join(text.split())
    if set(found)!=expected:raise PipelineError("Editor omitted a narrative scene")
    result=copy.deepcopy(draft)
    for scene in result["scenes"]:scene["narration"]=found[scene["scene_id"]]
    return result

def write(api,title,brief,minutes,evidence,directory,name):
    from .director_script import script_metrics,SPEECH_STYLE
    if name!="ethiopia" or "ethiop" not in title.casefold():raise PipelineError("The Ethiopia director draft belongs only to Ethiopia")
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    draft=read_json(ROOT/"episodes/ethiopia-story.json");draft["title"]=title
    target=sum(len(s["narration"].split()) for s in draft["scenes"])
    signature=key("spoken-director-edit-v2-story-stakes",draft,brief,minutes,SPEECH_STYLE,os.getenv("GEMINI_EDITOR_MODEL","gemini-3.5-flash-lite"))
    path=directory/"script.json"
    if path.exists():
        cached=read_json(path)
        if cached.get("fingerprint")==signature:
            validate_edit(cached,evidence,target);return cached
    validate_edit(draft,evidence,target)
    shape={"type":"object","required":["scenes"],"properties":{"scenes":{"type":"array","items":{
      "type":"object","required":["scene_id","narration"],"properties":{"scene_id":{"type":"integer"},"narration":{"type":"string"}}}}}}
    instruction=(
      "You are a documentary dialogue editor. Polish this ORIGINAL director's draft for an attentive, natural human narrator. "
      "Preserve every scene ID and scene order. Return the entire narration of every scene, even when unchanged. "
      "Preserve supported claims, qualifications, chronology, named people and the November 2022 endpoint. Add no facts or quotations. "
      "Keep the opening concrete and immediate: an army's expectation collides with what happens. Raise a question the ending actually answers. "
       "Make the middle move through choices and consequences, with clear transitions across centuries. "
      "Give each passage a fresh development: someone wants something, meets an obstacle, chooses, and changes another person's situation. "
      "Improve weak passages substantively; returning every sentence unchanged is only appropriate if no better spoken version exists. "
      "Remove repeated statements about unity, legitimacy or authority when the previous passage already made the point. "
      "Keep the wry observations about rulers' contradictions and let concrete reversals provide the entertainment. Never force jokes. "
      "Put understandable stakes before an unfamiliar surname. Deliver the causes promised by the hook and avoid constant teasers. "
      "Prefer language somebody says aloud. Vary sentence length and let difficult events breathe. Understate irony; never joke about suffering. "
      "Delete repetitions and vague summary sentences. Do not make every paragraph end with a dramatic slogan. "
      "Do not force a fixed number of short sentences. Avoid trailers, lectures, breathless hype and fake mysteries. "
      "Keep the final line decisive and specific; no subscription request, channel names, chapter announcements, source codes or 'in conclusion'. "
      f"Keep total length within 8 percent of {target} words; each chapter stays below 450. "
      "Return only the JSON narration edit. This is an editorial pass, not a new historical-review workflow.")
    accepted=draft;mode="original_director_draft";error=None
    try:
        raw=api.text(instruction,{"brief":brief,"draft":draft},shape,max_output=14000,
          model=os.getenv("GEMINI_EDITOR_MODEL","gemini-3.5-flash-lite"))
        candidate=apply_edit(draft,raw);validate_edit(candidate,evidence,target)
        accepted=candidate;mode="original_director_draft_with_Gemini_spoken_edit"
    except PipelineError as exc:
        error=str(exc);print("Using the complete original director draft: "+error,flush=True)
    accepted=normalize_script(accepted);metrics=script_metrics(accepted)
    accepted.update(fingerprint=signature,word_count=metrics["words"],target_seconds=minutes*60,
      script_target_words_per_minute=metrics["words"]/max(.01,minutes),provenance=mode)
    save_json(path,accepted);save_json(directory/"writing-metrics.json",metrics)
    save_json(directory/"editorial-writing.json",{"mode":mode,"model_error":error,
      "opening":accepted["scenes"][0]["narration"],"ending":accepted["scenes"][-1]["narration"],
      "word_count":metrics["words"],"chapters":metrics["chapter_words"],"manual_approval_required":False})
    (directory/"script.txt").write_text("\n\n".join(s["narration"] for s in accepted["scenes"]))
    return accepted
