import hashlib
from history_of_countries import youtube
from history_of_countries.core import key,read_json,save_json

def test_forced_research_retains_same_story_local_clips_when_the_new_runner_is_blocked(tmp_path,monkeypatch):
    import subprocess
    script={"title":"Ethiopia","scenes":[{"scene_id":1,"narration":"At Aksum."}]}
    movie=tmp_path/"clip.mp4";movie.write_bytes(b"previous-camera-excerpt")
    asset={"id":"camera","path":str(movie),"sha256":hashlib.sha256(movie.read_bytes()).hexdigest(),
           "source_url":"https://www.youtube.com/watch?v=abcdefghijk","duration_seconds":10,
           "inspection":{"camera_origin":"recorded_camera","clean_frame":True}}
    previous={"script_fingerprint":key(script),"assets":[asset],"scenes":{"1":["camera"]},
              "inspection_reports":[{"source_id":"abcdefghijk","source_kind":"camera"}]}
    save_json(tmp_path/"discovery.json",previous)
    class Blocked:
        def __init__(self,*args,**kwargs):
            save_json(tmp_path/"discovery.json",{"script_fingerprint":key(script),"assets":[],"scenes":{},
                "provider_status":[{"provider":"YouTube","status":"unavailable","reason":"authentication_required"}],
                "summary":{"attempted_queries":0}})
        def wait(self,**kwargs):return 0
    monkeypatch.setenv("YOUTUBE_FORCE_RESEARCH","true")
    monkeypatch.setattr(subprocess,"Popen",Blocked)
    report=youtube.bounded(script,tmp_path,timeout=1)
    assert report["assets"]==[asset] and report["scenes"]=={"1":["camera"]}
    assert report["summary"]["reused_clips"]==1
    assert read_json(tmp_path/"discovery.json")["assets"]==[asset]
    assert read_json(tmp_path/"request.json")["access_urls"]==[asset["source_url"]]
    other={**script,"title":"Japan"}
    empty={"script_fingerprint":key(other),"assets":[],"scenes":{}}
    assert youtube.merge_cached_discovery(empty,previous,other,tmp_path)["assets"]==[]

def test_one_restricted_source_does_not_hide_another_accessible_source(monkeypatch):
    monkeypatch.delenv("YTDLP_FALLBACK_PROXY",raising=False)
    youtube.download_access.reset()
    urls=["https://www.youtube.com/watch?v=11111111111","https://www.youtube.com/watch?v=22222222222"]
    seen=[]
    class Client:
        def __init__(self,settings):self.settings=settings
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def extract_info(self,url,download=False):
            seen.append(url)
            if url==urls[0]:
                self.settings["logger"].warning("Sign in to confirm you are not a bot")
                return {"formats":[]}
            return {"formats":[{"url":"https://example.test/public-format"}]}
    assert youtube.check_access(Client,urls)=={"status":"available","route":"direct"}
    assert seen==urls
