from types import SimpleNamespace
from history_of_countries.speech import transcript
from history_of_countries.gemini_speech import name_vocabulary

def test_recognizer_gets_only_name_vocabulary_instead_of_the_expected_story():
    seen={}
    class Recognizer:
        def transcribe(self,path,**kwargs):
            seen.update(kwargs)
            word=SimpleNamespace(word="Tewodros",start=0,end=.5)
            segment=SimpleNamespace(start=0,end=.5,text="Tewodros",words=[word])
            return [segment],None
    cues,words=transcript("actual.wav",Recognizer(),"Tewodros, Yohannes")
    assert seen["initial_prompt"]=="Names and places: Tewodros, Yohannes"
    assert "tried to do that" not in seen["initial_prompt"]
    assert cues[0]["text"]=="Tewodros" and words[0]["start"]==0

def test_source_search_metadata_supplies_vocabulary_without_narrative_sentences():
    scene={"asset_search_term":"Tewodros II Yohannes IV Ethiopia portrait",
           "location":"Ethiopian Highlands","narration":"A whole sentence that must not become the recognizer prompt."}
    result=name_vocabulary([scene])
    assert "Tewodros" in result and "Yohannes" in result
    assert "whole sentence" not in result
