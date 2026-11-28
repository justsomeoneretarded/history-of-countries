from history_of_countries import footage_review as review,footage_triage as triage
from history_of_countries.core import PipelineError


def scene():
    return {"scene_id":1,"narration":"At Lalibela, churches were carved into the rock.",
            "date_label":"12th Century","location":"Lalibela","asset_search_term":"Lalibela rock hewn churches"}


def segment(**extra):
    return {"scene_id":"1","start":8,"end":18,"presentation":"present_day_place",
            "observed":"A moving wide view of the rock churches at Lalibela.","anchor_id":"1:1",
            "narration_anchor":"At Lalibela","confidence":.9,"real_moving_footage":True,
            "clean_frame":True,"historical_period_supported":False,
            "period_evidence":"Modern camera view of surviving churches.","camera_origin":"recorded_camera",**extra}


def test_explicit_relative_times_map_to_only_the_declared_seen_input():
    info={"id":"abcdefghijk","title":"Lalibela walking tour","duration":600}
    raw={"source_kind":"camera","segments":[segment(timebase="clip_relative",input_index=1)]}
    windows=[(60,120),(240,300)]
    result=review.validate_segments(raw,info,[scene()],windows)
    accepted=result["segments"][0]
    assert (accepted["start"],accepted["end"])==(248,258)
    # Saved absolute seconds must never be offset again on resume.
    assert review.validate_segments(result,info,[scene()],windows)["segments"][0]["start"]==248
    raw["segments"][0]["end"]=65
    assert not review.validate_segments(raw,info,[scene()],windows)["segments"]
    raw["segments"][0].update(end=18,input_index=99)
    assert not review.validate_segments(raw,info,[scene()],windows)["segments"]


def test_unmarked_outside_window_timestamps_are_not_guessed_as_relative():
    info={"id":"abcdefghijk","title":"Lalibela walking tour","duration":600}
    assert not review.validate_segments({"segments":[segment()]},info,[scene()],[(60,120)])["segments"]


def test_generic_political_anchor_cannot_become_cathedral_interior_footage():
    info={"id":"abcdefghijk","title":"Holy Trinity Cathedral Addis Ababa walking tour","duration":600}
    passage={"scene_id":1,"location":"Addis Ababa","asset_search_term":"Abiy Ahmed Addis Ababa",
             "date_label":"2022","narration":"Who controls disputed land?"}
    raw={"source_kind":"camera","segments":[segment(start=80,end=90,
          observed="Stained glass window in the cathedral, Addis Ababa.",anchor_id="1:1")]}
    result=review.validate_segments(raw,info,[passage],[(60,120)])
    assert not result["segments"]
    assert "spoken passage" in result["rejected_segments"][0]["reason"]


def test_metadata_triage_cannot_invent_sources_or_scene_ids_and_reuses_its_cache(tmp_path):
    script={"title":"Ethiopia","scenes":[scene()]}
    metadata=[{"id":"camera","title":"Lalibela drone footage","query_scene_ids":["1"]},
              {"id":"music","title":"Lalibela Official Music Video","query_scene_ids":["1"]}]
    class Model:
        calls=0
        def text(self,*args,**kwargs):
            self.calls+=1
            return {"candidates":[
                {"source_id":"invented","scene_ids":["1"],"reason":"Invalid"},
                {"source_id":"music","scene_ids":["1"],"reason":"Do not accept music videos"},
                {"source_id":"camera","scene_ids":["999"],"reason":"Invalid scene"},
                {"source_id":"camera","scene_ids":["1"],"reason":"Likely real camera footage"}]}
    api=Model()
    sources,report=triage.shortlist(api,metadata,script,tmp_path,4)
    assert [item["id"] for item in sources]==["camera"]
    assert sources[0]["query_scene_ids"]==["1"]
    assert report["scope"]=="Likely camera sources only; not visual approval."
    assert triage.shortlist(api,metadata,script,tmp_path,4)[0]==sources
    assert api.calls==1


def test_failed_metadata_triage_keeps_local_camera_discovery_available(tmp_path):
    class Unavailable:
        def text(self,*args,**kwargs):raise PipelineError("Provider unavailable")
    metadata=[{"id":"camera","title":"Lalibela drone footage","query_scene_ids":["1"]}]
    selected,report=triage.shortlist(Unavailable(),metadata,{"title":"Ethiopia","scenes":[scene()]},tmp_path,2)
    assert selected[0]["id"]=="camera"
    assert report["mode"]=="local_camera_priority"
