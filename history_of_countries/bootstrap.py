"""Download only pinned, checksum-verified reusable media; no animation assets."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import requests
from .core import ROOT,PipelineError,read_json

SOURCE="https://raw.githubusercontent.com/justsomeoneretarded/History-of-X/18eee915526063977b1a73cc7cd34eb43dfce060/"
MAX_BYTES=30*1024*1024

def _fetch(item):
    relative,expected=item
    path=ROOT/relative
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==expected:return
    if not expected or len(expected)!=64:raise PipelineError("Missing media checksum: "+relative)
    response=requests.get(SOURCE+relative,timeout=(10,30),stream=True)
    response.raise_for_status()
    data=bytearray()
    for chunk in response.iter_content(65536):
        data.extend(chunk)
        if len(data)>MAX_BYTES:raise PipelineError("Bundled media exceeds size limit")
    if hashlib.sha256(data).hexdigest()!=expected:raise PipelineError("Media checksum mismatch: "+relative)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+".part");temporary.write_bytes(data);temporary.replace(path)

def ensure(title):
    music=read_json(ROOT/"assets/music/catalog.json")
    items=[("assets/music/"+v["file"],v["sha256"]) for v in music.values()]
    if any(x in title.casefold() for x in ("ethiop","abyssinia")):
        items += [(r["bundled_path"],r["sha256"]) for r in read_json(ROOT/"assets/presets/ethiopia/manifest.json")]
        items += [(r["path"],r["sha256"]) for r in read_json(ROOT/"assets/footage/catalog.json")]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(_fetch,dict(items).items()):pass
