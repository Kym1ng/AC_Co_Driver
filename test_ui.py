"""
Overlay UI — Sprint 2 test harness.

Runs the full rule-engine logic in a background QThread, subscribing to
sniffer.py's ZMQ PUB. When an event fires, the overlay window shows it
centred on-screen in large bold text, then fades out after 2 seconds.

Usage:
  Terminal 1 (in AC on track): python sniffer.py
  Terminal 2                 : python test_ui.py

Window properties:
  - No border / title bar
  - Transparent background (click passes through to game)
  - Always on top
  - Mouse-click-through (WindowTransparentForInput)
"""
import json
import sys
import time
from collections import deque

import zmq
from PyQt5.QtCore import (Qt, QThread, QTimer, pyqtSignal)
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import QApplication, QLabel, QWidget

# ── ZMQ ──────────────────────────────────────────────────────────────
SUB_CONNECT  = "tcp://127.0.0.1:5555"
WINDOW_SIZE  = 60
RULE_HZ      = 10

# ── Thresholds (mirror rule_engine.py) ───────────────────────────────
LONG_G_HARD_BRAKE    = -0.85
BRAKE_PEDAL_MIN      =  0.7
FRONT_LOAD_SHIFT     =  1.2
LONG_G_HARD_ACCEL    =  0.7
GAS_PEDAL_MIN        =  0.8
REAR_SLIP_LAUNCH     =  0.5
FRONT_SLIP_MAX       =  0.15
LATERAL_G_CORNER     =  1.0
LATERAL_G_DRIFT_MIN  =  0.6
REAR_FRONT_SLIP_DIFF =  0.25
COOLDOWN_SEC         =  3.0

# ── Event display config ─────────────────────────────────────────────
EVENT_LABELS = {
    "hard_brake":   "🛑 Hard Brake!!!",
    "hard_accel":   "🚀 Full Send!!!",
    "launch_slip":  "🔥 Wheelspin!!!",
    "sharp_corner": "🏎  Sharp Corner!",
    "drift":        "💨 Drifting!!!",
}
EVENT_COLORS = {
    "hard_brake":   "#FF4444",
    "hard_accel":   "#44FF88",
    "launch_slip":  "#FF8C00",
    "sharp_corner": "#44CCFF",
    "drift":        "#FF44FF",
}
DISPLAY_MS = 2500   # how long each event stays visible


# ─────────────────────────────────────────────────────────────────────
# Background worker: ZMQ SUB + rule evaluation → emits Qt signal
# ─────────────────────────────────────────────────────────────────────
class RuleWorker(QThread):
    event_fired = pyqtSignal(str)   # emits event_type string

    def run(self):
        ctx = zmq.Context()
        sock = ctx.socket(zmq.SUB)
        sock.connect(SUB_CONNECT)
        sock.setsockopt_string(zmq.SUBSCRIBE, "")
        sock.setsockopt(zmq.RCVTIMEO, 200)

        window = deque(maxlen=WINDOW_SIZE)
        last_trigger = {}
        interval = 1.0 / RULE_HZ
        next_rule_time = time.perf_counter()

        while True:
            # drain ZMQ buffer
            try:
                while True:
                    frame = json.loads(sock.recv_string())
                    window.append(frame)
            except zmq.Again:
                pass

            now = time.perf_counter()
            if now >= next_rule_time and len(window) >= 2:
                next_rule_time = now + interval
                latest = window[-1]
                recent = list(window)[-min(10, len(window)):]
                n      = len(recent)

                avg_long_g    = sum(f["long_g"]    for f in recent) / n
                avg_lateral_g = sum(f["lateral_g"] for f in recent) / n
                speed         = latest["speed"]

                def avg_wheel(key, idx):
                    return sum(f[key][idx] for f in recent) / n

                front_slip = (avg_wheel("wheel_slip", 0) + avg_wheel("wheel_slip", 1)) / 2
                rear_slip  = (avg_wheel("wheel_slip", 2) + avg_wheel("wheel_slip", 3)) / 2
                front_load = (avg_wheel("wheel_load", 0) + avg_wheel("wheel_load", 1)) / 2
                rear_load  = (avg_wheel("wheel_load", 2) + avg_wheel("wheel_load", 3)) / 2
                load_ratio = front_load / rear_load if rear_load > 0 else 0
                abs_firing = latest["abs_active"] > 0

                def fire(event_type):
                    if last_trigger.get(event_type, 0) + COOLDOWN_SEC <= now:
                        last_trigger[event_type] = now
                        self.event_fired.emit(event_type)

                # hard brake
                if (speed > 15
                        and latest["brake"] >= BRAKE_PEDAL_MIN
                        and (avg_long_g <= LONG_G_HARD_BRAKE
                             or load_ratio >= FRONT_LOAD_SHIFT
                             or abs_firing)):
                    fire("hard_brake")

                # hard accel
                if (speed < 80
                        and latest["gas"] >= GAS_PEDAL_MIN
                        and avg_long_g >= LONG_G_HARD_ACCEL):
                    fire("hard_accel")

                # launch slip
                if (speed < 30
                        and latest["gas"] > 0.5
                        and rear_slip >= REAR_SLIP_LAUNCH
                        and front_slip <= FRONT_SLIP_MAX):
                    fire("launch_slip")

                # sharp corner
                if abs(avg_lateral_g) >= LATERAL_G_CORNER and speed > 20:
                    fire("sharp_corner")

                # drift
                if (abs(avg_lateral_g) >= LATERAL_G_DRIFT_MIN
                        and (rear_slip - front_slip) >= REAR_FRONT_SLIP_DIFF):
                    fire("drift")

            time.sleep(0.02)


# ─────────────────────────────────────────────────────────────────────
# Overlay window
# ─────────────────────────────────────────────────────────────────────
class Overlay(QWidget):
    def __init__(self):
        super().__init__()

        # ── OS-level window flags ────────────────────────────────────
        self.setWindowFlags(
            Qt.FramelessWindowHint         # no title bar / border
            | Qt.WindowStaysOnTopHint      # always on top
            | Qt.Tool                      # no taskbar entry
            | Qt.WindowTransparentForInput # mouse clicks pass through
        )
        self.setAttribute(Qt.WA_TranslucentBackground)  # true transparent bg
        self.setAttribute(Qt.WA_ShowWithoutActivating)  # don't steal focus

        # ── full-screen (so text can appear anywhere) ─────────────────
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        # ── event label ──────────────────────────────────────────────
        self.label = QLabel("", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setGeometry(0, screen.height() // 3,
                               screen.width(), screen.height() // 3)

        font = QFont("Arial Black", 56, QFont.Black)
        self.label.setFont(font)
        self.label.setStyleSheet("color: white; background: transparent;")

        # ── hide timer ───────────────────────────────────────────────
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._clear)

        self.show()

    def show_event(self, event_type: str):
        label_text = EVENT_LABELS.get(event_type, event_type)
        color      = EVENT_COLORS.get(event_type, "#FFFFFF")
        shadow     = "2px 2px 12px rgba(0,0,0,0.9)"
        self.label.setText(label_text)
        self.label.setStyleSheet(
            f"color: {color}; background: transparent;"
            f"text-shadow: {shadow};"
        )
        self._hide_timer.start(DISPLAY_MS)

    def _clear(self):
        self.label.setText("")


# ─────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)

    overlay = Overlay()

    worker = RuleWorker()
    worker.event_fired.connect(overlay.show_event)
    worker.daemon = True
    worker.start()

    print("Overlay running. Make sure sniffer.py is running too.")
    print("Press Ctrl+C in terminal to exit.")
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
