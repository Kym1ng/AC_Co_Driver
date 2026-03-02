"""
Node B (Consumer): subscribes to Sniffer, maintains sliding window, evaluates rules.
When an event fires, forwards it to LLMWorker for commentary generation.

Connect: tcp://127.0.0.1:5555 (SUB). Append each frame to deque(maxlen=60).
Separate ~10 Hz loop scans window for events; cooldown prevents spam.
"""
import json
import time
from collections import deque

import zmq

# LLM is optional — if model file missing, rule engine still works without it
try:
    from llm_worker import LLMWorker
    _llm_available = True
except ImportError:
    _llm_available = False

SUB_CONNECT = "tcp://127.0.0.1:5555"
WINDOW_SIZE = 60
RULE_HZ = 10

# ── Rule thresholds (tune after real-world testing) ────────────────
# Hard brake
LONG_G_HARD_BRAKE   = -0.85  # avg longitudinal G
BRAKE_PEDAL_MIN     = 0.7    # brake pedal must be deep
FRONT_LOAD_SHIFT    = 1.2    # front wheel_load / rear wheel_load ratio (nose-dive)
ABS_CONFIRMS_BRAKE  = True   # if ABS fires, always count as hard brake regardless of G

# Hard acceleration / launch
LONG_G_HARD_ACCEL   = 0.7
GAS_PEDAL_MIN       = 0.8

# Launch slip / burnout
REAR_SLIP_LAUNCH    = 0.5    # rear avg slip
FRONT_SLIP_MAX      = 0.15   # front wheels barely slip (distinguishes from 4WD spin)

# Sharp cornering
LATERAL_G_CORNER    = 1.0

# Drift: lateral G + rear > front slip differential
LATERAL_G_DRIFT_MIN = 0.6
REAR_FRONT_SLIP_DIFF = 0.25  # rear slip must exceed front by this margin

COOLDOWN_SEC = 3.0


def main(model_path: str = "models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"):
    # ── optional LLM ─────────────────────────────────────────────────
    llm = None
    if _llm_available:
        try:
            llm = LLMWorker(model_path).start()
            print("LLM loaded and ready.")
        except FileNotFoundError as e:
            print(f"[LLM] Skipping — {e}")

    ctx = zmq.Context()
    sock = ctx.socket(zmq.SUB)
    sock.connect(SUB_CONNECT)
    sock.setsockopt_string(zmq.SUBSCRIBE, "")
    sock.setsockopt(zmq.RCVTIMEO, 500)

    window = deque(maxlen=WINDOW_SIZE)
    last_trigger = {}  # event_type -> last trigger time
    interval = 1.0 / RULE_HZ

    print(f"Rule engine SUB connected to {SUB_CONNECT}. Window={WINDOW_SIZE}, rule loop={RULE_HZ} Hz. Ctrl+C to stop.")
    print("-" * 50)

    next_rule_time = time.perf_counter()
    try:
        while True:
            # Drain all available frames (non-blocking style with timeout)
            try:
                while True:
                    msg = sock.recv_string()
                    frame = json.loads(msg)
                    window.append(frame)
            except zmq.Again:
                pass

            now = time.perf_counter()
            if now >= next_rule_time and len(window) >= 2:
                next_rule_time = now + interval
                latest = window[-1]
                recent = list(window)[-min(10, len(window)):]
                n = len(recent)

                # ── averaged signals over recent frames ───────────────
                avg_long_g    = sum(f["long_g"]    for f in recent) / n
                avg_lateral_g = sum(f["lateral_g"] for f in recent) / n
                speed         = latest["speed"]

                # per-wheel helpers (FL=0, FR=1, RL=2, RR=3)
                def avg_wheel(key, idx):
                    return sum(f[key][idx] for f in recent) / n

                front_slip = (avg_wheel("wheel_slip", 0) + avg_wheel("wheel_slip", 1)) / 2
                rear_slip  = (avg_wheel("wheel_slip", 2) + avg_wheel("wheel_slip", 3)) / 2
                front_load = (avg_wheel("wheel_load", 0) + avg_wheel("wheel_load", 1)) / 2
                rear_load  = (avg_wheel("wheel_load", 2) + avg_wheel("wheel_load", 3)) / 2
                load_ratio = front_load / rear_load if rear_load > 0 else 0

                abs_firing = latest["abs_active"] > 0
                tc_firing  = latest["tc_active"] > 0

                def fire(event_type: str, msg: str):
                    if last_trigger.get(event_type, 0) + COOLDOWN_SEC <= now:
                        last_trigger[event_type] = now
                        print(f"[Event] {event_type}: {msg}")
                        if llm:
                            llm.submit(event_type, {
                                "speed":      speed,
                                "long_g":     avg_long_g,
                                "lateral_g":  avg_lateral_g,
                                "rear_slip":  rear_slip,
                                "front_slip": front_slip,
                            })

                # ── Hard brake ────────────────────────────────────────
                # Trigger if: deep brake pedal AND (strong long_g OR ABS fires OR
                # front/rear load ratio shows nose-dive)
                hard_brake_g     = avg_long_g <= LONG_G_HARD_BRAKE
                hard_brake_pedal = latest["brake"] >= BRAKE_PEDAL_MIN
                hard_brake_load  = load_ratio >= FRONT_LOAD_SHIFT
                if speed > 15 and hard_brake_pedal and (hard_brake_g or hard_brake_load or abs_firing):
                    fire("hard_brake",
                         f"long_g={avg_long_g:.2f} brake={latest['brake']:.2f} "
                         f"load_ratio={load_ratio:.2f} abs={abs_firing}")

                # ── Hard acceleration / launch ─────────────────────────
                if speed < 80 and latest["gas"] >= GAS_PEDAL_MIN and avg_long_g >= LONG_G_HARD_ACCEL:
                    fire("hard_accel",
                         f"long_g={avg_long_g:.2f} gas={latest['gas']:.2f} tc={tc_firing}")

                # ── Launch slip / burnout ─────────────────────────────
                # Rear tyres spinning, fronts not (= RWD burnout / wheelspin)
                if (speed < 30 and latest["gas"] > 0.5
                        and rear_slip >= REAR_SLIP_LAUNCH
                        and front_slip <= FRONT_SLIP_MAX):
                    fire("launch_slip",
                         f"rear={rear_slip:.2f} front={front_slip:.2f}")

                # ── Sharp cornering ───────────────────────────────────
                if abs(avg_lateral_g) >= LATERAL_G_CORNER and speed > 20:
                    fire("sharp_corner", f"lateral_g={avg_lateral_g:.2f}")

                # ── Drift ─────────────────────────────────────────────
                # Lateral G present AND rear slip significantly exceeds front
                if (abs(avg_lateral_g) >= LATERAL_G_DRIFT_MIN
                        and (rear_slip - front_slip) >= REAR_FRONT_SLIP_DIFF):
                    fire("drift",
                         f"lateral_g={avg_lateral_g:.2f} "
                         f"rear_slip={rear_slip:.2f} front_slip={front_slip:.2f}")

            time.sleep(0.02)
    except KeyboardInterrupt:
        print("\nRule engine stopped.")
    finally:
        sock.close()
        ctx.term()


if __name__ == "__main__":
    main()
