"""Real encoded export using synthetic transport fixtures, not a Gemini voice test."""
import json
import pytest
import numpy as np
import soundfile as sf
from PIL import Image
from history_of_countries import editing,director_sound
from history_of_countries.core import save_json,read_json,probe,duration
from history_of_countries.runner import render

@pytest.mark.parametrize("profile,seconds,phase,total",[
    ("test",2,"preview",10.0),("cinematic",6,"full",31.2)])
def test_complete_editor_exports_muxed_video_metadata_and_preview_status(tmp_path,monkeypatch,profile,seconds,phase,total):
    monkeypatch.setitem(editing.PROFILES,profile,(320,180,30))
    work=tmp_path/"work";(work/"speech").mkdir(parents=True);output=tmp_path/"output"
    rate=48000;t=np.arange(rate*seconds)/rate
    tone=(.08*np.sin(2*np.pi*180*t)).astype("float32")
    music=tmp_path/"music.wav";sf.write(music,.005*np.sin(2*np.pi*420*np.arange(rate*12)/rate),rate)
    catalogue=tmp_path/"music.json"
    save_json(catalogue,{"aurora":{"file":music.name,"title":"Synthetic encoding fixture","artist":"Test suite",
      "license":"CC0","license_url":"https://creativecommons.org/publicdomain/zero/1.0/","source":"https://example.org/test-fixture"}})
    monkeypatch.setattr(director_sound,"CATALOG",catalogue)
    picture=tmp_path/"image.jpg";Image.new("RGB",(640,400),"#967347").save(picture)
    chapters=["Hook","Roots","Catalyst","Turning Point","Aftermath"]
    script={"title":"Editor integration fixture","summary":"Synthetic transport check.","scenes":[]}
    speech={"voice":"Charon","scenes":[]}
    for index,chapter in enumerate(chapters,1):
        name=f"scene-{index}.wav";sf.write(work/"speech"/name,tone,rate)
        script["scenes"].append({"scene_id":index,"chapter":chapter,"narration":"Synthetic transport fixture.",
          "date_label":str(1900+index),"bg_music_mood":"resolute"})
        speech["scenes"].append({"scene_id":index,"duration":float(seconds),"audio":name,
          "words":[{"word":"Fixture","start":.1,"end":1.8}],
          "captions":[{"start":.1,"end":1.8,"text":"Encoding fixture"}],
          "verification":{"accepted":True,"coverage":1.0,"precision":1.0}})
    assets={"assets":[{"id":"A","path":str(picture),"subject":"Synthetic encoding fixture","medium":"documentary_photo",
      "license":"CC0","license_url":"https://creativecommons.org/publicdomain/zero/1.0/",
      "source_url":"https://example.org/test-fixture","creator":"Test suite"}],
      "scenes":{str(i):["A"] for i in range(1,6)},"provider_status":[]}
    video=render(script,speech,assets,work,output,profile,request={"phase":phase,"minutes":.5})
    assert duration(video)==pytest.approx(total,abs=.03)
    streams=probe(video)["streams"]
    assert {s["codec_type"] for s in streams}=={"video","audio"}
    assert next(s for s in streams if s["codec_type"]=="video")["nb_frames"]==str(round(total*30))
    assert read_json(output/"quality.json")["passed"] is True
    assert read_json(output/"delivery.json")["upload_ready"] is (phase=="full")
    for name in ("thumbnail.jpg","description.txt","title.txt","captions.srt","sources-and-credits.txt"):
        assert (output/name).stat().st_size>0
