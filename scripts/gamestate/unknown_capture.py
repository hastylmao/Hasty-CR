"""Best-effort read-only evidence captures, outside the gameplay thread."""
import hashlib
import io
import json
from pathlib import Path
import queue
import subprocess
import threading
import time


def screen_point(x, y, mine_low):
    ox, oy = (x, 32000-y) if mine_low else (18000-x,y)
    return 103.5+51*(17.5-ox/1000), 171.9+41.4*(oy/1000-.5)


class UnknownCapture:
    def __init__(self, output, adb, serial):
        self.output = Path(output)
        self.adb, self.serial = str(adb), serial
        self.jobs = queue.Queue(maxsize=1)
        self.pending = set()
        self.done = {p.stem for p in self.output.glob('*.json')}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.retry_at = {}
        threading.Thread(target=self.run,daemon=True,name='unknown-capture').start()

    def observe(self, frame, side, state):
        accepted = {e[0] for e in state['entities']}
        towers = [u for u in frame.get('u',[]) if len(u)>10 and
                  u[3]==side and u[10] in {'KingTower','PrincessTower','Cannoneer','DaggerDuchess','ChefTower'}]
        if not towers:
            return
        mine_low = any(u[5]<16000 for u in towers)
        items=[]
        for u in frame.get('u',[]):
            if len(u)<10 or u[0] in accepted or u[8]<=0 or u[9]<=0:
                continue
            name=u[10] if len(u)>10 else ''
            if name in {'KingTower','PrincessTower','Cannoneer','DaggerDuchess','ChefTower'} or 'Projectile' in name or 'Container' in name:
                continue
            key=f'{u[6]}_'+hashlib.sha256(name.encode()).hexdigest()[:12]
            with self.lock:
                if key in self.done or key in self.pending or time.monotonic()<self.retry_at.get(key,0):
                    continue
            px=screen_point(u[4],u[5],mine_low)
            items.append((key,{'native_card':u[6],'unit':name,'address':u[0],
                               'side':u[3],'our_side':side,'tick':frame['t'],
                               'world_xy':u[4:6],'screen_xy_1080x1920':px,
                               'hp':u[8],'max_hp':u[9],'raw_unit':u,
                               'observed_unix':time.time(),'observed_monotonic':time.monotonic(),
                               'reason':'living character excluded from bridge'}))
        if items:
            with self.lock:
                try:
                    self.jobs.put_nowait(items)
                except queue.Full:
                    return
                self.pending.update(key for key,_ in items)

    def run(self):
        from PIL import Image
        while not self.stop.is_set():
            try:
                items=self.jobs.get(timeout=.25)
            except queue.Empty:
                continue
            try:
                # Avoid stale queued positions. Capture itself can still have latency.
                if time.monotonic()-items[0][1]['observed_monotonic']>1:
                    continue
                result=subprocess.run([self.adb,'-s',self.serial,'exec-out','screencap','-p'],
                                      capture_output=True,timeout=4,
                                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                result.check_returncode()
                im=Image.open(io.BytesIO(result.stdout)).convert('RGBA')
                self.output.mkdir(parents=True,exist_ok=True)
                for key,meta in items:
                    x,y=meta['screen_xy_1080x1920']; sx,sy=im.width/1080,im.height/1920
                    # Extra area above the ground coordinate includes tall/flying sprites.
                    box=(max(0,round((x-170)*sx)),max(0,round((y-260)*sy)),
                         min(im.width,round((x+170)*sx)),min(im.height,round((y+120)*sy)))
                    if box[2]<=box[0] or box[3]<=box[1]:
                        raise ValueError('unknown coordinate outside screenshot')
                    im.save(self.output/f'{key}_full.png')
                    im.crop(box).save(self.output/f'{key}_crop.png')
                    meta.update(crop_box=box,image_size=im.size,captured_unix=time.time(),
                                capture_delay_ms=round((time.monotonic()-meta.pop('observed_monotonic'))*1000),
                                full_image=f'{key}_full.png',crop_image=f'{key}_crop.png',
                                note='Asynchronous screenshot; troop may move between observation and capture. No visual identification performed.')
                    tmp=self.output/f'{key}.tmp'
                    tmp.write_text(json.dumps(meta,indent=2),encoding='utf-8')
                    tmp.replace(self.output/f'{key}.json')
                    with self.lock:
                        self.done.add(key)
                    print(f"Unknown troop evidence saved: {name_for(meta)} -> {self.output / (key+'_crop.png')}")
            except Exception as exc:
                print(f'Unknown troop capture failed: {exc}')
                with self.lock:
                    self.retry_at.update({key:time.monotonic()+10 for key,_ in items})
            finally:
                with self.lock:
                    self.pending.difference_update(key for key,_ in items)

    def close(self):
        self.stop.set()


def name_for(meta):
    return f"{meta['unit'] or '(unnamed)'} / {meta['native_card']}"
