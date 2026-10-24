"""상주 인코더의 fragmented MP4 출력을 구간 파일로 자른다(0.15.0, OS·FFmpeg 없이 테스트).

ffmpeg 하나가 녹화 동안 계속 `ftyp moov (moof mdat)* [mfra]`를 stdout으로 내보낸다. 박스 헤더(크기+형식)만 보고
조각(moof+mdat)이 다 모이면 `init(ftyp+moov) + moof + mdat`을 독립 MP4 한 개로 돌려준다.
조각의 tfdt(시작 시각)는 0으로 고쳐, 예전처럼 구간마다 ffmpeg을 따로 돌려 만든 파일과 같은 모양(0초 시작)이 되게 한다.
그래서 저장(concat inpoint/duration)·검증은 바꾸지 않는다. default_base_moof라 trun 데이터 위치는 moof 기준이어서 그대로 옮겨도 된다.
"""
from __future__ import annotations

import struct

MAX_BOX = 64 * 1024 * 1024  # 한 박스 상한(비정상 출력으로 메모리를 늘리지 않음)
_CONTAINERS = (b'traf',)


def _header(buffer, offset=0):
    """(박스 전체 크기, 형식, 헤더 길이). 헤더가 덜 왔으면 None."""
    if len(buffer) - offset < 8:
        return None
    size, kind = struct.unpack_from('>I4s', buffer, offset)
    header = 8
    if size == 1:
        if len(buffer) - offset < 16:
            return None
        size = struct.unpack_from('>Q', buffer, offset + 8)[0]
        header = 16
    elif size == 0:
        raise ValueError(f'MP4 박스 {kind!r} 크기 0(끝까지)은 스트림에서 쓸 수 없어요')
    if size < header:
        raise ValueError(f'MP4 박스 {kind!r} 크기 {size}가 헤더보다 작아요')
    return size, kind, header


def children(data, start, end):
    offset = start
    while offset < end:
        parsed = _header(data, offset)
        if parsed is None or offset + parsed[0] > end:
            raise ValueError('MP4 하위 박스가 잘렸어요')
        size, kind, header = parsed
        yield offset, size, kind, header
        offset += size


def rebase_fragment(moof: bytearray) -> int:
    """moof 안 tfdt를 0으로 고치고(제자리) trun 표본 수 합을 돌려준다."""
    samples, found = 0, False
    for offset, size, kind, header in children(moof, 8, len(moof)):
        if kind not in _CONTAINERS:
            continue
        for sub, sub_size, sub_kind, sub_header in children(moof, offset + header, offset + size):
            body = sub + sub_header
            if sub_kind == b'tfdt':
                version = moof[body]
                width = 8 if version == 1 else 4
                if sub_size < sub_header + 4 + width:
                    raise ValueError('tfdt가 잘렸어요')
                moof[body + 4:body + 4 + width] = bytes(width)
                found = True
            elif sub_kind == b'trun':
                if sub_size < sub_header + 8:
                    raise ValueError('trun이 잘렸어요')
                samples += struct.unpack_from('>I', moof, body + 4)[0]
    if not found or samples <= 0:
        raise ValueError('조각에 tfdt·trun이 없어요')
    return samples


class FragmentSplitter:
    """feed(바이트)로 들어온 출력에서 완성된 조각을 [(독립 MP4 bytes, 프레임 수)]로 돌려준다."""

    def __init__(self, max_box: int = MAX_BOX) -> None:
        self.max_box = max_box
        self._buffer = bytearray()
        self._init = []          # ftyp, moov
        self.init = None         # ftyp+moov (moov를 받은 뒤)
        self._moof = None
        self.fragments = 0

    @property
    def pending(self) -> int:
        """아직 완성되지 않은 바이트 수(끝났는데 남으면 출력이 잘린 것)."""
        return len(self._buffer) + (len(self._moof) if self._moof is not None else 0)

    def feed(self, data: bytes):
        self._buffer += data
        out = []
        while True:
            parsed = _header(self._buffer)
            if parsed is None:
                break
            size, kind, _header_len = parsed
            if size > self.max_box:
                raise ValueError(f'MP4 박스 {kind!r} 크기 {size}가 상한을 넘었어요')
            if len(self._buffer) < size:
                break
            box = bytes(self._buffer[:size])
            del self._buffer[:size]
            fragment = self._box(kind, box)
            if fragment is not None:
                out.append(fragment)
        return out

    def _box(self, kind, box):
        if self.init is None:
            if kind in (b'ftyp', b'moov'):
                self._init.append(box)
                if kind == b'moov':
                    self.init = b''.join(self._init)
                return None
            if kind == b'moof':
                raise ValueError('moov 전에 조각이 왔어요')
            return None  # free 등은 무시
        if kind == b'moof':
            if self._moof is not None:
                raise ValueError('mdat 없이 조각이 이어졌어요')
            moof = bytearray(box)
            self._samples = rebase_fragment(moof)
            self._moof = bytes(moof)
            return None
        if kind == b'mdat':
            if self._moof is None:
                raise ValueError('moof 없는 mdat')
            data, self._moof = self.init + self._moof + box, None
            self.fragments += 1
            return data, self._samples
        return None  # mfra(끝 색인)·free 등
