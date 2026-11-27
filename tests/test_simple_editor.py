"""Meaningful editor contracts; synthetic fixtures do not certify real TTS quality."""
from pathlib import Path
import json
import numpy as np
import pytest
from PIL import Image,ImageDraw
from history_of_countries.core import PipelineError,probe,duration,ffmpeg
from history_of_countries import editing,planning,media,youtube
from history_of_countries.runner import validate_request

def test_rights_must_be_explicit_and_downloads_cannot_bypass_them():
    assert not youtube.reusable({"id":"abc","license":"Standard YouTube License"})
    assert not youtube.reusable({"id":"abc"})
    assert youtube.reusable({"id":"abc","license":"Creative Commons Attribution license (reuse allowed)"})
    assert not youtube.reusable({"id":"abc","license":"Creative Commons Attribution license","has_drm":True})
    assert not youtube.reusable({"id":"abc","license":"Creative Commons Attribution license","is_live":True})
    with pytest.raises(PipelineError):youtube.video_id("https://example.com/watch?v=tn2ehtuk1Gk")
    assert youtube.video_id("https://www.youtube.com/watch?v=tn2ehtuk1Gk")=="tn2ehtuk1Gk"

def test_later_archive_cannot_become_adwa_battle_footage():
    archive={"title":"Ethiopian cavalry 1935","description":"Ethiopian troops","id":"a"}
    assert not youtube.related(archive,{"asset_search_term":"Ethiopian cavalry","date_label":"1896","narration":"Cavalry at Adwa."})
    assert youtube.related(archive,{"asset_search_term":"Ethiopian cavalry","date_label":"1935","narration":"The cavalry in 1935."})

def test_unknown_media_ids_and_missing_scenes_never_reach_the_editor():
    script={"scenes":[{"scene_id":1}]};catalogue={"scenes":{"1":["A"]}}
    with pytest.raises(PipelineError,match="unrelated"):
        planning.validate_order({"scenes":[{"scene_id":"1","asset_ids":["B"]}]},script,catalogue)
    with pytest.raises(PipelineError,match="omitted"):
        planning.validate_order({"scenes":[]},script,catalogue)

def test_frame_clock_covers_narration_without_cumulative_drift():
    scenes=[{"scene_id":i,"chapter":"Roots","narration":"A specific story.","date_label":"1900"} for i in range(1,25)]
    speech={"scenes":[{"scene_id":s["scene_id"],"duration":17.973} for s in scenes]}
    catalogue={"assets":[{"id":"A","medium":"historical_photo"}]}
    result=planning.shots({"scenes":scenes},speech,catalogue,{str(s["scene_id"]):["A"] for s in scenes})
    assert sum(s["frames"] for s in result)==round(24*17.973*30)
    assert result[0]["global_start"]==0
    assert all(a["global_end"]==b["global_start"] for a,b in zip(result,result[1:]))
    assert all(3<=s["frames"]/30<=6 for s in result)

def test_uncropped_fit_keeps_all_source_edges_at_every_aspect_ratio():
    for source in ((600,1200),(1200,600),(1920,1080),(800,800)):
        x,y,w,h=editing.fit_rect(source,(1920,1080))
        assert x>=0 and y>=0 and x+w<=1920 and y+h<=1080
        assert w/h==pytest.approx(source[0]/source[1],rel=.003)
        assert w==1920 or h==1080

def test_simple_request_defaults_and_untrusted_input_validation():
    request=validate_request({"title":"Japan","brief":"Explain political change across centuries."})
    assert request["voice"]=="Charon" and request["youtube"]
    with pytest.raises(PipelineError):validate_request({"minutes":True})
    with pytest.raises(PipelineError):validate_request({"youtube_urls":["file:///tmp/key"]})

def test_actual_image_and_video_clips_encode_and_join_without_black_gaps(tmp_path,monkeypatch):
    monkeypatch.setitem(editing.PROFILES,"test",(320,180,30))
    photo=tmp_path/"photo.png"
    image=Image.new("RGB",(640,400),"#95714f");draw=ImageDraw.Draw(image)
    for x in range(0,640,20):draw.rectangle((x,30,x+10,370),fill=(x%255,150,90))
    image.save(photo)
    movie=tmp_path/"source.mp4"
    ffmpeg("-f","lavfi","-i","testsrc2=size=320x180:rate=30","-t","3","-an","-c:v","libx264","-pix_fmt","yuv420p",movie)
    directory=tmp_path/"shots"
    still=editing.render_shot({"id":"P","path":str(photo),"medium":"documentary_photo"},
       {"frames":60,"motion":"left","year_label":"1896"} ,directory,"test")
    moving=editing.render_shot({"id":"V","path":str(movie),"medium":"video"},
       {"frames":60,"motion":"in","source_start":.25,"year_label":"1935"},directory,"test")
    final=tmp_path/"joined.mp4";editing.concat([still,moving],final)
    assert duration(final)==pytest.approx(4,abs=.04)
    stream=next(s for s in probe(final)["streams"] if s["codec_type"]=="video")
    assert int(stream["nb_frames"])==120 and stream["codec_name"]=="h264"
    start=tmp_path/"first.png";end=tmp_path/"later.png"
    ffmpeg("-i",still,"-vf","select=eq(n\\,0)","-frames:v","1",start)
    ffmpeg("-i",still,"-vf","select=eq(n\\,50)","-frames:v","1",end)
    assert np.mean(np.abs(np.asarray(Image.open(start),dtype=float)-np.asarray(Image.open(end),dtype=float)))<.35


