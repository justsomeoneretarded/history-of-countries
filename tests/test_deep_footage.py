"""Temporal acceptance, actual video decisions and production coverage contracts."""
from dataclasses import replace
from pathlib import Path
import pytest
from history_of_countries import youtube,sourcing,footage_search as search,footage_review as review
from history_of_countries.core import PipelineError,ffmpeg,read_json
from history_of_countries.runner import render

def scene(ident=1,**extra):
    return {"scene_id":ident,"chapter":"Roots","asset_search_term":"Lalibela rock hewn churches",
            "location":"Lalibela","date_label":"12th Century",
            "narration":"At Lalibela, churches were carved into the rock.",**extra}

def test_modern_filming_date_does_not_erase_surviving_medieval_subject():
    info={"title":"Lalibela churches walking tour Ethiopia 2024","description":"Rock hewn churches"}
    assert youtube.related(info,scene())
    assert search.context(info,scene())["presentation"]=="present_day_place_or_object"
    battle=scene(asset_search_term="Ethiopian cavalry",location="Adwa",date_label="1896",narration="The cavalry fought at Adwa.")
    assert not youtube.related({"title":"Ethiopian cavalry 1935","description":"Italian invasion"},battle)

def test_uploaded_today_archive_preserves_its_depicted_event_year():
    info={"title":"Ethiopian cavalry 1935 newsreel uploaded 2024","description":"Archive film"}
    assert youtube.related(info,scene(asset_search_term="Ethiopian cavalry",date_label="1935"))
    assert not youtube.related(info,scene(asset_search_term="Ethiopian cavalry",date_label="1896"))

def test_search_capacity_exceeds_old_capacity_by_100_times_and_spreads_first_round(tmp_path):
    script={"title":"The Entire History of Ethiopia","scenes":[scene(i,asset_search_term=f"Lalibela churches viewpoint {i}",location=f"Site {i}") for i in range(1,25)]}
    queries,note=search.plan_queries(None,script,tmp_path,search.Limits())
    assert len(queries)==200
    assert note["capacity_results"]>=100*15
    assert {q["scene_id"] for q in queries[:24]}=={str(i) for i in range(1,25)}
    # Cached planning resumes without spending another model request.
    class NoCall:
        def text(self,*args,**kwargs):raise AssertionError("Unexpected provider call")
    assert search.plan_queries(NoCall(),script,tmp_path,search.Limits())[0]==queries

def test_shortlist_gives_later_scenes_access_to_inspection_budget():
    script={"title":"Ethiopia","scenes":[scene(1),scene(2,asset_search_term="Gondar castles",location="Gondar")]}
    candidates=[{"id":str(i),"title":"Lalibela churches","query_scene_ids":["1"]} for i in range(20)]
    candidates.append({"id":"G","title":"Gondar castles walkthrough","query_scene_ids":["2"]})
    result=search.fair_shortlist(candidates,script,2)
    assert result[1]["id"]=="G"

def source():return {"id":"abcdefghijk","title":"Lalibela churches walking tour 2024","duration":600}
def segment(**extra):
    return {"scene_id":"1","start":80.0,"end":95.0,"presentation":"present_day_place",
            "observed":"A moving wide view of Lalibela churches carved into rock.",
            "narration_anchor":"At Lalibela, churches","confidence":.9,"real_moving_footage":True,
            "clean_frame":True,"historical_period_supported":False,
            "period_evidence":"Modern camera view of a surviving church.",**extra}

@pytest.mark.parametrize("changes",[
    {"start":20,"end":35},  # Outside the actual inspected window.
    {"start":80,"end":200}, # A model cannot request a huge download.
    {"scene_id":"999"}, {"confidence":.4}, {"real_moving_footage":False},
    {"clean_frame":False},{"narration_anchor":"Words the narrator never said"},
    {"start":float("nan")},
])
def test_unseen_wrong_or_unsuitable_clip_never_becomes_approved_footage(changes):
    result=review.validate_segments({"segments":[segment(**changes)]},source(),[scene()],[(60,120)])
    assert not result["segments"] and result["rejected_segments"]

