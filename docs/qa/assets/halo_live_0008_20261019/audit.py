"""Audit capture/replay consistency, not OCR ground truth or real halo appearances."""

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

import cv2
import numpy as np
from mabinogi_addon.detect.halo_timer import read_seconds


def audit(path):
    rows = []
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        pngs = sorted(name for name in names if name.endswith('/frame.png'))
        assert len(pngs) == sum(name.endswith('/metadata.json') for name in names)
        for name in pngs:
            meta = json.loads(archive.read(str(PurePosixPath(name).with_name('metadata.json'))))
            frame = cv2.imdecode(np.frombuffer(archive.read(name), np.uint8), cv2.IMREAD_COLOR)
            assert frame is not None and list(frame.shape) == meta['shape']
            assert int(PurePosixPath(name).parent.name) == meta['sequence']
            rows.append(dict(sequence=meta['sequence'], raw=meta['raw_time'],
                             replay=read_seconds(frame), time=datetime.fromisoformat(meta['captured_at']),
                             status=meta['read_status']))
    assert rows
    assert [row['sequence'] for row in rows] == list(range(1, len(rows)+1))
    valid = [row for row in rows if type(row['raw']) is int]
    residual = [row['raw']+(row['time']-valid[0]['time']).total_seconds()-valid[0]['raw']
                for row in valid]
    return dict(pairs=len(rows), statuses=dict(Counter(row['status'] for row in rows)),
                raw_range=[min(row['raw'] for row in valid), max(row['raw'] for row in valid)] if valid else None,
                replay_matches=sum(row['raw'] == row['replay'] for row in rows),
                captured_span_seconds=(rows[-1]['time']-rows[0]['time']).total_seconds(),
                raw_vs_utc_residual_seconds=dict(min=min(residual), max=max(residual)) if residual else None,
                max_gap_seconds=max(((b['time']-a['time']).total_seconds()
                                     for a,b in zip(rows, rows[1:])), default=0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path,
                        default=Path(__file__).resolve().parents[4]/'tests/data/0008.zip')
    args = parser.parse_args()
    print(json.dumps(audit(args.archive), indent=2))
