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
