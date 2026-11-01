"""게임 그림대화 PNG 규격(그림대화 명세 1·2절).

- 256×96, 팔레트 방식 2비트(4색).
- 청크 순서: IHDR, PLTE(4색), zTXt authid, zTXt author, IDAT, IEND — 게임 파일과 같게.
- 서명(authid·author zTXt)은 내가 마지막에 그린 recentchatimage.png에서 **바이트 그대로** 옮긴다.
  앱은 서명을 만들거나 고치지 않는다(사칭 방지).

OpenCV는 2비트 팔레트 PNG를 쓰지 못하므로 청크를 직접 만든다. 픽셀 묶기는 numpy로 한다.
"""

from __future__ import annotations

import re
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

WIDTH = 256
HEIGHT = 96
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
RECENT_NAME = "recentchatimage.png"


@dataclass(frozen=True)
class Signature:
    """recentchatimage.png의 서명 청크 두 개(길이·종류·내용·CRC 전체 바이트)와 읽은 이름."""

    authid_chunk: bytes
    author_chunk: bytes
    author: str


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def iter_chunks(data: bytes):
    """(종류, 내용, 청크 전체 바이트)를 차례로. PNG가 아니거나 잘린 파일이면 ValueError."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("PNG가 아니에요")
    pos = len(PNG_SIGNATURE)
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError("잘린 PNG")
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        end = pos + 12 + length
        if end > len(data):
            raise ValueError("잘린 PNG")
        kind = data[pos + 4:pos + 8]
        yield kind, data[pos + 8:pos + 8 + length], data[pos:end]
        pos = end
        if kind == b"IEND":
            return


def _ztxt(body: bytes) -> tuple[bytes, bytes] | None:
    key, sep, rest = body.partition(b"\0")
    if not sep or not rest or rest[0] != 0:
        return None
    try:
        return key, zlib.decompress(rest[1:])
    except zlib.error:
        return None


def read_signature(data: bytes) -> Signature | None:
    """서명 청크(authid 숫자 + author 이름)를 바이트 그대로 꺼낸다. 하나라도 없거나 이상하면 None."""
    found: dict[bytes, tuple[bytes, bytes]] = {}
    try:
        for kind, body, raw in iter_chunks(data):
            if kind != b"zTXt":
                continue
            parsed = _ztxt(body)
            if parsed and parsed[0] in (b"authid", b"author") and parsed[0] not in found:
                found[parsed[0]] = (raw, parsed[1])
    except ValueError:
        return None
    if b"authid" not in found or b"author" not in found:
        return None
    authid = found[b"authid"][1]
    if not re.fullmatch(rb"-?[0-9]+", authid) or authid.lstrip(b"-") in (b"", b"0"):
        return None  # 가짜 번호(0)는 게임 목록에 안 보였다
    try:
        author = found[b"author"][1].decode("cp949")
    except UnicodeDecodeError:
        return None
    if not author.strip():
        return None
    return Signature(found[b"authid"][0], found[b"author"][0], author)


def read_signature_file(path: Path) -> Signature | None:
    """recentchatimage.png 파일에서 서명 읽기. 받은 그림(chat_…png)은 받지 않는다(사칭 방지)."""
    path = Path(path)
    if path.name.lower() != RECENT_NAME:
        return None
    try:
        return read_signature(path.read_bytes())
    except OSError:
        return None


def pack_2bit(indices: np.ndarray) -> bytes:
    """(96,256) 0~3 배열 → 줄마다 필터 0 + 한 바이트에 4픽셀(왼쪽이 높은 비트)."""
    a = np.asarray(indices, dtype=np.uint8) & 3
    h, w = a.shape
    pad = (-w) % 4
    if pad:
        a = np.pad(a, ((0, 0), (0, pad)))
    q = a.reshape(h, -1, 4)
    packed = (q[:, :, 0] << 6) | (q[:, :, 1] << 4) | (q[:, :, 2] << 2) | q[:, :, 3]
    rows = np.concatenate([np.zeros((h, 1), np.uint8), packed.astype(np.uint8)], axis=1)
    return rows.tobytes()


def encode_png(indices: np.ndarray, palette: list[tuple[int, int, int]], signature: Signature) -> bytes:
    """게임과 같은 청크 순서의 2비트 팔레트 PNG."""
    a = np.asarray(indices)
    if a.shape != (HEIGHT, WIDTH):
        raise ValueError(f"크기는 {WIDTH}×{HEIGHT}이어야 해요")
    if len(palette) != 4:
        raise ValueError("색은 4개여야 해요")
    ihdr = struct.pack(">IIBBBBB", WIDTH, HEIGHT, 2, 3, 0, 0, 0)
    plte = b"".join(bytes((r & 255, g & 255, b & 255)) for r, g, b in palette)
    return (PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"PLTE", plte)
            + signature.authid_chunk + signature.author_chunk
            + _chunk(b"IDAT", zlib.compress(pack_2bit(a), 9)) + _chunk(b"IEND", b""))


def decode_indices(data: bytes) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """우리가 쓴 2비트 팔레트 PNG(줄 필터 0)를 (색 칸 배열, 팔레트)로 — 저장 결과 확인·테스트용.

    다른 필터를 쓴 파일(게임 파일 등)은 ValueError — 그런 그림은 Qt로 이미지로 불러온다.
    """
    ihdr = plte = None
    idat = b""
    for kind, body, _ in iter_chunks(data):
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            plte = body
        elif kind == b"IDAT":
            idat += body
    if ihdr is None or plte is None or ihdr[2] != 2 or ihdr[3] != 3 or ihdr[6] != 0:
        raise ValueError("2비트 팔레트 PNG가 아니에요")
    w, h = ihdr[0], ihdr[1]
    stride = (w * 2 + 7) // 8
    raw = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(h, stride + 1)
    if raw[:, 0].any():
        raise ValueError("줄 필터 0만 읽어요")
    rows = raw[:, 1:]
    bits = np.stack([(rows >> s) & 3 for s in (6, 4, 2, 0)], axis=2).reshape(h, -1)[:, :w]
    pal = [tuple(plte[i:i + 3]) for i in range(0, len(plte) - 2, 3)]
    return bits.astype(np.uint8), pal


_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def chat_filename(author: str, when: datetime, exists=lambda name: False) -> str:
    """`chat_YYYYMMDD_HHMMSS_서명이름.png`. 이름이 겹치면 초 단위를 올려 피한다(명세 1절)."""
    from datetime import timedelta

    safe = _UNSAFE.sub("_", author).strip() or "_"
    t = when.replace(microsecond=0)
    for _ in range(3600):
        name = f"chat_{t:%Y%m%d_%H%M%S}_{safe}.png"
        if not exists(name):
            return name
        t += timedelta(seconds=1)
    raise FileExistsError("같은 시각 이름이 너무 많아요")