def test_youtube_search_uses_the_reuse_filter_but_still_requires_result_license():
    from urllib.parse import urlparse,parse_qs
    query=parse_qs(urlparse(youtube.search_url("Ethiopia 1935 footage")).query)
    assert query["search_query"]==["Ethiopia 1935 footage"]
    assert query["sp"]==["EgIwAQ=="]
    assert not youtube.reusable({"id":"tn2ehtuk1Gk","title":"creative commons footage"})


def test_repeated_photo_is_held_whole_without_a_camera_reset():
    scene={"scene_id":1,"chapter":"Roots","narration":"The same subject continues.","date_label":"1900"}
    speech={"scenes":[{"scene_id":1,"duration":12.0}]}
    rows=planning.shots({"scenes":[scene]},speech,{"assets":[{"id":"A","medium":"historical_photo"}]},{"1":["A","A","A"]})
    assert len(rows)>=2
    assert all(s["motion"]=="hold" and not s["source_crop"] for s in rows)
    assert sum(s["frames"] for s in rows)==360

def test_restoration_word_never_moves_a_1941_photo_into_medieval_history():
    from history_of_countries.documentary_assets import matching_assets
    archive={"id":"1941","tags":["restoration"],"medium":"historical_photo","event_period":[1941,1941]}
    medieval={"date_label":"1270 AD","narration":"The restoration of the Solomonic dynasty."}
    liberation={"date_label":"1941","narration":"The restoration after occupation."}
    assert matching_assets(medieval,[archive])==[]
    assert matching_assets(liberation,[archive])==["1941"]

def test_one_invalid_gemini_cue_preserves_the_other_valid_choices():
    script={"scenes":[{"scene_id":1},{"scene_id":2}]}
    catalogue={"scenes":{"1":["A","B"],"2":["C"]}}
    raw={"scenes":[{"scene_id":"1","asset_ids":["B","wrong","B"]},
                   {"scene_id":"2","asset_ids":["C"]}]}
    result,repairs=planning.repair_order(raw,script,catalogue,{"1":["A","A","A"],"2":["C"]})
    assert result=={"1":["B","A","B"],"2":["C"]}
    assert repairs==[{"scene_id":"1","cue":1,"reason":"unapproved_asset_id"}]


def test_compact_transport_ids_round_trip_without_approving_unknown_ids():
    payload={"media":[{"id":"archive-long-sha","subject":"A named event"},{"id":"photo-long-sha","subject":"A ruler"}],
             "scenes":[{"scene_id":"1","allowed_asset_ids":["photo-long-sha"]}]}
    compact,aliases=planning.compact_ids(payload)
    assert compact["scenes"][0]["allowed_asset_ids"]==["A2"]
    assert compact["media"][0]["id"]=="A1"
    assert payload["media"][0]["id"]=="archive-long-sha"
    decoded=planning.restore_ids({"scenes":[{"scene_id":"1","asset_ids":["A2","A999"]}]},aliases)
    assert decoded["scenes"][0]["asset_ids"]==["photo-long-sha","A999"]


def test_important_portrait_edges_survive_real_frame_composition():
    source=Image.new("RGB",(100,200),"#997755");draw=ImageDraw.Draw(source)
    draw.rectangle((0,0,15,15),fill="red")
    draw.rectangle((84,0,99,15),fill="green")
    draw.rectangle((0,184,15,199),fill="blue")
    draw.rectangle((84,184,99,199),fill="yellow")
    result=editing.complete_image(source,(320,180),"plain")
    x,y,w,h=editing.fit_rect(source.size,result.size)
    for point,color in [((x+3,y+3),(255,0,0)),((x+w-4,y+3),(0,128,0)),
                        ((x+3,y+h-4),(0,0,255)),((x+w-4,y+h-4),(255,255,0))]:
        assert max(abs(a-b) for a,b in zip(result.getpixel(point),color))<15

def test_consecutive_footage_shots_continue_forward_instead_of_replaying_the_start():
    scene={"scene_id":1,"chapter":"Hook","narration":"The actual footage continues.","date_label":"1935"}
    speech={"scenes":[{"scene_id":1,"duration":12.0}]}
    catalogue={"assets":[{"id":"V","medium":"video","duration_seconds":16}],"scenes":{"1":["V"]}}
    rows=planning.shots({"scenes":[scene]},speech,catalogue,{"1":["V"]})
    assert rows[0]["source_start"]==0
    assert all(b["source_start"]==a["source_start"]+a["frames"]/30 for a,b in zip(rows,rows[1:]))
