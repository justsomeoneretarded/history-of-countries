"""A real WAV transport fixture verifies bounded free-Gemini quota recovery."""
import base64,io,wave
import pytest
from history_of_countries.media_api import MediaAPI
from history_of_countries.gemini import QuotaDeferred

def wave_response():
    buffer=io.BytesIO()
    with wave.open(buffer,"wb") as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000)
        output.writeframes(b"\0\0"*4800)
    return {"steps":[{"type":"model_output","content":[{"type":"audio","data":base64.b64encode(buffer.getvalue()).decode()}]}]}

def test_exhausted_primary_preserves_voice_and_uses_only_the_verified_free_lite_model(tmp_path,monkeypatch):
    monkeypatch.setenv("GEMINI_TTS_MODEL","gemini-3.8-flash-tts")
    api=MediaAPI.__new__(MediaAPI);calls=[]
    def request(model,endpoint,body,kind):
        calls.append((model,body["generation_config"]["speech_config"][0]["voice"]))
        if model=="gemini-3.8-flash-tts":raise QuotaDeferred("Daily free quota")
        return wave_response()
    api.request=request
    result=api.speech("An original narration fixture.","Charon",tmp_path/"recording.wav")
    assert calls==[("gemini-3.8-flash-tts","Charon"),("gemini-3.8-flash-lite-tts","Charon")]
    assert result["model"]=="gemini-3.8-flash-lite-tts"
    assert (tmp_path/"recording.wav").exists()

def test_both_free_models_exhausted_stop_after_two_calls(tmp_path,monkeypatch):
    monkeypatch.setenv("GEMINI_TTS_MODEL","gemini-3.8-flash-tts")
    api=MediaAPI.__new__(MediaAPI);calls=[]
    def request(model,*args):
        calls.append(model);raise QuotaDeferred("Daily free quota")
    api.request=request
    with pytest.raises(QuotaDeferred):api.speech("An original fixture.","Charon",tmp_path/"recording.wav")
    assert calls==["gemini-3.8-flash-tts","gemini-3.8-flash-lite-tts"]
