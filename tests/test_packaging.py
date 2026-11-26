"""Exercise real thumbnail/description packaging; encoding tests alone do not cover it."""
from pathlib import Path
from PIL import Image
from history_of_countries.packaging import package

def test_complete_youtube_package_uses_real_image_and_keeps_metadata_in_bounds(tmp_path):
    picture=tmp_path/"portrait.jpg"
    Image.new("RGB",(400,700),"#765b3a").save(picture)
    output=tmp_path/"output";output.mkdir()
    work=tmp_path/"work";work.mkdir()
    script={"title":"The Entire History of Ethiopia","summary":"Choices and power across centuries.",
      "scenes":[{"scene_id":1,"chapter":"Hook","date_label":"1896","narration":"Menelik prepares his army."}]}
    speech={"scenes":[{"duration":12}]}
    assets={"assets":[{"id":"P","path":str(picture),"subject":"Menelik II portrait",
      "medium":"historical_photo","creator":"Historical archive","license":"Public domain",
      "source_url":"https://example.org/identified-public-domain-portrait"}]}
    package(None,script,speech,assets,output,work)
    for name in ("title.txt","description.txt","thumbnail.jpg","script.txt","sources-and-credits.txt","media-credits.json"):
        assert (output/name).is_file() and (output/name).stat().st_size>0
    with Image.open(output/"thumbnail.jpg") as image:assert image.size==(1280,720)
    assert (output/"thumbnail.jpg").stat().st_size<2_000_000
    assert len((output/"title.txt").read_text().strip())<=100
    assert len((output/"description.txt").read_text())<=5000
    assert "source_url" not in (output/"title.txt").read_text()


def test_oversized_model_metadata_is_bounded_before_thumbnail_and_upload_files():
    from history_of_countries.packaging import normalize_metadata
    script={"title":"A real history topic","summary":"The actual scope."}
    raw={"title":"A\n"*180,"thumbnail_subject":"One two three four five six",
      "thumbnail_hook":"A very long hook with far too many words","description":"x"*6000}
    result=normalize_metadata(raw,script)
    assert len(result["title"])<=100 and "\n" not in result["title"]
    assert len(result["thumbnail_subject"].split())<=4
    assert len(result["thumbnail_hook"].split())<=5
    assert len(result["description"])<=1200

def test_bad_optional_model_metadata_uses_the_actual_topic_instead_of_stopping_export():
    from history_of_countries.packaging import normalize_metadata
    script={"title":"The Entire History of Japan","summary":"The actual scope of Japan's history."}
    for raw in (None,[],{"title":None},{"title":"Unrelated response"}):
        result=normalize_metadata(raw,script)
        assert result["title"]==script["title"]
        assert result["thumbnail_subject"]=="Japan"
        assert result["description"]==script["summary"]

def test_many_licensed_images_keep_all_titles_authors_sources_and_licenses_within_upload_limit(tmp_path):
    import json
    picture=tmp_path/"fixture.jpg";Image.new("RGB",(400,700),"#765b3a").save(picture)
    output=tmp_path/"output";output.mkdir();work=tmp_path/"work";work.mkdir()
    script={"title":"The Entire History of Ethiopia","summary":"A short description.",
      "scenes":[{"scene_id":1,"chapter":"Hook","date_label":"1896","narration":"A source-credit regression fixture."}]}
    assets={"assets":[{"id":str(i),"path":str(picture),"subject":f"Historical image {i:02d}, source collection",
      "medium":"historical_photo","creator":"A credited archive photographer","license":"CC BY 2.0",
      "license_url":"https://creativecommons.org/licenses/by/2.0/",
      "source_url":f"https://commons.wikimedia.org/?curid={100000+i}"} for i in range(32)]}
    package(None,script,{"scenes":[{"duration":12}]},assets,output,work)
    description=(output/"description.txt").read_text()
    assert len(description)<=4900
    for asset in assets["assets"]:
        assert asset["subject"] in description and asset["source_url"] in description
        assert asset["creator"] in description and asset["license_url"] in description
    report=json.loads((output/"package-checks.json").read_text())
    assert report["passed"] and report["required_visual_attributions"]==32
    assert report["grouped_credits"] is True
