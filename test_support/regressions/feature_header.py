"""Read real first-show header geometry without changing fonts or layouts."""

from PySide6.QtGui import QFontInfo
from mabinogi_addon.ui.widgets import FeatureHeader


def initial_header_metrics(window):
    w, app = window
    observed = {}
    for key in ("dorcha", "custom"):
        w._open_setup_feature(key)
        app.processEvents()
        panel = w._combat_pages[key].widget()
        header = next(h for h in panel.findChildren(FeatureHeader) if h.isVisible())
        observed[key] = {}
        for name, widget in (("header", header), ("title", header.title),
                             ("description", header.description)):
            font = widget.font()
            actual = QFontInfo(font)
            observed[key][name] = {
                "font": font.toString(), "family": actual.family(),
                "pixels": actual.pixelSize(), "points": actual.pointSizeF(),
                "weight": actual.weight(), "height": widget.height(),
                "metrics_height": widget.fontMetrics().height(),
            }
    return observed

