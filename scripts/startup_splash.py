"""Build-time extension of PyInstaller Splash. No application import or Qt required."""

from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parents[1]


def tcl_text(text):
    # Only hex enters Tcl source: braces, dollars and brackets stay literal data.
    return (
        "[encoding convertfrom utf-8 [binary decode hex "
        + text.encode("utf-8").hex()
        + "]]"
    )


def message_lists(messages):
    return (
        "[list "
        + " ".join(
            "[list "
            + " ".join(tcl_text(c) for c in unicodedata.normalize("NFC", text.strip()))
            + "]"
            for text in messages
            if isinstance(text, str) and text.strip()
        )
        + "]"
    )


def animation_script(messages, interval=60, hold=2000):
    if interval < 1 or hold < 1:
        raise ValueError("positive animation intervals required")
    return (
        f"set startup_messages {message_lists(messages)}\n"
        f"set startup_interval {int(interval)}\nset startup_hold {int(hold)}\n"
        + (ROOT / "packaging/startup_animation.tcl").read_text(encoding="utf-8")
    )


def splash_type(base, *, messages, probe=False):
    """Explicit spec-local subclass; never monkeypatch PyInstaller globally."""

    class StartupSplash(base):
        def generate_script(self):
            original = super().generate_script()
            for marker in (
                "proc _ipc_caller",
                "set status_text",
                ".root.canvas",
                "set server_socket",
                "raise .",
            ):
                # set status_text belongs to the IPC implementation even with no text_pos.
                if marker not in original:
                    raise RuntimeError("PyInstaller splash contract changed: " + marker)
            extension = (ROOT / "packaging/startup_layout.tcl").read_text(
                encoding="utf-8"
            )
            if probe:
                extension += "\n" + (ROOT / "packaging/startup_probe.tcl").read_text(
                    encoding="utf-8"
                )
            extension += "\n" + animation_script(messages)
            failure = "\n catch {startup::close}\n catch {startup_show {시작하는 중}}\n"
            if probe:
                failure += (
                    'catch {set fp [open "$env(MABINOGI_SPLASH_PROBE_REPORT).error.txt" w]; '
                    "puts $fp $::errorInfo; close $fp}\n"
                )
            extension = (
                "\nif {[catch {\n"
                + extension
                + "\n} startup_error]} {"
                + failure
                + "}\n"
            )
            # Configure the existing root before its first raise/map, avoiding a flash
            # at the upstream default geometry before DPI layout is ready.
            position = original.rfind("raise .")
            script = original[:position] + extension + original[position:]
            # PyInstaller 6.22.3 SplashWriter stores len(str) but writes UTF-8 bytes.
            # Non-ASCII source would be truncated by the bootloader. Keep the archive
            # source ASCII and decode the complete script inside Tcl instead.
            script = "eval " + tcl_text(script) + "\n"
            Path(self.script_name).write_text(script, encoding="utf-8")
            return script

    return StartupSplash
