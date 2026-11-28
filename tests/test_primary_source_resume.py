import hashlib
from history_of_countries import open_footage
from history_of_countries.core import key,save_json

def test_broader_archive_research_keeps_verified_clips_from_the_same_story(tmp_path,monkeypatch):
    movie=tmp_path/"accepted.mp4";movie.write_bytes(b"previously-inspected-camera")
    script={"title":"Ethiopia","scenes":[{"scene_id":1,"chapter":"Roots","narration":"At Aksum.",
        "asset_search_term":"Aksum monuments","location":"Aksum","date_label":"4th Century"}]}
    asset={"id":"camera","path":str(movie),"sha256":hashlib.sha256(movie.read_bytes()).hexdigest(),"duration_seconds":10}
    save_json(tmp_path/"discovery.json",{
        "fingerprint":key("direct-footage-v2-subject-searches",script,8),
        "assets":[asset],"scenes":{"1":["camera"]},"provider_status":[],
        "inspection_reports":[{"source_id":"old-source","source_kind":"camera","segments":[]} ]})
    monkeypatch.setattr(open_footage,"archive_candidates",lambda *args:[])
    monkeypatch.setattr(open_footage,"commons_candidates",lambda *args:[])
    report=open_footage.discover(object(),script,tmp_path)
    assert report["assets"]==[asset]
    assert report["scenes"]=={"1":["camera"]}
    assert report["summary"]["reused_clips"]==1
    # Acquired clips from a different script cannot survive into this one.
    other={**script,"title":"Japan"}
    assert open_footage.discover(object(),other,tmp_path)["assets"]==[]
