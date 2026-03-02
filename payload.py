"""
Data contract between Sniffer (PUB) and Rule Engine (SUB).

Every frame broadcast by sniffer.py is a JSON object with these keys.
Rule Engine reads exactly these keys — don't rename without updating both sides.

Core motion:
  timestamp   float   Unix time
  speed       float   km/h
  long_g      float   longitudinal G (positive=accel, negative=brake)
  lateral_g   float   lateral G (left/right)
  gas         float   throttle pedal 0–1
  brake       float   brake pedal 0–1
  gear        int     current gear (0=R, 1=N, 2=1st …)
  rpms        int     engine RPM

Per-wheel data (order: FL, FR, RL, RR):
  wheel_slip      list[4]  slip ratio per wheel  — key for drift/launch/lockup
  wheel_load      list[4]  downforce per wheel (N) — weight transfer during braking
  suspension_travel list[4] suspension compression — detects nose-dive on hard brake

Driver aids (active = value > 0):
  abs_active  float   ABS intervention level (0 = not active)
  tc_active   float   TC intervention level  (0 = not active)

Chassis attitude:
  steer_angle float   steering wheel angle (rad)
  pitch       float   nose-up/down angle (rad) — rises on hard brake
  roll        float   body roll (rad)
"""

import time


def build_payload(
    speed: float,
    long_g: float,
    lateral_g: float,
    gas: float,
    brake: float,
    gear: int,
    rpms: int,
    wheel_slip: list,
    wheel_load: list,
    suspension_travel: list,
    abs_active: float,
    tc_active: float,
    steer_angle: float,
    pitch: float,
    roll: float,
) -> dict:
    """Build one telemetry frame. Sniffer calls this every 1/60 s."""
    return {
        "timestamp": time.time(),
        # ── core motion ────────────────────────────────
        "speed":       round(speed, 2),
        "long_g":      round(long_g, 3),
        "lateral_g":   round(lateral_g, 3),
        "gas":         round(gas, 3),
        "brake":       round(brake, 3),
        "gear":        int(gear),
        "rpms":        int(rpms),
        # ── per-wheel (FL, FR, RL, RR) ─────────────────
        "wheel_slip":        [round(v, 3) for v in wheel_slip],
        "wheel_load":        [round(v, 1) for v in wheel_load],
        "suspension_travel": [round(v, 4) for v in suspension_travel],
        # ── driver aids ────────────────────────────────
        "abs_active":  round(abs_active, 3),
        "tc_active":   round(tc_active, 3),
        # ── chassis attitude ───────────────────────────
        "steer_angle": round(steer_angle, 4),
        "pitch":       round(pitch, 4),
        "roll":        round(roll, 4),
    }
