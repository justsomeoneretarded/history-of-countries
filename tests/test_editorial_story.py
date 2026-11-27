"""Narration quality, chronology and intake are checked before API work."""
import json
import pytest
from history_of_countries.core import ROOT,PipelineError
from history_of_countries.editorial_story import apply_edit,validate_edit

def draft():return json.loads((ROOT/"episodes/ethiopia-story.json").read_text())
def evidence():return json.loads((ROOT/"episodes/ethiopia.json").read_text())["evidence"]

def test_original_story_has_complete_causal_arc_and_bounded_chapters():
    story=draft()
    words=sum(len(s["narration"].split()) for s in story["scenes"])
    assert 1350<=words<=1540
    assert validate_edit(story,evidence(),words)==words
    assert "Baratieri" in story["scenes"][0]["narration"]
    assert "Adwa" in story["scenes"][-1]["narration"]
    assert "Sharing a country" in story["scenes"][-1]["narration"]

def test_editor_cannot_change_chronology_sources_or_invent_scene_ids():
    story=draft();raw={"scenes":[{"scene_id":s["scene_id"],"narration":s["narration"]} for s in story["scenes"]]}
    assert apply_edit(story,raw)==story
    raw["scenes"][-1]["scene_id"]=999
    with pytest.raises(PipelineError,match="scene IDs"):apply_edit(story,raw)
    assert story==draft()

def test_editor_cannot_drop_a_middle_scene_or_pad_with_summary_filler():
    story=draft()
    raw={"scenes":[{"scene_id":s["scene_id"],"narration":s["narration"]} for s in story["scenes"][:-1]]}
    with pytest.raises(PipelineError,match="omitted"):apply_edit(story,raw)
    story["scenes"][0]["narration"]+=" The plan fails."
    with pytest.raises(PipelineError,match="filler"):validate_edit(story,evidence(),1488)
