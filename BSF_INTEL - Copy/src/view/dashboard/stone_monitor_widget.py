from PyQt6.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QFrame
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from .base import DashboardWidgetBase
from ...utils.theme_manager import ThemeManager


class StoneConditionWidget(DashboardWidgetBase):
    def __init__(self, widget_id, title="Stone Health", parent=None):
        super().__init__(widget_id, title, parent)
        self.wear_pct = 0.0
        self.init_stone_ui()

    def init_stone_ui(self):
        self.circular_frame = QFrame()
        self.circular_frame.setMinimumSize(100, 100)
        self.circular_frame.paintEvent = self._draw_circular_progress

        # Wrap in a themed panel to match other KPI cards
        self.right_panel = QFrame()
        self.right_panel.setObjectName("ValuePanel")

        i_layout = QVBoxLayout(self.right_panel)
        i_layout.setContentsMargins(12, 12, 12, 12)
        i_layout.setSpacing(8)

        life_layout = QVBoxLayout()
        self.lbl_life_header = QLabel("REMAINING LIFE")
        self.lbl_life_header.setObjectName("MetricLabel")

        self.lbl_life_val = QLabel("1,240 Cycles")
        self.lbl_life_val.setObjectName("MetricValue")
        self.lbl_life_val.setStyleSheet("font-size: 24px; font-weight: 800;")

        life_layout.addWidget(self.lbl_life_header)
        life_layout.addWidget(self.lbl_life_val)

        self.lbl_status = QLabel("OPTIMAL")
        self.lbl_status.setProperty("status", "optimal")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setFixedHeight(24)

        i_layout.addLayout(life_layout)
        i_layout.addWidget(self.lbl_status)

        main = QHBoxLayout()
        main.setSpacing(12)
        main.addWidget(self.circular_frame, 1)
        main.addWidget(self.right_panel, 1)

        self.content_layout.addLayout(main)

    def on_span_changed(self, row_span, col_span):
        pass

    def _draw_circular_progress(self, event):
        painter = QPainter(self.circular_frame)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.circular_frame.width(), self.circular_frame.height()
        size = min(w, h) - 20
        rect = QRect((w - size) // 2, (h - size) // 2, size, size)

        bg_arc = QColor(ThemeManager.color("border_strong"))
        accent = QColor(ThemeManager.color("accent"))
        text_primary = QColor(ThemeManager.color("text_primary"))
        text_secondary = QColor(ThemeManager.color("text_muted"))

        pen = QPen(bg_arc, 8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)

        span = int(self.wear_pct * 360 * 16 / 100)
        pen = QPen(accent, 8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, -span)

        painter.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        painter.setPen(text_primary)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self.wear_pct:.0f}%")

        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(text_secondary)
        label_rect = QRect(rect.x(), rect.y() + size // 2 + 5, size, 20)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter, "WEAR")
        painter.end()

    def update_stone_data(self, wear_pct, rem_cycles):
        self.wear_pct = wear_pct
        self.circular_frame.update()
        self.lbl_life_val.setText(f"{rem_cycles:,} Cycles")

        if wear_pct < 60:
            status = "OPTIMAL"
            status_key = "optimal"
        elif wear_pct < 85:
            status = "WARNING"
            status_key = "warning"
        else:
            status = "CRITICAL"
            status_key = "error"

        self.lbl_status.setText(status)
        self.lbl_status.setProperty("status", status_key)
        ThemeManager.repolish(self.lbl_status)

    def update_style(self):
        self.circular_frame.update()

    def apply_theme(self, is_dark):
        super().apply_theme(is_dark)
        self.update_style()
        if hasattr(self, 'right_panel'):
            ThemeManager.repolish(self.right_panel)
