"""Queued old worker results must not survive region removal or restart."""

from threading import Event, get_ident

from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui import buff_controller as module
from mabinogi_addon.ui.overlay import BuffOverlay


def test_queued_results_are_discarded_after_stop_and_ui_dispatch_is_preserved(monkeypatch):
    app = QApplication.instance() or QApplication([])
    ready = Event()
    delivered = []

    class EmittingWorker(module._TrackWorker):
        def run(self):
            self.updated.emit([])
            self.alerted.emit(["old"])
            self.alerted2.emit(["old"])
            self.foreground_changed.emit(True, False)
            ready.set()

    class Source:
        def close(self):
            pass

    monkeypatch.setattr(module, "_TrackWorker", EmittingWorker)
    overlay = BuffOverlay()
    controller = module.BuffController(overlay, {}, {})
    for name in ("_on_updated", "_on_alerted", "_on_alerted2", "_on_foreground_changed"):
        monkeypatch.setattr(controller, name, lambda *args: delivered.append(get_ident()))
    try:
        controller.start(Source(), None)
        old_worker = controller._worker
        assert ready.wait(3)
        controller.stop()
        app.processEvents()
        assert old_worker.isFinished()
        assert delivered == []
        ready.clear()
        controller.start(Source(), None)
        assert ready.wait(3)
        app.processEvents()
        assert delivered == [get_ident()] * 4
    finally:
        controller.stop()
        overlay.close()
        overlay.deleteLater()
