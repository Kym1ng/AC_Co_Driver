"""
Node A (Producer): reads AC shared memory at 60Hz, publishes JSON to ZMQ.

Run after AC is on track. Bind: tcp://127.0.0.1:5555 (PUB).
No feedback; just read → pack → broadcast → sleep 1/60 s.
"""
import json
import sys
import time

import zmq

from payload import build_payload

try:
    from sim_info import info
except OSError as e:
    print("Cannot connect to AC shared memory. Start Assetto Corsa and be on track first.")
    print("Error:", e)
    sys.exit(1)

PUB_BIND = "tcp://127.0.0.1:5555"
HZ = 60


def main():
    ctx = zmq.Context()
    sock = ctx.socket(zmq.PUB)
    sock.bind(PUB_BIND)
    print(f"Sniffer PUB bound to {PUB_BIND} @ {HZ} Hz. Ctrl+C to stop.")

    try:
        while True:
            p = info.physics  # shorthand

            # ── core motion ──────────────────────────────────────────
            speed       = p.speedKmh
            long_g      = p.accG[2]   # positive=accel, negative=brake
            lateral_g   = p.accG[0]
            gas         = p.gas
            brake       = p.brake
            gear        = p.gear
            rpms        = p.rpms

            # ── per-wheel (FL=0, FR=1, RL=2, RR=3) ──────────────────
            wheel_slip        = list(p.wheelSlip)
            wheel_load        = list(p.wheelLoad)
            suspension_travel = list(p.suspensionTravel)

            # ── driver aids ──────────────────────────────────────────
            abs_active  = p.abs
            tc_active   = p.tc

            # ── chassis attitude ─────────────────────────────────────
            steer_angle = p.steerAngle
            pitch       = p.pitch
            roll        = p.roll

            payload = build_payload(
                speed=speed,
                long_g=long_g,
                lateral_g=lateral_g,
                gas=gas,
                brake=brake,
                gear=gear,
                rpms=rpms,
                wheel_slip=wheel_slip,
                wheel_load=wheel_load,
                suspension_travel=suspension_travel,
                abs_active=abs_active,
                tc_active=tc_active,
                steer_angle=steer_angle,
                pitch=pitch,
                roll=roll,
            )
            sock.send_string(json.dumps(payload))
            time.sleep(1 / HZ)
    except KeyboardInterrupt:
        print("\nSniffer stopped.")
    finally:
        sock.close()
        ctx.term()


if __name__ == "__main__":
    main()
