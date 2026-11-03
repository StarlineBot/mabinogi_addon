"""0.40.2 '켜지자마자 종료'(0.40.0) 재발 방지 — 번들(exe) 배치에서 경로 문제를 잡는다.

0.40.0: harp_latency가 채널 파일을 `__file__` 기준으로 읽어, exe(_MEIPASS/assets)에서 못 찾고 모든 사용자에게 만들어지는 하프 탭
생성 중 예외 → 앱 종료. 소스 실행 스모크는 소스 폴더에 파일이 있어 못 잡았다.
1) 번들 배치 모의: packaging/build_windows.py의 --add-data 매핑대로 임시 _MEIPASS를 만들고(파이썬 코드만 복사 — 소스 폴더가 보이면
   잘못된 경로도 통과해 버린다) sys.frozen=True로 MainWindow를 오프스크린 생성 → 예외 없이 뜨고 하프 채널 목록도 읽힌다.
2) 금지 검사: src에서 `__file__` 기준으로 assets/를 읽는 코드가 없다(assets는 paths.resource_dir()만).
   detect/templates는 빌드가 같은 상대 위치(mabinogi_addon/detect/templates)로 넣으므로 예외.
"""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "mabinogi_addon"


def _add_data():
    """build_windows.py의 --add-data '원본;대상' 목록."""
    text = (ROOT / "packaging" / "build_windows.py").read_text(encoding="utf-8")
    options = shlex.split(text.split('OPTIONS = shlex.split("""', 1)[1].split('""")', 1)[0])
    pairs = [options[i + 1].split(";", 1) for i, o in enumerate(options) if o == "--add-data"]
    assert pairs, "--add-data 매핑을 찾지 못함(빌드 스크립트 형식이 바뀜)"
    return pairs


def _fake_meipass(tmp: Path) -> Path:
    meipass = tmp / "_MEIPASS"
    package = meipass / "mabinogi_addon"
    for py in SRC.rglob("*.py"):  # 코드(exe에서는 PYZ 안) — 데이터는 복사하지 않는다
        target = package / py.relative_to(SRC)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(py, target)
    for source, dest in _add_data():
        shutil.copytree(ROOT / source, meipass / dest, dirs_exist_ok=True)
    return meipass


SCRIPT = r'''
import os, sys
meipass = sys.argv[1]
sys.path.insert(0, meipass)
sys.frozen = True
sys._MEIPASS = meipass
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import mabinogi_addon
assert mabinogi_addon.__file__.startswith(meipass), mabinogi_addon.__file__  # 소스 폴더가 아니라 번들 배치에서 읽음
from PySide6.QtWidgets import QApplication
app = QApplication([])
app.quit = lambda: None  # 테스트 창 픽스처와 같게(시작 중 이벤트 처리에서 앱이 끝나지 않게)
from mabinogi_addon.ui.main_window import MainWindow
w = MainWindow()  # 모든 탭 생성(0.40.0은 여기서 하프 탭 예외로 종료)
print("HARP", len(w.harp_tab.channels), w.harp_tab.load_error, flush=True)
w._force_quit = True
w.harp_tab.shutdown()
print("OK", flush=True)
os._exit(0)  # 정리 단계(블랙박스 등 Windows 전용 자원)는 이 검사의 범위가 아니다
'''


def test_main_window_starts_from_bundle_layout(tmp_path):
    meipass = _fake_meipass(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "LOCALAPPDATA": str(home), "QT_QPA_PLATFORM": "offscreen",
           "PYTHONNOUSERSITE": "1"}
    import os
    for key in ("FONTCONFIG_FILE", "SYSTEMROOT", "TEMP", "TMP"):
        if key in os.environ:
            env[key] = os.environ[key]
    run = subprocess.run([sys.executable, "-c", SCRIPT, str(meipass)], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=180)
    assert run.returncode == 0 and "OK" in run.stdout, run.stdout[-2000:] + run.stderr[-4000:]
    assert "HARP 21 None" in run.stdout  # 하프 채널 목록을 번들 assets에서 읽음(못 읽어도 앱은 뜨지만 그건 실패로 본다)


def test_no_asset_reads_relative_to_module_file():
    offenders = []
    for py in SRC.rglob("*.py"):
        if py.name == "paths.py":
            continue  # resource_dir()가 소스 실행용 기준을 갖고 있다
        text = py.read_text(encoding="utf-8")
        names = set(re.findall(r"(\w+)\s*=\s*(?:Path\()?(?:os\.path\.dirname\()?__file__", text))
        for no, raw in enumerate(text.splitlines(), 1):
            line = raw.split("#", 1)[0]  # 주석 속 설명은 제외
            if "assets" not in line:
                continue
            if "__file__" in line or any(re.search(rf"\b{re.escape(n)}\b", line) for n in names):
                offenders.append(f"{py.relative_to(ROOT)}:{no}: {line.strip()}")
    assert not offenders, "assets는 paths.resource_dir()로만 읽는다(exe 번들 경로):\n" + "\n".join(offenders)
