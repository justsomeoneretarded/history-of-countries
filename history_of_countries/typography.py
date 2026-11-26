"""System DejaVu typography; no animation assets or proprietary fonts."""
from functools import lru_cache
from pathlib import Path
from PIL import ImageFont

@lru_cache(maxsize=96)
def font(size,bold=False):
    name="DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for location in (Path("/usr/share/fonts/truetype/dejavu")/name,Path(name)):
        try:return ImageFont.truetype(str(location),max(1,int(size)))
        except OSError:continue
    return ImageFont.load_default(size=max(1,int(size)))
