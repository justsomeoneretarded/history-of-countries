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
    path=tmp_path/"preview.mp4"
    ffmpeg("-f","lavfi","-i","testsrc2=size=320x180:rate=15","-t","60","-an","-c:v","libx264","-pix_fmt","yuv420p",path)
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


def test_twentieth_century_archive_cannot_illustrate_ancient_or_medieval_events():
    info={"title":"Ethiopian cavalry 1935 newsreel","description":"Ethiopian soldiers"}
    for label in ("340 AD","12th Century","500 BCE"):
        assert not youtube.related(info,scene(asset_search_term="Ethiopian cavalry",date_label=label))


def test_modern_adwa_terrain_is_context_and_cannot_become_period_battle_film():
    info={"title":"Adwa hills Ethiopia drone 2024","description":"Present-day terrain"}
    passage=scene(location="Adwa",asset_search_term="Oreste Baratieri Adwa portrait",date_label="1896",narration="Columns moved into the hills around Adwa.")
    assert youtube.related(info,passage)
    assert search.context(info,passage)["presentation"]=="present_day_place_or_object"


def test_sourcing_failure_is_resolved_before_tts_quota_is_spent(tmp_path,monkeypatch):
    from history_of_countries import runner
    from history_of_countries.core import save_json
    calls=[]
    def write(args):
        calls.append(args[args.index("--stage")+1])
        work=Path(args[args.index("--work")+1])
        save_json(work/"script.json",{"title":"Ethiopia","scenes":[scene()]})
        return 0
    def missing(*args,**kwargs):raise PipelineError("No reusable media")
    monkeypatch.setattr(runner.director_script,"main",write)
    monkeypatch.setattr(runner.bootstrap,"ensure",lambda *args:None)
    monkeypatch.setattr(runner.media,"build",missing)
    with pytest.raises(PipelineError,match="No reusable media"):
        runner.run({"title":"Ethiopia","brief":"Choices and consequences."},tmp_path/"work",tmp_path/"output")
    assert calls==["plan"]

def test_multiple_excerpts_from_one_work_need_one_description_attribution():
    from history_of_countries.packaging import compact_attribution
    common={"title":"Ethiopia archive newsreel","source_url":"https://www.youtube.com/watch?v=abcdefghijk",
            "creator":"Archive channel","license":"CC BY 3.0","license_url":"https://creativecommons.org/licenses/by/3.0/"}
    text=compact_attribution([{**common,"subject":"Troops marching"},{**common,"subject":"Vehicles arriving"}])
    assert text.count(common["source_url"])==1
    assert "Ethiopia archive newsreel" in text


def test_historical_recording_date_is_distinct_from_upload_and_remaster_year():
    passage=scene(asset_search_term="Ethiopian cavalry",date_label="1941")
    info={"title":"Ethiopian cavalry archive uploaded 2024","description":"Original footage 1941.",
          "upload_date":"20241102"}
    assert youtube.related(info,passage)
    match=search.context(info,passage)
    assert match["candidate_event_years"]==[1941]
    assert match["upload_date"]=="20241102"
    assert not youtube.related(info,{**passage,"date_label":"1896"})
    info["title"]="Ethiopian cavalry 1941 remastered 2024"
    assert search.dated_event_evidence(info)=={1941}


def test_failed_discovery_process_cannot_reuse_footage_from_another_script(tmp_path,monkeypatch):
    import subprocess
    from history_of_countries.core import save_json,key
    save_json(tmp_path/"discovery.json",{"assets":[{"id":"old-country"}],"scenes":{"1":["old-country"]},"provider_status":[]})
    class Failed:
        def __init__(self,*a,**k):pass
        def wait(self,*a,**k):return 1
    monkeypatch.setattr(subprocess,"Popen",Failed)
    script={"title":"Ethiopia","scenes":[scene()]}
    result=youtube.bounded(script,tmp_path,timeout=1)
    assert result["assets"]==[]
    assert result["script_fingerprint"]==key(script)
    assert result["provider_status"][-1]["reason"]=="extractor_process_failed"


