import hashlib
import json
import pytest
from history_of_countries import footage_verify as verify,footage_review as review
from history_of_countries.core import ffmpeg
from history_of_countries.gemini import QuotaDeferred

def approved(ident,**extra):
    return {"asset_id":ident,"matches_observation":True,"real_camera_motion":True,
            "clean_frame":True,"natural_image":True,"confidence":.9,"reason":"Actual shot matches.",**extra}

def test_only_complete_unambiguous_actual_excerpt_approval_can_pass():
    assert verify.decision(approved("a"))[0]
    for row in (None,approved("a",confidence=float("nan")),approved("a",confidence=9),approved("a",natural_image=False),
                approved("a",matches_observation=False),approved("a",clean_frame=False),
                approved("a",real_camera_motion=False),approved("a",confidence=.7)):
        assert not verify.decision(row)[0]

def assets(tmp_path):
    path=tmp_path/"source.mp4"
    ffmpeg("-f","lavfi","-i","testsrc2=size=640x360:rate=15","-t","3","-an",
           "-c:v","libx264","-pix_fmt","yuv420p",path)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    return [{"id":ident,"path":str(path),"sha256":digest,"subject":"Expected subject "+ident,
             "width":640,"height":360,"inspection":{"narration_anchor":"The spoken anchor."}} for ident in ("good","bad")]

def test_actual_local_video_is_supplied_and_failed_or_unknown_ids_cannot_enter_catalog(tmp_path):
    records=assets(tmp_path)
    class Model:
        calls=0
        def request(self,model,endpoint,body,kind):
            self.calls+=1
            assert len([p for p in body["contents"][0]["parts"] if "inlineData" in p])==2
            assert not any("fileData" in p for p in body["contents"][0]["parts"])
            rows=[approved("good"),approved("bad",natural_image=False,reason="Heavy painted filter."),
                  approved("invented")]
            return {"candidates":[{"content":{"parts":[{"text":json.dumps({"clips":rows})}]}}]}
    api=Model()
    accepted,report=verify.verify(api,records,tmp_path/"review")
    assert [asset["id"] for asset in accepted]==["good"]
    assert [row["passed"] for row in report]==[True,False]
    assert not list((tmp_path/"review").glob("*.mp4"))
    assert verify.verify(api,records,tmp_path/"review")[0]==accepted
    assert api.calls==1

def test_provider_quota_failure_leaves_actual_excerpts_unapproved(tmp_path):
    class Exhausted:
        def request(self,*args):raise QuotaDeferred("Provider daily quota")
    accepted,report=verify.verify(Exhausted(),assets(tmp_path),tmp_path/"review")
    assert not accepted and len(report)==2
    assert all(not row["passed"] and "deferred" in row["reason"] for row in report)

def test_castle_inflection_and_verified_site_alias_work_but_an_unrelated_castle_does_not():
    scene={"scene_id":8,"location":"Gondar","asset_search_term":"Fasilides Gondar castles",
           "date_label":"1636","narration":"Its castles give royal power a permanent address."}
    info={"id":"abcdefghijk","title":"Fasil Ghebbi royal site","duration":200}
    row={"scene_id":"8","start":10,"end":15,"presentation":"surviving_object","anchor_id":"8:1",
         "observed":"Close-up of stone castle walls and towers of Fasil Ghebbi.",
         "confidence":.9,"real_moving_footage":True,"clean_frame":True,"camera_origin":"recorded_camera",
         "historical_period_supported":False,"period_evidence":"Modern camera view of surviving buildings."}
    assert review.validate_segments({"source_kind":"camera","segments":[row]},info,[scene],[(0,60)])["segments"]
    row["observed"]="Stone castle walls and towers of a castle in Germany."
    info["title"]="Bavarian castle walking tour"
    assert not review.validate_segments({"source_kind":"camera","segments":[row]},info,[scene],[(0,60)])["segments"]

def test_long_excerpts_are_split_into_at_most_sixty_seconds_per_actual_video_request(tmp_path):
    base=assets(tmp_path)[0]
    records=[{**base,"id":str(i),"subject":"Budget fixture "+str(i),"duration_seconds":30} for i in range(4)]
    class Model:
        calls=0
        def request(self,model,endpoint,body,kind):
            self.calls+=1
            parts=body["contents"][0]["parts"]
            assert len([part for part in parts if "inlineData" in part])==2
            payload=json.loads(parts[0]["text"].split("CLIP DATA:\n",1)[1])
            rows=[approved(row["asset_id"]) for row in payload]
            return {"candidates":[{"content":{"parts":[{"text":json.dumps({"clips":rows})}]}}]}
    api=Model()
    accepted,_=verify.verify(api,records,tmp_path/"budget-review")
    assert len(accepted)==4 and api.calls==2
