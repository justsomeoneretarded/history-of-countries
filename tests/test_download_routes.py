"""Route reuse, private optional cookies and actual SOCKS-path local clipping."""
from pathlib import Path
import pytest
from history_of_countries import download_access,youtube
from history_of_countries.download_auth import prepare_cookies
from history_of_countries.core import PipelineError,ffmpeg,read_json,duration

@pytest.fixture(autouse=True)
def clean_routes():
    download_access.reset()
    yield
    download_access.reset()

def test_public_access_check_chooses_and_remembers_the_working_fallback(monkeypatch):
    monkeypatch.setenv("YTDLP_FALLBACK_PROXY","socks5h://127.0.0.1:40000")
    calls=[]
    class Public:
        def __init__(self,options):self.options=options
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def extract_info(self,*args,**kwargs):
            calls.append(self.options.get("proxy"))
            if not self.options.get("proxy"):
                self.options["logger"].warning("Sign in to confirm you're not a bot")
                return {"formats":[]}
            return {"formats":[{"url":"https://example.org/public-camera.mp4"}]}
    result=youtube.check_access(Public)
    assert result=={"status":"available","route":"fallback"}
    assert calls==[None,"socks5h://127.0.0.1:40000"]
    assert youtube._options()["proxy"]=="socks5h://127.0.0.1:40000"

def test_optional_cookies_are_private_and_invalid_exports_leave_no_file(tmp_path,capsys):
    assert prepare_cookies("",tmp_path) is None
    invalid="private-test-marker"
    with pytest.raises(PipelineError):prepare_cookies(invalid,tmp_path)
    assert not (tmp_path/"youtube-cookies.txt").exists()
    assert invalid not in capsys.readouterr().out
    contents="# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t2147483647\tSID\tfixture\n"
    path=prepare_cookies(contents,tmp_path)
    assert path.stat().st_mode&0o777==0o600
    assert capsys.readouterr().out==""

def test_cookie_options_apply_to_both_routes_without_mutating_callers(monkeypatch):
    monkeypatch.setenv("YOUTUBE_COOKIE_FILE","/tmp/fixture-cookies.txt")
    monkeypatch.setenv("YTDLP_FALLBACK_PROXY","socks5h://127.0.0.1:40000")
    base={"quiet":True}
    assert download_access.options(base,"direct")["cookiefile"]=="/tmp/fixture-cookies.txt"
    assert download_access.options(base,"fallback")["cookiefile"]=="/tmp/fixture-cookies.txt"
    assert base=={"quiet":True}

def test_socks_route_uses_native_download_and_real_local_cut(tmp_path,monkeypatch):
    import shutil
    monkeypatch.setenv("YTDLP_FALLBACK_PROXY","socks5h://127.0.0.1:40000")
    download_access.record_route_success("fallback")
    original=tmp_path/"original.mp4"
    ffmpeg("-f","lavfi","-i","testsrc2=size=640x360:rate=15","-t","20","-an","-c:v","libx264","-pix_fmt","yuv420p",original)
    calls=[]
    class Native:
        def __init__(self,options):self.options=options
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def download(self,urls):
            assert "download_ranges" not in self.options
            assert self.options["proxy"].startswith("socks5h://")
            calls.append(urls[0])
            target=Path(self.options["outtmpl"].replace("%(ext)s","mp4"))
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
    path=youtube.download_excerpt({"id":"abcdefghijk","duration":20},5,13,tmp_path/"clips/a.mp4",ydl_factory=Native)
    assert len(calls)==1
    assert duration(path)==pytest.approx(8,abs=.1)
    assert read_json(path.with_suffix(".acquisition.json"))["route"]=="fallback"
