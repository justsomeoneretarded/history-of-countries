from history_of_countries import footage_triage as triage

def test_large_camera_pool_is_screened_in_bounded_batches_and_reuses_completed_results(tmp_path):
    metadata=[{"id":str(i),"title":"Lalibela drone footage","query_scene_ids":["1"]} for i in range(235)]
    script={"title":"Ethiopia","scenes":[{"scene_id":1,"chapter":"Roots","narration":"Lalibela churches.",
             "location":"Lalibela","asset_search_term":"Lalibela churches","date_label":"12th Century"}]}
    class Model:
        calls=0
        def text(self,instruction,payload,schema,**kwargs):
            self.calls+=1
            assert len(payload["sources"])<=100
            return {"candidates":[{"source_id":payload["sources"][0]["id"],"scene_ids":["1"],"reason":"Likely camera footage"}]}
    api=Model()
    selected,report=triage.shortlist(api,metadata,script,tmp_path,10)
    assert len(selected)==3 and api.calls==3
    assert report["complete"] is True
    assert triage.shortlist(api,metadata,script,tmp_path,10)[0]==selected
    assert api.calls==3
