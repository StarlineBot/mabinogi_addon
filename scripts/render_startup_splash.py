"""Capture the actual Tcl layout on a desktop (diagnostic, not the startup entry)."""

import argparse
from pathlib import Path
import tempfile
import tkinter

from mss import MSS
from mss.tools import to_png
from PyInstaller.building.splash_templates import build_script

from mabinogi_addon.startup_content import MESSAGES
from scripts.startup_splash import ROOT, splash_type


def render(destination):
    destination.parent.mkdir(parents=True, exist_ok=True)

    class Base:
        def generate_script(self):
            return build_script(always_on_top=True)

    root = tkinter.Tk()
    if root.tk.call("info", "patchlevel").split(".")[:2] != ["8", "6"]:
        root.destroy()
        raise RuntimeError(
            "Use Tcl/Tk 8.6, matching the PyInstaller splash interpreter"
        )
    root.tk.setvar(
        "_image_data",
        (ROOT / "src/mabinogi_addon/assets/startup_background.png").read_bytes(),
    )
    with tempfile.TemporaryDirectory() as temporary:
        Base.script_name = Path(temporary) / "splash.tcl"
        root.tk.eval(splash_type(Base, messages=MESSAGES)().generate_script())
    root.tk.setvar("status_text", "@status:" + max(MESSAGES, key=len))
    errors = []

    def capture():
        try:
            with MSS() as screen:
                shot = screen.grab(
                    dict(
                        left=root.winfo_rootx(),
                        top=root.winfo_rooty(),
                        width=root.winfo_width(),
                        height=root.winfo_height(),
                    )
                )
                to_png(shot.rgb, shot.size, output=str(destination))
        except Exception as error:
            errors.append(error)
        finally:
            root.destroy()

    # Allow the compositor to paint once; only this screenshot helper waits.
    root.after(300, capture)
    root.mainloop()
    if errors:
        raise errors[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("startup-splash-preview.png")
    )
    render(parser.parse_args().output.resolve())
