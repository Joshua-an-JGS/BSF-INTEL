from PyQt6.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QFrame, QGridLayout
from .base import DashboardWidgetBase
from ...utils.icon_manager import IconManager
from ...utils.theme_manager import ThemeManager


class MachineHealthWidget(DashboardWidgetBase):
    def __init__(self, widget_id, title="Machine Health", parent=None):
        super().__init__(widget_id, title, parent)
        self.health_rows = []
        self.init_health_ui()

    def init_health_ui(self):
        self.grid = QGridLayout()
        self.grid.setSpacing(10)

        row_vib = self._create_health_row("VIBRATION", "NORMAL", "machine_tool")
        row_temp = self._create_health_row("TEMPERATURE", "38.5 C", "general_info")
        row_spindle = self._create_health_row("SPINDLE", "NORMAL", "dashboard")

        self.grid.addWidget(row_vib, 0, 0)
        self.grid.addWidget(row_temp, 1, 0)
        self.grid.addWidget(row_spindle, 2, 0)

        self.content_layout.addLayout(self.grid)

    def _create_health_row(self, label, value, icon_name):
        frame = QFrame()
        frame.setObjectName("HealthRow")
        frame.setProperty("status", "optimal")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        icon = QLabel()
        icon.setObjectName(f"HealthIcon_{label.lower()}")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(28, 28)

        v_box = QVBoxLayout()
        v_box.setSpacing(2)
        lbl = QLabel(label)
        lbl.setObjectName("MetricLabel")
        val = QLabel(value)
        val.setObjectName("HealthValue")
        v_box.addWidget(lbl)
        v_box.addWidget(val)

        layout.addWidget(icon)
        layout.addLayout(v_box)
        layout.addStretch()

        self.health_rows.append((frame, icon, lbl, val, icon_name, label))
        return frame

    def on_span_changed(self, row_span, col_span):
        for i in reversed(range(self.grid.count())):
            item = self.grid.itemAt(i)
            widget = item.widget()
            if widget:
                self.grid.removeWidget(widget)

        if col_span >= 8:
            for i, (w, _, _, _, _, _) in enumerate(self.health_rows):
                self.grid.addWidget(w, 0, i)
        else:
            for i, (w, _, _, _, _, _) in enumerate(self.health_rows):
                self.grid.addWidget(w, i, 0)

    def update_health(self, vibration, temp, load):
        values = [vibration, temp, load]
        for idx, val_text in enumerate(values):
            if idx < len(self.health_rows):
                frame, _, _, val, _, label = self.health_rows[idx]
                val.setText(str(val_text))

                status = "optimal"
                val_str = str(val_text).upper()
                try:
                    if label == "VIBRATION":
                        if val_str != "NORMAL":
                            status = "error"
                    elif label == "TEMPERATURE":
                        num_str = "".join([c for c in val_str if c.isdigit() or c == "."])
                        if num_str:
                            t_val = float(num_str)
                            if t_val > 55.0:
                                status = "error"
                            elif t_val > 45.0:
                                status = "warning"
                    elif label == "SPINDLE":
                        num_str = "".join([c for c in val_str if c.isdigit() or c == "."])
                        if num_str:
                            l_val = float(num_str)
                            if l_val > 85.0:
                                status = "error"
                            elif l_val > 70.0:
                                status = "warning"
                except Exception:
                    pass

                frame.setProperty("status", status)
                ThemeManager.repolish(frame)
                self._tint_health_icon(frame, idx)

    def _tint_health_icon(self, frame, idx):
        if idx >= len(self.health_rows):
            return
        _, icon, _, _, icon_name, label = self.health_rows[idx]
        status = frame.property("status") or "optimal"
        is_dark = ThemeManager.is_dark

        if status == "error":
            color = "#EF4444" if is_dark else "#DC2626"
        elif status == "warning":
            color = "#F59E0B" if is_dark else "#D97706"
        else:
            color = "#22C55E" if is_dark else "#16A34A"

        raw_pix = IconManager.get_pixmap(icon_name, 16, 16)
        icon.setPixmap(IconManager._tint_pixmap(raw_pix, color))

    def update_style(self):
        for idx, (frame, _, _, _, _, _) in enumerate(self.health_rows):
            self._tint_health_icon(frame, idx)
        ThemeManager.repolish(self)

    def apply_theme(self, is_dark):
        super().apply_theme(is_dark)
        self.update_style()
