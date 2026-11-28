import pytest
from history_of_countries import runner,sourcing
from history_of_countries.core import PipelineError,read_json,save_json

def test_impossible_footage_supply_stops_before_tts_and_keeps_an_actionable_report(tmp_path,monkeypatch):
    calls=[]
    def write(args):
        calls.append(args[args.index("--stage")+1])
        save_json(tmp_path/"work/script.json",{"title":"Ethiopia","scenes":[{"scene_id":1,"narration":"A story."}]})
        return 0
    monkeypatch.setattr(runner.director_script,"main",write)
    monkeypatch.setattr(runner.bootstrap,"ensure",lambda *args:None)
    monkeypatch.setattr(runner.media,"build",lambda *a,**kw:{"assets":[{"id":"still","medium":"photo"}]})
    with pytest.raises(PipelineError,match="TTS quota was not spent"):
        runner.run({"title":"Ethiopia","brief":"Choices and consequences."},tmp_path/"work",tmp_path/"output")
    assert calls==["plan"]
    report=read_json(tmp_path/"output/sourcing-preflight.json")
    assert report["possible"] is False and report["available_footage_seconds"]==0
    assert report["minimum_required_footage_seconds"]==pytest.approx(118.125)
    assert read_json(tmp_path/"output/delivery.json")["status"]=="needs_sourcing"

def test_preflight_is_an_optimistic_bound_and_never_counts_same_clip_twice():
    clip={"id":"camera","medium":"video","duration_seconds":60}
    catalog={"assets":[clip,clip,{"id":"other","medium":"video","duration_seconds":70}]}
    report=sourcing.preflight(catalog,8.75)
    assert report["available_footage_seconds"]==130
    assert report["possible"] is True
    assert "actual edited coverage" in report["scope"]
