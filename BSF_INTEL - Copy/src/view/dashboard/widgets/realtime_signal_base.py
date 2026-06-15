import time
import pyqtgraph as pg
from collections import deque
from PyQt6.QtWidgets import QLabel, QPushButton
from PyQt6.QtCore import QTimer, Qt
from ..base import DashboardWidgetBase
from ....utils.theme_manager import ThemeManager
from ....services.industrial_device_manager import IndustrialDeviceManager


class RealTimeSignalWidgetBase(DashboardWidgetBase):
    """
    Base class for high-frequency signal visualization.
    Uses PyQtGraph for performance and a deque for the rolling window.
    """

    def __init__(self, widget_id, title="Signal Graph", unit="Units", parent=None):
        super().__init__(widget_id, title, parent)
        self.unit = unit
        self.rolling_window_sec = 15
        self.sampling_rate = 100
        self.render_fps = 30
        self.max_points = self.rolling_window_sec * self.sampling_rate
        self._y_range = None
        self._y_smoothing = 0.18
        self._sample_count = 0
        self._last_rendered_count = 0

        self.time_buffer = deque(maxlen=self.max_points)
        self.data_buffer = deque(maxlen=self.max_points)

        self.manager = IndustrialDeviceManager.get_instance()
        self.init_graph()
        self._setup_status_indicator()
        self._setup_overlay_controls()

    def _setup_overlay_controls(self):
        self.btn_connect = QPushButton("Connect", self.plot_widget)
        self.btn_connect.setObjectName("SecondaryBtn")
        self.btn_connect.setProperty("role", "connect")
        self.btn_connect.setFixedSize(96, 32)
        self.btn_connect.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_connect.clicked.connect(self.on_connect_clicked)
        self.btn_connect.show()
        self._update_connect_visual("disconnected")

    def on_connect_clicked(self):
        pass

    def _update_connect_visual(self, mode: str):
        self.btn_connect.setProperty("state", mode)
        ThemeManager.repolish(self.btn_connect)

    def update_button_state(self, status: str):
        status_key = (status or "").upper()
        if status_key in {"LIVE", "LIVE (MOCK)"}:
            self.btn_connect.setText("Disconnect")
            self.btn_connect.setEnabled(True)
            self.btn_connect.setObjectName("AlertBtn")
            self._update_connect_visual("live")
        elif status_key == "CONNECTING":
            self.btn_connect.setText("Connecting...")
            self.btn_connect.setEnabled(False)
            self.btn_connect.setObjectName("SecondaryBtn")
            self._update_connect_visual("connecting")
        else:
            self.btn_connect.setText("Connect")
            self.btn_connect.setEnabled(True)
            self.btn_connect.setObjectName("SecondaryBtn")
            self._update_connect_visual("disconnected")

    def _setup_status_indicator(self):
        self.lbl_status = QLabel("DISCONNECTED")
        self.lbl_status.setObjectName("ConnectionStatus")
        self.lbl_status.setProperty("state", "disconnected")
        self.content_layout.insertWidget(0, self.lbl_status, alignment=Qt.AlignmentFlag.AlignRight)

    def update_status(self, status: str):
        status_key = (status or "DISCONNECTED").upper()
        state_map = {
            "DISCONNECTED": "disconnected",
            "CONNECTING": "connecting",
            "LIVE": "live",
            "LIVE (MOCK)": "mock",
            "FAULT": "fault",
        }
        text_map = {
            "DISCONNECTED": "OFFLINE",
            "CONNECTING": "CONNECTING",
            "LIVE": "LIVE",
            "LIVE (MOCK)": "LIVE (MOCK)",
            "FAULT": "FAULT",
        }
        self.lbl_status.setText(text_map.get(status_key, "INFO"))
        self.lbl_status.setProperty("state", state_map.get(status_key, "info"))
        ThemeManager.repolish(self.lbl_status)

    def init_graph(self):
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setAntialiasing(True)
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.22)

        self.plot_item = self.plot_widget.getPlotItem()
        self.plot_item.setLabel("bottom", "Time", units="s")
        self.plot_item.setLabel("left", self.widget_title, units=self.unit)
        self.plot_item.setDownsampling(auto=True, mode="peak")
        self.plot_item.setClipToView(True)

        self.curve = self.plot_widget.plot(
            pen=pg.mkPen(ThemeManager.color("accent_alt"), width=2),
            name=self.widget_title,
        )
        self.curve.setClipToView(True)
        self.curve.setDownsampling(auto=True, method="peak")
        self.lbl_live_value = pg.TextItem(text="--", color=ThemeManager.color("text_primary"), anchor=(1, 0))
        self.plot_item.addItem(self.lbl_live_value)

        self.content_layout.addWidget(self.plot_widget)

        self._update_timer = QTimer()
        self._update_timer.setInterval(max(16, int(1000 / self.render_fps)))
        self._update_timer.timeout.connect(self.refresh_plot)
        self._update_timer.start()

        self.update_style()

    def start_streaming(self):
        pass

    def stop_streaming(self):
        pass

    def on_data_received(self, data: dict):
        pass

    def add_point(self, value):
        now = time.time()
        if not hasattr(self, "_first_ts"):
            self._first_ts = now

        elapsed = now - self._first_ts
        self.time_buffer.append(elapsed)
        self.data_buffer.append(value)
        self._sample_count += 1

    def _mark_sample_received(self):
        self._sample_count += 1

    def refresh_plot(self):
        if self._sample_count == self._last_rendered_count:
            return
        if len(self.data_buffer) < 2:
            return

        times = list(self.time_buffer)
        values = list(self.data_buffer)
        self.curve.setData(times, values)

        current_time = times[-1]
        self.plot_widget.setXRange(max(0, current_time - self.rolling_window_sec), current_time, padding=0)

        latest = values[-1]
        self.lbl_live_value.setText(f"{latest:.2f} {self.unit}")

        # Stabilized dynamic y-scaling to avoid visual jitter.
        v_min = min(values)
        v_max = max(values)
        span = max(v_max - v_min, 1e-6)
        pad = max(0.02 * abs(v_max), span * 0.15, 0.05)
        target_min = v_min - pad
        target_max = v_max + pad

        if self._y_range is None:
            self._y_range = (target_min, target_max)
        else:
            prev_min, prev_max = self._y_range
            alpha = self._y_smoothing
            self._y_range = (
                prev_min + alpha * (target_min - prev_min),
                prev_max + alpha * (target_max - prev_max),
            )
        self.plot_widget.setYRange(self._y_range[0], self._y_range[1], padding=0)

        try:
            rect = self.plot_item.viewRect()
            if rect and not isinstance(rect, bool) and not rect.isEmpty():
                self.lbl_live_value.setPos(current_time, rect.top())
            else:
                self.lbl_live_value.setPos(current_time, latest)
        except Exception:
            self.lbl_live_value.setPos(current_time, latest)

        self._last_rendered_count = self._sample_count

    def update_style(self):
        bg = ThemeManager.color("bg_surface_alt")
        text_color = ThemeManager.color("text_muted")
        grid_color = ThemeManager.color("border_strong")
        accent = ThemeManager.color("accent_alt")

        self.plot_widget.setBackground(bg)

        if self.plot_item:
            self.plot_item.showGrid(
                x=True,
                y=True,
                alpha=0.28 if ThemeManager.is_dark else 0.2,
            )
            for axis in ["left", "bottom"]:
                axis_obj = self.plot_item.getAxis(axis)
                axis_obj.setTextPen(text_color)
                axis_obj.setPen(grid_color)
                axis_obj.setStyle(tickLength=-6, autoExpandTextSpace=True)
            self.plot_item.setLabel("left", self.widget_title, units=self.unit)
            self.plot_item.setLabel("bottom", "Time", units="s")
            self.lbl_live_value.setColor(text_color)

        self.curve.setPen(pg.mkPen(accent, width=2))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "btn_connect"):
            margin = 10
            btn_w = self.btn_connect.width()
            self.btn_connect.move(self.plot_widget.width() - btn_w - margin, margin)

    def apply_theme(self, is_dark):
        super().apply_theme(is_dark)
        self.update_style()
        self._update_connect_visual(self.btn_connect.property("state") or "disconnected")
