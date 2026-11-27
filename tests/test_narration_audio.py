"""Real voice-stem transport test; a synthetic fixture makes no quality claim."""
import numpy as np
import soundfile as sf
from history_of_countries.narration_audio import master
from history_of_countries.core import duration

def test_chapter_mastering_preserves_time_and_finite_samples(tmp_path):
    rate=24000;t=np.arange(rate*2)/rate
    wave=(.12*np.sin(2*np.pi*170*t)*(0.7+.3*np.sin(2*np.pi*3*t))+.02*np.sin(2*np.pi*30*t)).astype("float32")
    source=tmp_path/"voice.wav";sf.write(source,wave,rate)
    output,report=master(source,tmp_path/"masters")
    result,actual_rate=sf.read(output)
    assert actual_rate==rate and np.isfinite(result).all()
    assert abs(duration(source)-duration(output))<.03
    assert report["time_stretch_applied"] is False
    assert master(source,tmp_path/"masters")[0]==output
