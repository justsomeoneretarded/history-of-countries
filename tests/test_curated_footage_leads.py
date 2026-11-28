from dataclasses import replace
from history_of_countries import footage_search,youtube

def test_explicit_source_gets_real_video_inspection_even_if_metadata_screen_omits_it(tmp_path):
    ident="abcdefghijk"
    class Client:
        def __init__(self,settings):self.settings=settings
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def extract_info(self,url,download=False):
            if "results?" in url:return {"entries":[]}
            return {"id":ident,"title":"Gondar castles walking tour","duration":120,
                    "license":"Creative Commons Attribution license (reuse allowed)",
                    "formats":[{"url":"https://example.test/public-video"}]}
    class Model:
        def text(self,instruction,payload,schema,**kwargs):
            return {"scenes":[]} if "scenes" in schema.get("required",[]) else {"candidates":[]}
    inspected=[]
    def inspect(api,info,scenes,directory,download):
        inspected.append(info["id"])
        return {"source_id":info["id"],"source_kind":"camera","segments":[]}
    script={"title":"Ethiopia","scenes":[{"scene_id":1,"chapter":"Roots","location":"Gondar",
         "asset_search_term":"Gondar castles","date_label":"1636","narration":"Fasilides builds at Gondar."}]}
    limits=replace(footage_search.Limits(),max_queries=1,metadata_limit=2,review_limit=1,workers=1)
    result=youtube.discover(script,tmp_path,urls=["https://www.youtube.com/watch?v="+ident],
        ydl_factory=Client,api=Model(),limits=limits,reviewer=inspect)
    assert inspected==[ident]
    assert result["requested_urls"]==["https://www.youtube.com/watch?v="+ident]
    assert result["assets"]==[]  # Inspection is mandatory; a curated lead is not automatic approval.