def test_native_whole_download_fallback_cuts_approved_interval_and_reuses_source(tmp_path):
    import shutil
    from history_of_countries.core import duration
    raw=tmp_path/"original.mp4"
    ffmpeg("-f","lavfi","-i","testsrc2=size=640x360:rate=15","-t","30","-an","-c:v","libx264","-pix_fmt","yuv420p",raw)
    class Native:
        whole_calls=0
        def __init__(self,settings):self.settings=settings
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def download(self,urls):
            if "download_ranges" in self.settings:raise PipelineError("fixture FFmpeg range 403")
            Native.whole_calls+=1
            path=Path(self.settings["outtmpl"].replace("%(ext)s","mp4"))
            path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(raw,path)
    info={"id":"abcdefghijk","duration":30}
    a=youtube.download_excerpt(info,10,18,tmp_path/"clips/a.mp4",ydl_factory=Native)
    b=youtube.download_excerpt(info,20,28,tmp_path/"clips/b.mp4",ydl_factory=Native)
    assert duration(a)==pytest.approx(8,abs=.1)
    assert duration(b)==pytest.approx(8,abs=.1)
    assert Native.whole_calls==1
    assert read_json(a.with_suffix(".acquisition.json"))["method"]=="native_whole_download_then_local_cut"


def test_historical_place_aliases_survive_foreign_language_discovery():
    info={"title":"Axum churches walking tour 2024","description":"Abyssinia monuments"}
    passage=scene(asset_search_term="Aksum churches monuments",location="Aksum")
    assert youtube.related(info,passage)
    assert search.words("Adoua Adowa Adwa")=={"adwa"}


def test_camera_asset_ranks_above_keyword_stuffed_explainers_and_music():
    script={"title":"Ethiopia","scenes":[scene()]}
    candidates=[
        {"id":"music","title":"Lalibela Official Music Video","query_scene_ids":["1"]},
        {"id":"essay","title":"Lalibela churches: The Untold Story","query_scene_ids":["1"]},
        {"id":"camera","title":"Lalibela walking tour 4K","query_scene_ids":["1"]}]
    assert search.fair_shortlist(candidates,script,1)[0]["id"]=="camera"
    assert all(x["id"]!="music" for x in search.fair_shortlist(candidates,script,3))

def test_review_budget_includes_late_chapters_and_ending():
    chapters=["Hook"]*2+["Roots"]*6+["Catalyst"]*5+["Turning Point"]*6+["Aftermath"]*5
    script={"title":"Ethiopia","scenes":[scene(i,chapter=c) for i,c in enumerate(chapters,1)]}
    ordered=search.scene_review_order(script)
    assert "24" in ordered[:10]
    assert len(ordered)==24 and len(set(ordered))==24

def test_synthetic_reconstruction_cannot_pass_conflicting_real_footage_flags():
    info={"id":"abcdefghijk","title":"Yohannes IV","duration":200}
    passage=scene(asset_search_term="Yohannes",location="Ethiopian Highlands",date_label="1889")
    row=segment(presentation="period_event",historical_period_supported=True,
                period_evidence="Reconstruction of a nineteenth-century royal court.")
    raw={"summary":"Cinematic AI-generated historical reconstruction.","segments":[row]}
    result=review.validate_segments(raw,info,[passage],[(60,120)])
    assert not result["segments"]
    assert "synthetic" in result["rejected_segments"][0]["reason"].lower()
    raw={"summary":"A historical scene.","source_kind":"synthetic","segments":[row]}
    assert not review.validate_segments(raw,info,[passage],[(60,120)])["segments"]

def test_minor_quote_punctuation_can_be_repaired_but_unrelated_words_cannot():
    text="At Lalibela, churches were carved into the rock."
    assert review.spoken_anchor("At Lalibela churches",text)=="At Lalibela, churches"
    assert review.spoken_anchor("A completely unrelated army invaded",text) is None

def test_explicit_spoken_anchor_id_avoids_model_paraphrase_rejections():
    row=segment(anchor_id="1:1",narration_anchor="A paraphrase of the supplied sentence")
    result=review.validate_segments({"segments":[row]},source(),[scene()],[(60,120)])
    assert result["segments"][0]["narration_anchor"]==scene()["narration"]
    row["anchor_id"]="1:999"
    assert not review.validate_segments({"segments":[row]},source(),[scene()],[(60,120)])["segments"]

