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
    assert all(3<=s["frames"]/30<=4.5 for s in result)

def test_image_motion_uses_fractional_smooth_coordinates_and_no_random_shake():
    first=editing.pose(0,"in");middle=editing.pose(.5,"in");last=editing.pose(1,"in")
    assert first[0]<middle[0]<last[0]
    assert middle[0]==pytest.approx(1.0225)
    positions=[editing.pose(i/149,"left")[1] for i in range(150)]
    assert all(a>b for a,b in zip(positions,positions[1:]))
    assert len(set(positions))==150

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
    assert np.mean(np.abs(np.asarray(Image.open(start),dtype=float)-np.asarray(Image.open(end),dtype=float)))>.2


def test_youtube_search_uses_the_reuse_filter_but_still_requires_result_license():
    from urllib.parse import urlparse,parse_qs
    query=parse_qs(urlparse(youtube.search_url("Ethiopia 1935 footage")).query)
    assert query["search_query"]==["Ethiopia 1935 footage"]
    assert query["sp"]==["EgIwAQ=="]
    assert not youtube.reusable({"id":"tn2ehtuk1Gk","title":"creative commons footage"})


def test_repeated_photo_holds_one_continuous_camera_across_edit_boundaries():
    scene={"scene_id":1,"chapter":"Roots","narration":"The same subject continues.","date_label":"1900"}
    speech={"scenes":[{"scene_id":1,"duration":12.0}]}
    rows=planning.shots({"scenes":[scene]},speech,{"assets":[{"id":"A","medium":"historical_photo"}]},{"1":["A","A","A"]})
    assert len(rows)==3
    assert len({s["motion"] for s in rows})==1
    frames=sum(s["frames"] for s in rows)
    for previous,following in zip(rows,rows[1:]):
        before=(previous["motion_offset_frames"]+previous["frames"]-1)/(frames-1)
        after=following["motion_offset_frames"]/(frames-1)
        assert after-before==pytest.approx(1/(frames-1))


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
