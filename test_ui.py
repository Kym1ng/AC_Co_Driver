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
from PyQt5.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import QApplication, QLabel, QWidget

DEBUG = True  # set False to reduce console output

try:
    from llm_worker import LLMWorker, DEFAULT_MODEL_PATH

    _llm_available = True
    _llm_import_error = None
except Exception as e:  # llama-cpp or model path might be missing
    _llm_available = False
    _llm_import_error = e

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


class LLMBridge(QObject):
    """Qt bridge that exposes a signal for LLM text."""

    text_ready = pyqtSignal(str)


if _llm_available:
    class QtLLMWorker(LLMWorker):
        """LLMWorker that forwards responses to a Qt signal instead of printing."""

        def __init__(self, bridge: LLMBridge, model_path: str = DEFAULT_MODEL_PATH):
            self._bridge = bridge
            super().__init__(model_path=model_path)

        def on_response(self, event_type: str, text: str):
            # Emit only the final LLM text; UI decides how to render it.
            if DEBUG:
                print(f"[LLM] ({event_type}) -> {text}")
            self._bridge.text_ready.emit(text)


# ─────────────────────────────────────────────────────────────────────
# Background worker: ZMQ SUB + rule evaluation → emits Qt signal
# ─────────────────────────────────────────────────────────────────────
class RuleWorker(QThread):
    event_fired = pyqtSignal(str)      # emits event_type string (rules)
    frame_received = pyqtSignal(object)  # emits latest raw frame for debug

    def __init__(self, llm=None):
        super().__init__()
        self._llm = llm

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

        # ── debug/health counters (rate-limited) ─────────────────────
        rx_frames = 0
        last_rx_time = 0.0
        last_stats_time = time.perf_counter()
        last_stats_frames = 0

        if DEBUG:
            print(f"[UI] RuleWorker connected SUB to {SUB_CONNECT}")

        while True:
            # drain ZMQ buffer
            try:
                while True:
                    raw = sock.recv_string()
                    frame = json.loads(raw)
                    window.append(frame)
                    rx_frames += 1
                    last_rx_time = time.perf_counter()
            except zmq.Again:
                pass

            now = time.perf_counter()

            # ── periodic stats (once per second) ─────────────────────
            if DEBUG and (now - last_stats_time) >= 1.0:
                dt = now - last_stats_time
                fps = (rx_frames - last_stats_frames) / dt if dt > 0 else 0.0
                last_stats_frames = rx_frames
                last_stats_time = now

                if window:
                    latest = window[-1]
                    spd = latest.get("speed", -1)
                    print(f"[UI] rx={fps:5.1f} fps | window={len(window):2d} | speed={spd:6.1f} km/h")
                else:
                    print(f"[UI] rx={fps:5.1f} fps | window= 0 | waiting for sniffer…")

                if last_rx_time and (now - last_rx_time) > 2.0:
                    print("[UI][WARN] No telemetry received for >2s. Is sniffer.py running?")

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
                        if self._llm is not None:
                            if DEBUG:
                                print(
                                    f"[UI][Event] {event_type} | speed={speed:.1f} "
                                    f"long_g={avg_long_g:.2f} lat_g={avg_lateral_g:.2f} "
                                    f"rear_slip={rear_slip:.2f} front_slip={front_slip:.2f}"
                                )
                            self._llm.submit(
                                event_type,
                                {
                                    "speed":      speed,
                                    "long_g":     avg_long_g,
                                    "lateral_g":  avg_lateral_g,
                                    "rear_slip":  rear_slip,
                                    "front_slip": front_slip,
                                },
                            )
                        else:
                            if DEBUG:
                                print(f"[UI][Event] {event_type} (LLM disabled) ")
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

                # ── debug: always show latest raw frame on overlay ──
                # Instead of relying on rule triggers, push the most
                # recent frame to the UI every rule tick so we can see
                # speed / gas / brake directly.
                self.frame_received.emit(latest)

            time.sleep(0.02)


# ─────────────────────────────────────────────────────────────────────
# Overlay window
# ─────────────────────────────────────────────────────────────────────
class Overlay(QWidget):
    def __init__(self):
        super().__init__()

        # ── OS-level window flags ────────────────────────────────────
        # NOTE: for debugging visibility we temporarily DISABLE
        # WindowTransparentForInput so you can click/drag this window
        # and clearly see it above the game. Once confirmed, we can
        # turn the click-through flag back on.
        self.setWindowFlags(
            Qt.FramelessWindowHint         # no title bar / border
            | Qt.WindowStaysOnTopHint      # always on top
            | Qt.Tool                      # no taskbar entry
            # | Qt.WindowTransparentForInput # mouse clicks pass through
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
        # For debugging, give the text a semi-opaque dark background so
        # it is unmistakably visible on top of AC.
        self.label.setStyleSheet(
            "color: white; background-color: rgba(0, 0, 0, 180);"
        )

        # ── hide timer ───────────────────────────────────────────────
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._clear)

        self.show()

        if DEBUG:
            print("[UI] Overlay window created (transparent, always-on-top).")
            # Show a persistent banner for a few seconds so you can
            # visually confirm the overlay window location.
            self.label.setText("AC Co-Driver overlay ACTIVE")
            self._hide_timer.start(4000)

    def show_event(self, event_type: str):
        label_text = EVENT_LABELS.get(event_type, event_type)
        self.label.setText(label_text)
        # Use same style as telemetry banner: white text on dark background.
        self.label.setStyleSheet(
            "color: white; background-color: rgba(0, 0, 0, 180);"
        )
        self._hide_timer.start(DISPLAY_MS)

    def show_frame(self, frame: object):
        """Show raw telemetry values from sniffer for debugging ZMQ."""
        if not isinstance(frame, dict):
            return
        try:
            speed = frame.get("speed", 0.0)
            long_g = frame.get("long_g", 0.0)
            lateral_g = frame.get("lateral_g", 0.0)
            gas = frame.get("gas", 0.0)
            brake = frame.get("brake", 0.0)
        except Exception:
            return
        text = (
            f"speed={speed:6.1f} km/h  "
            f"long_g={long_g:+5.2f}  lat_g={lateral_g:+5.2f}  "
            f"gas={gas:.2f}  brake={brake:.2f}"
        )
        self.label.setText(text)
        self.label.setStyleSheet(
            "color: white; background-color: rgba(0, 0, 0, 180);"
        )
        self._hide_timer.start(DISPLAY_MS)

    def show_llm_text(self, text: str):
        """Show raw LLM commentary text in the overlay."""
        if not text:
            return
        self.label.setText(text)
        self.label.setStyleSheet(
            "color: white; background-color: rgba(0, 0, 0, 180);"
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

    worker = RuleWorker(llm=None)
    # For ZMQ debugging, show raw telemetry frames directly in the UI.
    worker.frame_received.connect(overlay.show_frame)
    worker.daemon = True
    worker.start()

    print("Overlay running. Make sure sniffer.py is running too.")
    print("Press Ctrl+C in terminal to exit.")
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
