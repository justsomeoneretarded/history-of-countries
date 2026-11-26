"""Read untrusted workflow inputs as data, never interpolate them into shell code."""
from pathlib import Path
import argparse,json,os,re,subprocess
from history_of_countries.runner import validate_request
from history_of_countries.core import save_json

def configure():
    event=json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if os.environ.get("GITHUB_EVENT_NAME")=="workflow_dispatch":
        raw=event.get("inputs",{})
        request={"title":raw.get("title","The Entire History of Ethiopia"),"brief":raw.get("brief",""),
          "voice":raw.get("voice","Charon"),"minutes":float(raw.get("minutes",8.75)),
          "youtube":str(raw.get("youtube","true")).lower()=="true",
          "youtube_urls":[x for x in re.split(r"[\s,]+",raw.get("youtube_urls","")) if x],
          "phase":raw.get("phase","full"),"resume_run":raw.get("resume_run",""),
          "resume_repository":raw.get("resume_repository") or os.environ["GITHUB_REPOSITORY"],
          "resume_artifact":raw.get("resume_artifact","countries-checkpoint")}
    else:
        paths=subprocess.check_output(["git","diff-tree","--no-commit-id","--name-only","-r","HEAD"],text=True).splitlines()
        paths=[p for p in paths if re.fullmatch(r"production/requests/[A-Za-z0-9_.-]+\.json",p)]
        if len(paths)!=1:raise SystemExit("Change exactly one production/requests JSON per production commit")
        request=json.loads(Path(paths[0]).read_text())
    request=validate_request(request)
    run=str(request.get("resume_run",""));repo=request.get("resume_repository") or os.environ["GITHUB_REPOSITORY"]
    artifact=request.get("resume_artifact","countries-checkpoint")
    if run and not re.fullmatch(r"[0-9]+",run):raise SystemExit("Numeric resume run ID required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repo):raise SystemExit("owner/repository resume source required")
    if artifact not in {"countries-checkpoint","directed-checkpoint","director-audio"}:raise SystemExit("Unsupported checkpoint artifact")
    save_json("work/input.json",request)
    with open(os.environ["GITHUB_ENV"],"a") as env:
        env.write("RESUME_RUN="+run+"\nRESUME_REPOSITORY="+repo+"\nRESUME_ARTIFACT="+artifact+"\n")
    print(json.dumps({k:request[k] for k in ("title","voice","minutes","phase","youtube")}))

def restore():
    import shutil
    source=Path("work/restore");destination=Path("work/countries")
    destination.mkdir(parents=True,exist_ok=True)
    for name in ("script.json","script.txt","research.json","request.json","style-profile.json",
      "writing-metrics.json","narration-metrics.json","directed-packaging.json","speech","director-chapters","voice-auditions"):
        path=source/name
        if path.is_dir():shutil.copytree(path,destination/name,dirs_exist_ok=True)
        elif path.is_file():shutil.copy2(path,destination/name)
    shutil.rmtree(source,ignore_errors=True)
    print("Restored writing/narration only; animation programs and renders were omitted.")

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("command",choices=("configure","restore"))
    args=parser.parse_args();configure() if args.command=="configure" else restore()
