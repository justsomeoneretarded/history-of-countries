"""Remove only this job's temporary download session and userspace proxy."""
import os
import signal
import shutil
from pathlib import Path
root=Path(os.environ["RUNNER_TEMP"])
pid=root/"warp/proxy.pid"
if pid.exists():
    try:os.kill(int(pid.read_text().strip()),signal.SIGTERM)
    except (ValueError,ProcessLookupError):pass
(root/"youtube-cookies.txt").unlink(missing_ok=True)
shutil.rmtree(root/"warp",ignore_errors=True)
