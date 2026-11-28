import json
import pytest
import requests

from history_of_countries.core import read_json,save_json
from history_of_countries.gemini import QuotaDeferred
from history_of_countries.media_api import MediaAPI

class Session:
    def __init__(self,status=200):self.status=status;self.calls=0
    def post(self,*args,**kwargs):
        self.calls+=1
        response=requests.Response();response.status_code=self.status
        payload={"error":{"message":"PerDay quota exhausted"}} if self.status==429 else {
            "candidates":[{"finishReason":"STOP","content":{"parts":[{"text":"{}"}]}}]}
        response._content=json.dumps(payload).encode()
        return response

def test_resume_preserves_history_and_pacing_without_inheriting_another_runs_local_cap(tmp_path,monkeypatch):
    ledger=tmp_path/"usage.json";now=[1000.]
    monkeypatch.setenv("GEMINI_MEDIA_LEDGER",str(ledger));monkeypatch.setenv("GITHUB_RUN_ID","new-run")
    monkeypatch.setenv("GEMINI_TEXT_REQUEST_BUDGET","1")
    old={"time":950.,"kind":"text","model":"gemini-3.5-flash-lite","run_id":"old-run"}
    save_json(ledger,{"calls":[old]*48,"last_start":950.})
    def sleep(seconds):now[0]+=seconds
    session=Session();api=MediaAPI(tmp_path/"api",session=session,clock=lambda:now[0],sleeper=sleep)
    api.request("gemini-3.5-flash-lite","models/test",{"request":1},"text")
    assert now[0]==1015.
    state=read_json(ledger)
    assert len(state["calls"])==49 and state["calls"][-1]["run_id"]=="new-run"
    # New objects in the same run share the cap, including separate stage gateways.
    api2=MediaAPI(tmp_path/"api",session=session,clock=lambda:now[0],sleeper=sleep)
    with pytest.raises(QuotaDeferred) as blocked:
        api2.request("gemini-3.5-flash-lite","models/test",{"request":2},"text")
    assert blocked.value.source=="local_budget"
    assert session.calls==1

def test_real_provider_daily_quota_still_stops_immediately_without_an_accepted_cache(tmp_path,monkeypatch):
    monkeypatch.setenv("GEMINI_MEDIA_LEDGER",str(tmp_path/"usage.json"));monkeypatch.setenv("GITHUB_RUN_ID","new-run")
    session=Session(429)
    api=MediaAPI(tmp_path/"api",session=session,clock=lambda:1000.,sleeper=lambda _:None)
    with pytest.raises(QuotaDeferred) as blocked:
        api.request("gemini-3.5-flash-lite","models/test",{},"text")
    assert blocked.value.source=="provider"
    assert session.calls==1
    assert list((tmp_path/"api").glob("*.json"))==[]