def test_clean_short_camera_shots_and_longer_seen_intervals_are_usable():
    for start,end,expected in [(80,84,4),(60,110,30)]:
        result=review.validate_segments({"segments":[segment(start=start,end=end)]},source(),[scene()],[(60,120)])
        assert result["segments"][0]["end"]-result["segments"][0]["start"]==expected


def test_explicit_authentication_challenge_stops_youtube_before_model_calls(tmp_path):
    class Blocked:
        def __init__(self,options):self.options=options
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def extract_info(self,*a,**kw):
            self.options["logger"].warning("Sign in to confirm you're not a bot.")
            return {"id":"aqz-KE-bpKQ","title":"Public compatibility check","formats":[]}
    class NoModel:
        def text(self,*args,**kwargs):raise AssertionError("No model call for inaccessible downloads")
    result=youtube.discover({"title":"Ethiopia","scenes":[scene()]},tmp_path,ydl_factory=Blocked,api=NoModel())
    assert result["summary"]["attempted_queries"]==0
    assert result["provider_status"][0]["reason"]=="authentication_required_on_hosted_runner"
    assert not result["assets"]

def test_primary_archive_licences_and_event_years_are_explicit():
    from history_of_countries.open_footage import license_record
    assert license_record("http://creativecommons.org/licenses/publicdomain/")["license"]=="Public domain"
    assert license_record("https://creativecommons.org/licenses/by/4.0/")["license"]=="CC BY 4.0"
    assert license_record("") is None
    assert license_record("https://creativecommons.org/licenses/by-nc/4.0/") is None
    info={"title":"25 Years Ago, 1960/09/22","depicted_years":[1935]}
    assert search.dated_event_evidence(info)=={1935}

def test_insufficient_youtube_supply_uses_direct_sources_without_relabelling_them(tmp_path,monkeypatch):
    from history_of_countries import footage
    monkeypatch.setattr(footage.youtube,"bounded",lambda *a,**k:{"assets":[],"scenes":{},"provider_status":[],
        "inspection_reports":[],"summary":{"accepted_clips":0}})
    monkeypatch.setattr(footage,"MediaAPI",lambda *a:object())
    monkeypatch.setattr(footage.footage_verify,"verify",lambda api,assets,path:(assets,[]))
    movie={"id":"archive-camera","provider":"Internet Archive","duration_seconds":20}
    monkeypatch.setattr(footage.open_footage,"discover",lambda *a,**k:{"assets":[movie],"scenes":{"1":[movie["id"]]},
        "provider_status":[],"inspection_reports":[],"summary":{"accepted_clips":1}})
    result=footage.discover({"title":"Ethiopia","scenes":[scene()]},tmp_path)
    assert result["summary"]["youtube"]["accepted_clips"]==0
    assert result["summary"]["accepted_clips"]==1
    assert result["assets"][0]["provider"]=="Internet Archive"


def test_researched_camera_excerpts_reuse_only_for_same_script_and_unchanged_bytes(tmp_path):
    import hashlib
    from history_of_countries.core import key
    movie=tmp_path/"camera.mp4";movie.write_bytes(b"accepted-source-fixture")
    script={"title":"Ethiopia","scenes":[scene()]}
    report={"script_fingerprint":key(script),"assets":[{"path":str(movie),"sha256":hashlib.sha256(movie.read_bytes()).hexdigest(),
            "source_url":"https://www.youtube.com/watch?v=abcdefghijk",
            "inspection":{"camera_origin":"recorded_camera","clean_frame":True}}],
            "inspection_reports":[{"source_id":"abcdefghijk","source_kind":"camera"}]}
    assert youtube.reusable_discovery(report,script,tmp_path)
    assert not youtube.reusable_discovery(report,{"title":"Japan","scenes":[scene()]},tmp_path)
    movie.write_bytes(b"changed")
    assert not youtube.reusable_discovery(report,script,tmp_path)
