"""A small live transport check using the same private session as production."""
import json
import os
from pathlib import Path
import re
import subprocess
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


def main():
    work=Path("work/footage")
    cookie=Path(os.environ["YOUTUBE_COOKIE_FILE"]) if os.getenv("YOUTUBE_COOKIE_FILE") else None
    print("DOWNLOAD_SESSION "+json.dumps({"cookies_configured":bool(cookie and cookie.is_file()),
          "fallback_configured":bool(os.getenv("YTDLP_FALLBACK_PROXY"))}),flush=True)
    probe_downloads(work,{})
    results=read_json(work/"download-probe/results.json")["results"]
    passed=sum(row.get("status")=="downloaded" for row in results)
    print("DOWNLOAD_CHECK "+json.dumps({"downloaded":passed,"tested":len(results)}),flush=True)
    if not results or passed!=len(results):
        raise PipelineError("Some public clips remain unavailable; inspect DOWNLOAD_PROBE reasons")


if __name__=="__main__":
    configure() if "--configure" in sys.argv else main()
