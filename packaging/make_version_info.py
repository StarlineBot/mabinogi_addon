"""릴리스 빌드용: 태그 버전을 version.py와 PyInstaller version_info.txt에 주입.

release.yml에서 `uv run python packaging/make_version_info.py "$VER"` 로 호출.
(YAML run 블록에 긴 heredoc을 넣으면 들여쓰기 때문에 워크플로 파싱이 깨져서 분리.)
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    ver = (sys.argv[1] if len(sys.argv) > 1 else "0.0.0").lstrip("v").strip() or "0.0.0"
    root = Path(__file__).resolve().parents[1]

    # 1) 소스 버전(앱 창 제목·설정 표시)
    (root / "src" / "mabinogi_addon" / "version.py").write_text(
        "from __future__ import annotations\n\n"
        f"__version__ = {ver!r}\n\n\n"
        "def display_version() -> str:\n"
        '    return "개발" if __version__ == "0.0.0" else f"v{__version__}"\n',
        encoding="utf-8",
    )

    # 2) exe 파일 속성(버전 리소스)용 version-file
    parts = [int(x) for x in ver.split(".") if x.isdigit()][:3]
    while len(parts) < 3:
        parts.append(0)
    v4 = tuple(parts) + (0,)
    info = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v4}, prodvers={v4}, mask=0x3f, flags=0x0,
    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041204b0', [
      StringStruct('CompanyName', 'HP Starline'),
      StringStruct('FileDescription', '섯다라인 마비노기 애드온'),
      StringStruct('FileVersion', {ver!r}),
      StringStruct('InternalName', 'mabinogi-addon'),
      StringStruct('OriginalFilename', 'mabinogi-addon.exe'),
      StringStruct('ProductName', '섯다라인 마비노기 애드온'),
      StringStruct('ProductVersion', {ver!r})])]),
    VarFileInfo([VarStruct('Translation', [0x0412, 1200])])
  ]
)
"""
    (root / "packaging" / "version_info.txt").write_text(info, encoding="utf-8")
    print("version:", ver, v4)


if __name__ == "__main__":
    main()