def test_clean_modern_landmark_and_identified_period_archive_can_be_accepted():
    result=review.validate_segments({"segments":[segment()]},source(),[scene()],[(60,120)])
    assert result["segments"][0]["start"]==80
    assert result["segments"][0]["presentation"]=="present_day_place"
    war=scene(asset_search_term="Ethiopian cavalry",location="Ethiopia",date_label="1935",
              narration="The cavalry fought during the Italian invasion.")
    archive={"id":"abcdefghijk","title":"Ethiopian cavalry 1935 newsreel","duration":200}
    row=segment(presentation="period_event",historical_period_supported=True,
                period_evidence="The source identifies this as 1935 newsreel.",narration_anchor="cavalry fought")
    assert review.validate_segments({"segments":[row]},archive,[war],[(60,120)])["segments"]
    row["historical_period_supported"]=False
    assert not review.validate_segments({"segments":[row]},archive,[war],[(60,120)])["segments"]

def test_native_video_request_samples_different_source_moments_and_validates_absolute_time(tmp_path,monkeypatch):
    class Fake:
        def request(self,model,endpoint,body,kind):
            self.body=body
            import json
            return {"candidates":[{"content":{"parts":[{"text":json.dumps({"summary":"Usable landmark.","segments":[segment()]})}]}}]}
    api=Fake()
    def no_download(*a,**k):raise AssertionError("Native review must not download a preview")
    result=review.inspect(api,source(),[scene()],tmp_path,no_download)
    parts=api.body["contents"][0]["parts"]
    assert len([p for p in parts if "fileData" in p])==3
    assert result["mode"]=="Gemini_native_YouTube_video"
    assert result["segments"][0]["start"]==80

def test_sourcing_uses_visible_holds_and_actual_footage_not_encoded_cut_count(monkeypatch):
    script={"scenes":[scene()]}
    catalog={"assets":[{"id":"P","medium":"photo","width":600,"height":1200},
                       {"id":"V","medium":"video","provider":"YouTube Creative Commons"}]}
    shots=[{"scene_id":1,"asset_id":"P","global_start":i*4,"global_end":(i+1)*4} for i in range(5)]
    shots.append({"scene_id":1,"asset_id":"V","global_start":20,"global_end":24})
    result=sourcing.assess(script,catalog,shots)
    assert not result["passed"] and result["status"]=="needs_sourcing"
    assert result["long_unchanged_images"][0]["seconds"]==20
    assert result["moving_footage_seconds"]==4
    shots[-1]["global_end"]=30
    assert sourcing.assess(script,catalog,shots)["passed"]
    assert sourcing.assess(script,catalog,shots[:-1],required=False)["passed"]

def test_deep_discovery_reports_failed_searches_and_does_not_invent_clips(tmp_path,monkeypatch):
    from history_of_countries import youtube
    class Broken:
        def __init__(self,settings):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def extract_info(self,*args,**kwargs):raise RuntimeError("fixture failure")
    limits=replace(search.Limits(),max_queries=2,metadata_limit=2,review_limit=1,workers=1)
    report=youtube.discover({"title":"Ethiopia","scenes":[scene()]},tmp_path,ydl_factory=Broken,limits=limits)
    assert report["summary"]["attempted_queries"]==2
    assert not report["assets"]
    assert report["summary"]["error_counts"]=={"RuntimeError":2}
    assert read_json(tmp_path/"discovery.json")["assets"]==[]

def test_url_inspection_failure_falls_back_to_actual_downloaded_video(tmp_path):
    import json
    path=tmp_path/"preview.mp4";path.write_bytes(b"test transport bytes")
    class Fake:
        def request(self,model,endpoint,body,kind):
            self.calls=getattr(self,"calls",0)+1
            if self.calls==1:raise PipelineError("URL not supported")
            self.body=body
            return {"candidates":[{"content":{"parts":[{"text":json.dumps({"summary":"Usable.","segments":[segment()]})}]}}]}
    api=Fake()
    result=review.inspect(api,source(),[scene()],tmp_path,lambda *a,**k:path)
    assert result["mode"]=="Gemini_downloaded_video"
    assert any("inlineData" in p for p in api.body["contents"][0]["parts"])
    assert result["segments"][0]["start"]==80
