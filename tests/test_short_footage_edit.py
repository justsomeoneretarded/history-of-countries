import pytest
from history_of_countries.planning import shots

def test_short_inspected_clip_is_edited_at_real_speed_without_losing_audio_time_or_restarting():
    script={"scenes":[{"scene_id":1,"chapter":"Roots","date_label":"12th Century","narration":"Churches carved in rock."}]}
    speech={"scenes":[{"scene_id":1,"duration":8.8,"words":[]}]}
    media={"assets":[{"id":"clip","medium":"video","duration_seconds":3.1},{"id":"still","medium":"photo"}],
           "scenes":{"1":["clip","still"]}}
    timeline=shots(script,speech,media,{"1":["clip","clip"]})
    assert timeline[0]["asset_id"]=="clip"
    assert timeline[0]["global_end"]==pytest.approx(3.1)
    assert sum(shot["frames"] for shot in timeline)==264
    assert timeline[-1]["global_end"]==pytest.approx(8.8)
    assert sum(shot["asset_id"]=="clip" for shot in timeline)==1
    assert all(a["global_end"]==b["global_start"] for a,b in zip(timeline,timeline[1:]))
    assert all(shot["source_crop"] is False and shot["motion"]=="hold" for shot in timeline)
