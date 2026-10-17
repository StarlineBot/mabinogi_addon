"""Deterministic assets from visually inspected originals, never filename labels."""

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np

from mabinogi_addon import image_io
from mabinogi_addon.detect.dorcha_reader import prepare, _normalize

ROOT = Path(__file__).resolve().parents[1]
# The entire source images were inspected; x selects a particular digit.
GLYPHS = [(6,'4170',26),(3,'4078',26),(1,'4018',28),(2,'4049',26),
          (4,'4111',26),(9,'4230',26),(5,'4139',27),(8,'4207',26),
          (0,'3995',26),(8,'4208',26),(7,'4423',27),(7,'5174',28)]


def checked(path, blob):
    raw = path.read_bytes()
    assert hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest() == blob
    return path


def main():
    target = ROOT/'src/mabinogi_addon/detect/templates'
    source = checked(ROOT/'tests/data/투아림게이지 샘플 모음.zip', '843674a62afdb47ce1ce74dc298a1bd693700440')
    refs, labels, provenance = [], [], []
    with ZipFile(source) as z:
        for value, stamp, x in GLYPHS:
            name = f'새 폴더 (2)/v04_{stamp}.png'
            raw = z.read(name)
            a = cv2.imdecode(np.frombuffer(raw,np.uint8),1)
            ink = ((a.min(axis=2)>=180)&(np.ptp(a,axis=2)<=35)).astype(np.uint8)
            # Each crop ends before the next component; pad on the right to 6px.
            width = 0
            while x+width < 33 and ink[8:16,x+width].any():
                width += 1
            assert 2 <= width <= 6
            glyph = np.zeros((8,6),np.uint8)
            glyph[:,:width] = ink[8:16,x:x+width]
            refs.append(glyph); labels.append(value)
            provenance.append(dict(value=value,member=name,box=[x,8,width,8],sha256=hashlib.sha256(raw).hexdigest()))
        a = cv2.imdecode(np.frombuffer(z.read('새 폴더 (2)/v04_3995.png'),np.uint8),1)
        percent = ((a[8:16,33:41].min(axis=2)>=180)&(np.ptp(a[8:16,33:41],axis=2)<=35)).astype(np.uint8)
    np.savez_compressed(target/'tuarim/small_refs.npz',refs=np.stack(refs),labels=np.array(labels),percent=percent)
    (target/'tuarim/small_sources.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    source = checked(ROOT/'tests/data/autofind_20261016T192204168176Z_e70b6c5c.zip','2df5e973412440f1d6bf5cdead55d14006cc78dd')
    with ZipFile(source) as z:
        frame = cv2.imdecode(np.frombuffer(z.read('input.png'),np.uint8),1)
    image_io.imwrite(target/'autofind/dorcha_anchor_live.png',cv2.cvtColor(frame[105:162,526:571],cv2.COLOR_BGR2GRAY))
    image_io.imwrite(target/'autofind/tuarim_structure_live.png',frame[105:162,526:600])
    # Keep the original bank reproducible and add a second, inspected zero rendering.
    from scripts.build_dorcha_refs import main as original_refs
    original_refs()
    path = target/'dorcha/refs.npz'
    with np.load(path,allow_pickle=False) as data:
        refs,labels = data['refs'].copy(),data['labels'].copy()
    ink = prepare(frame[122:145,534:562])
    assert ink is not None
    np.savez_compressed(path,refs=np.vstack([refs,_normalize(ink)]),labels=np.append(labels,0))
    path = target/'dorcha/sources.json'
    provenance = json.loads(path.read_text(encoding='utf-8'))
    provenance.append(dict(value=0,file=str(source.relative_to(ROOT)),member='input.png',box=[534,122,28,23],sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    path.write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
