"""Inspectable production evidence without dumping credentials or model internals."""
from pathlib import Path
import base64,io,json
from PIL import Image
work=Path("work/countries");output=Path("output/countries")
for root,names in ((work,["narration-metrics.json","progress.json","failure.json"]),(output,["quality.json","delivery.json","failure.json","media-discovery.json"])):
    for name in names:
        path=root/name
        if path.exists():
            print("COUNTRIES_REPORT "+json.dumps({"file":str(path),"data":json.loads(path.read_text())},ensure_ascii=False))
path=output/"storyboard.json"
if path.exists():
    data=json.loads(path.read_text())
    print("COUNTRIES_STORYBOARD "+json.dumps({k:data.get(k) for k in ("mode","model_error","repairs","scenes")},ensure_ascii=False))
path=work/"media/media.json"
if path.exists():
    data=json.loads(path.read_text())
    print("COUNTRIES_MEDIA "+json.dumps({"assets":[{k:a.get(k) for k in ("id","subject","provider","license")} for a in data["assets"]],
      "coverage":data["scenes"],"provider_status":data.get("provider_status",[])},ensure_ascii=False))
for name,tag in (("contact-sheet.jpg","COUNTRIES_IMAGE"),("thumbnail.jpg","COUNTRIES_THUMBNAIL")):
    path=output/name
    if path.exists():
        with Image.open(path) as im:
            im=im.convert("RGB");im.thumbnail((1440,1200));buffer=io.BytesIO();im.save(buffer,format="JPEG",quality=78)
        encoded=base64.b64encode(buffer.getvalue()).decode()
        print(tag+"_START")
        for i in range(0,len(encoded),8000):print(tag+"_CHUNK "+encoded[i:i+8000])
        print(tag+"_END")
