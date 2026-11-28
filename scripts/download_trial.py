"""A small live transport check using the same private session as production."""
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import sys

from history_of_countries.core import PipelineError, read_json, save_json
from footage_trial import probe_downloads


def configure():
    event=read_json(os.environ["GITHUB_EVENT_PATH"])
    if os.getenv("GITHUB_EVENT_NAME")=="workflow_dispatch":
        request=event.get("inputs",{})
    else:
        changed=subprocess.check_output(["git","diff-tree","--no-commit-id","--name-only","-r","HEAD"],text=True).splitlines()
        paths=[p for p in changed if re.fullmatch(r"production/download-tests/[A-Za-z0-9_.-]+\.json",p)]
        if len(paths)!=1:raise PipelineError("Change exactly one download test request")
        request=read_json(paths[0])
    resume=str(request.get("resume_run",""))
    if not re.fullmatch(r"[0-9]+",resume):raise PipelineError("A numeric footage checkpoint run is required")
    with open(os.environ["GITHUB_ENV"],"a") as stream:
        stream.write("DOWNLOAD_RESUME_RUN="+resume+"\n")


def inspect_formats(work):
    """Compare actual source formats on both configured routes; never print URLs."""
    import yt_dlp
    from history_of_countries import youtube,download_access
    for ident in ("PJnJsHP2bzY","dc_SQ5n8EMg"):
        for route in download_access.routes():
            try:
                settings={**youtube._options(route),"ignore_no_formats_error":False}
                with yt_dlp.YoutubeDL(settings) as client:
                    item=client.extract_info("https://www.youtube.com/watch?v="+ident,download=False)
                formats=[fmt for fmt in item.get("formats",[]) if fmt.get("vcodec") not in (None,"none")]
                print("DOWNLOAD_FORMATS "+json.dumps({"source_id":ident,"route":route,"status":"available",
                      "license":item.get("license"),"duration":item.get("duration"),
                      "formats":[{k:fmt.get(k) for k in ("format_id","width","height","filesize","filesize_approx","ext","protocol")}
                                 for fmt in formats[-12:]]}),flush=True)
            except Exception as exc:
                print("DOWNLOAD_FORMATS "+json.dumps({"source_id":ident,"route":route,"status":"unavailable",
                      "reason":youtube.download_failure_reason(exc)}),flush=True)


def main():
    work=Path("work/footage")
    cookie=Path(os.environ["YOUTUBE_COOKIE_FILE"]) if os.getenv("YOUTUBE_COOKIE_FILE") else None
    print("DOWNLOAD_SESSION "+json.dumps({"cookies_configured":bool(cookie and cookie.is_file()),
          "fallback_configured":bool(os.getenv("YTDLP_FALLBACK_PROXY"))}),flush=True)
    # A restored checkpoint can contain an earlier probe clip; force fresh network transfers.
    shutil.rmtree(work/"download-probe",ignore_errors=True)
    inspect_formats(work)
    probe_downloads(work,{})
    results=read_json(work/"download-probe/results.json")["results"]
    passed=sum(row.get("status")=="downloaded" for row in results)
    print("DOWNLOAD_CHECK "+json.dumps({"downloaded":passed,"tested":len(results)}),flush=True)
    if not results or passed!=len(results):
        raise PipelineError("Some public clips remain unavailable; inspect DOWNLOAD_PROBE reasons")


if __name__=="__main__":
    configure() if "--configure" in sys.argv else main()
