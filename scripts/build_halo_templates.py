"""Generate fixed training references; never learn from held-out timer frames."""

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np

from mabinogi_addon.detect.halo_timer import cells

TRAIN = {'0001':'1441','0002':'1439','0003':'1438','0004':'1437',
         '0005':'1436','0006':'1435','0014':'1426','0048':'1330'}


def main():
    root=Path(__file__).resolve().parents[1]
    images,labels,slots=[],[],[]
    sources={}
    with ZipFile(root/'tests/data/0058.zip') as archive:
        for name,text in TRAIN.items():
            raw=archive.read(name+'/frame.png')
            frame=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
            candidates=cells(frame)
            if len(candidates)!=1:
                raise ValueError(f'{name}: ambiguous training geometry ({len(candidates)})')
            glyphs,_=candidates[0]
            for slot,(glyph,digit) in enumerate(zip(glyphs,text)):
                images.append(glyph)
                labels.append(int(digit))
                slots.append(slot)
            sources[name]=dict(text=text,sha256=hashlib.sha256(raw).hexdigest())
    folder=root/'src/mabinogi_addon/detect/templates/halo_timer'
    folder.mkdir(exist_ok=True)
    np.savez_compressed(folder/'refs.npz',images=np.array(images,dtype=np.uint8),
                        labels=np.array(labels,dtype=np.uint8),slots=np.array(slots,dtype=np.uint8))
    (folder/'sources.json').write_text(json.dumps(sources,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
