"""A real copied research checkpoint must remain usable after its work root changes."""
import json
from pathlib import Path
from scripts import request
from history_of_countries.core import save_json,read_json

def test_research_media_paths_rebase_without_changing_source_attribution(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);monkeypatch.setenv("RESUME_ARTIFACT","footage-research")
    source=tmp_path/"work/restore"
    clip=source/"media/youtube/clips/camera.mp4";clip.parent.mkdir(parents=True);clip.write_bytes(b"fixture")
    url="https://www.youtube.com/watch?v=abcdefghijk"
    save_json(source/"media/footage-research.json",{"assets":[{"id":"camera","path":"/old/project/work/footage/media/youtube/clips/camera.mp4",
              "source_url":url,"sha256":"unchanged"}]})
    save_json(source/"script.json",{"title":"Ethiopia","scenes":[]})
    save_json(tmp_path/"work/input.json",{"fresh_pictures":True})
    request.restore()
    actual=read_json(tmp_path/"work/countries/media/footage-research.json")["assets"][0]
    assert actual["path"]==str((tmp_path/"work/countries/media/youtube/clips/camera.mp4").resolve())
    assert Path(actual["path"]).read_bytes()==b"fixture"
    assert actual["source_url"]==url and actual["sha256"]=="unchanged"
    assert not source.exists()
