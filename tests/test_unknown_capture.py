import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import time

from PIL import Image

spec=importlib.util.spec_from_file_location('unknown_capture',
    Path(__file__).resolve().parents[1]/'scripts/gamestate/unknown_capture.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_screen_mapping_matches_live_tile_centres():
    # World point -> own-frame tile (4,10) -> screen tile (13,10).
    assert module.screen_point(4500,21500,True)==(766.5,585.9)
    assert module.screen_point(13500,10500,False)==(766.5,585.9)


def test_capture_metadata_crop_and_persistent_dedup(tmp_path,monkeypatch):
    image=Image.new('RGB',(1080,1920),'red')
    buf=io.BytesIO(); image.save(buf,format='PNG')
    calls=[]
    def capture(command,**kw):
        calls.append(command)
        return SimpleNamespace(stdout=buf.getvalue(),check_returncode=lambda:None)
    monkeypatch.setattr(module.subprocess,'run',capture)
    worker=module.UnknownCapture(tmp_path,'adb','127.0.0.1:16480')
    king=[1,0,0,1,9000,3000,0,11,5000,5000,'KingTower']
    unknown=[2,0,0,0,4500,21500,999,11,700,1000,'UnknownHero']
    known=[3,0,0,0,4500,21500,1,11,700,1000,'Known']
    frame={'t':100,'u':[king,unknown,known]}
    worker.observe(frame,1,{'entities':[[3]]})
    deadline=time.monotonic()+3
    while not list(tmp_path.glob('*.json')) and time.monotonic()<deadline:
        time.sleep(.01)
    meta=json.loads(next(tmp_path.glob('*.json')).read_text())
    worker.observe(frame,1,{'entities':[[3]]})
    worker.close()
    assert len(calls)==1
    assert meta['native_card']==999 and meta['unit']=='UnknownHero'
    assert meta['tick']==100
    assert Image.open(tmp_path/meta['crop_image']).size==(340,380)
    second=module.UnknownCapture(tmp_path,'adb','127.0.0.1:16480')
    second.observe(frame,1,{'entities':[[3]]})
    second.close()
    assert len(calls)==1
