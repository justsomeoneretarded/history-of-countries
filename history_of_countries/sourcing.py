"""Measured footage coverage and visible holds; technical success is not editorial readiness."""
import os
from .core import PipelineError
from .planning import VIDEO

def assess(script,catalog,shots,required=True):
    try:minimum=float(os.getenv("FOOTAGE_MIN_FRACTION","0.25"))
    except ValueError:raise PipelineError("FOOTAGE_MIN_FRACTION must be numeric") from None
    if not .05<=minimum<=.8:raise PipelineError("FOOTAGE_MIN_FRACTION must be between 0.05 and 0.8")
    records={a["id"]:a for a in catalog["assets"]}
    total=sum(s["global_end"]-s["global_start"] for s in shots)
    moving=0.;youtube_seconds=0.;covered=set();holds=[];current=None;image_area=0.;image_time=0.
    for shot in shots:
        asset=records[shot["asset_id"]];seconds=shot["global_end"]-shot["global_start"]
        if asset.get("medium") in VIDEO:
            actual=max(0.,seconds-float(shot.get("outro_hold_seconds",0)))
            moving+=actual;covered.add(str(shot["scene_id"]))
            if asset.get("provider")=="YouTube Creative Commons":youtube_seconds+=actual
            current=None
        else:
            if current and current["asset_id"]==shot["asset_id"] and abs(current["end"]-shot["global_start"])<.05:
                current["end"]=shot["global_end"];current["seconds"]+=seconds
            else:
                current={"asset_id":shot["asset_id"],"subject":asset.get("subject"),"start":shot["global_start"],
                         "end":shot["global_end"],"seconds":seconds}
                holds.append(current)
            w,h=asset.get("width",0),asset.get("height",0)
            if w and h:
                ratio=w/h/(16/9)
                image_area+=min(ratio,1/ratio)*seconds;image_time+=seconds
    fraction=moving/max(total,.01);failures=[];warnings=[]
    if required and fraction<minimum:
        failures.append(f"Moving footage covers {fraction:.1%}; required minimum is {minimum:.0%}. Export remains a draft.")
    long_holds=sorted((h for h in holds if h["seconds"]>10),key=lambda h:-h["seconds"])
    if long_holds:warnings.append(f"{len(long_holds)} unchanged image holds exceed 10 seconds.")
    fill=image_area/image_time if image_time else None
    if fill is not None and fill<.8:warnings.append("Many images need substantial background fill; source more frames close to 16:9.")
    if required and not youtube_seconds:warnings.append("No YouTube footage reached the actual edit; see discovery reasons.")
    return {"passed":not failures,"required":required,"status":"needs_sourcing" if failures else "passed",
            "minimum_footage_fraction":minimum,"duration_seconds":round(total,3),
            "moving_footage_seconds":round(moving,3),"moving_footage_fraction":round(fraction,5),
            "youtube_footage_seconds":round(youtube_seconds,3),"scenes_with_footage":len(covered),
            "scenes_without_footage":[str(s["scene_id"]) for s in script["scenes"] if str(s["scene_id"]) not in covered],
            "average_image_foreground_fill":round(fill,4) if fill is not None else None,
            "long_unchanged_images":long_holds,"failures":failures,"warnings":warnings,
            "discovery":catalog.get("footage_research",{}),
            "scope":"Actual edited timeline; moving-footage supply, repeated stills and frame use. No retention prediction or factual approval."}
