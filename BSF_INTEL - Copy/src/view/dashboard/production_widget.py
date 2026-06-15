from PyQt6.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QFrame, QGridLayout
from .base import DashboardWidgetBase
from ...utils.icon_manager import IconManager
from ...utils.theme_manager import ThemeManager


class ProductionWidget(DashboardWidgetBase):
    def __init__(self, widget_id, title="Production Stats", parent=None):
        super().__init__(widget_id, title, parent)
        self.metric_cards = []
        self.init_production_ui()

    def init_production_ui(self):
        self.grid = QGridLayout()
        self.grid.setSpacing(10)

        cards = [
            ("PARTS", "0", "history"),
            ("CYCLE", "0.0s", "dashboard"),
            ("RATE", "0 / hr", "optimize"),
            ("UPTIME", "00:00", "info_panel"),
        ]

        for idx, (label, value, icon) in enumerate(cards):
            card = self._create_metric_card(label, value, icon)
            self.grid.addWidget(card, idx // 2, idx % 2)

        self.content_layout.addLayout(self.grid)

    def _create_metric_card(self, label, value, icon_name):
        frame = QFrame()
        frame.setObjectName(f"MetricCard_{label.lower()}")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        icon = QLabel()
        icon.setObjectName(f"MetricIcon_{label.lower()}")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(28, 28)

        lbl = QLabel(label)
        lbl.setObjectName("MetricLabel")
        header.addWidget(icon)
        header.addWidget(lbl)
        header.addStretch()

        val = QLabel(value)
        val.setObjectName("MetricValue")

        layout.addLayout(header)
        layout.addWidget(val)

        self.metric_cards.append((frame, icon, lbl, val, icon_name, label))
        return frame

    def on_span_changed(self, row_span, col_span):
        for i in reversed(range(self.grid.count())):
            item = self.grid.itemAt(i)
            card = item.widget()
            if card:
                self.grid.removeWidget(card)

        if col_span >= 8:
            for i, (card, _, _, _, _, _) in enumerate(self.metric_cards):
                self.grid.addWidget(card, 0, i)
        else:
            for i, (card, _, _, _, _, _) in enumerate(self.metric_cards):
                self.grid.addWidget(card, i // 2, i % 2)

    def update_metrics(self, count, cycle, rate, uptime):
        values = [str(count), f"{cycle:.1f}s", f"{rate} / hr", str(uptime)]
        for idx, text in enumerate(values):
            if idx < len(self.metric_cards):
                _, _, _, value_label, _, _ = self.metric_cards[idx]
                value_label.setText(text)

    def update_style(self):
        is_dark = ThemeManager.is_dark
        color_map = {
            "PARTS": "#60A5FA" if is_dark else "#1D4ED8",
            "CYCLE": "#34D399" if is_dark else "#065F46",
            "RATE": "#FBBF24" if is_dark else "#92400E",
            "UPTIME": "#C084FC" if is_dark else "#5B21B6",
        }
        for _, icon, _, _, icon_name, label in self.metric_cards:
            raw_pix = IconManager.get_pixmap(icon_name, 16, 16)
            tint_color = color_map.get(label, "#3B82F6")
            icon.setPixmap(IconManager._tint_pixmap(raw_pix, tint_color))
        ThemeManager.repolish(self)

    def apply_theme(self, is_dark):
        super().apply_theme(is_dark)
        self.update_style()
