"""
Simple ZMQ subscriber to debug sniffer → UI pipeline.

Run while Assetto Corsa is on track and sniffer.py is running:

  .\.venv\Scripts\Activate.ps1
  python sniffer.py         # terminal 1

  .\.venv\Scripts\Activate.ps1
  python debug_sub.py       # terminal 2

You should see live JSON frames printed a few times per second. If this
prints nothing (only timeouts), then sniffer.py is not publishing or the
port/endpoint is wrong.
"""

import json
import time

import zmq

SUB_CONNECT = "tcp://127.0.0.1:5555"


def main() -> None:
    ctx = zmq.Context()
    sock = ctx.socket(zmq.SUB)
    sock.connect(SUB_CONNECT)
    sock.setsockopt_string(zmq.SUBSCRIBE, "")
    sock.setsockopt(zmq.RCVTIMEO, 500)  # 0.5s timeout

    print(f"[debug_sub] Connected to {SUB_CONNECT}. Waiting for frames...")
    try:
        while True:
            latest = None

            # Drain all queued messages so we always show the *freshest* frame.
            while True:
                try:
                    raw = sock.recv_string(flags=zmq.NOBLOCK)
                except zmq.Again:
                    break
                else:
                    latest = raw

            if latest is None:
                print("[debug_sub] No data in last 0.5s. Is sniffer.py running and AC on track?")
            else:
                try:
                    frame = json.loads(latest)
                except json.JSONDecodeError:
                    print(f"[debug_sub] Received non-JSON: {latest[:120]}...")
                else:
                    speed = frame.get("speed", 0.0)
                    long_g = frame.get("long_g", 0.0)
                    gas = frame.get("gas", 0.0)
                    brake = frame.get("brake", 0.0)
                    print(
                        f"[frame] speed={speed:6.1f} km/h  "
                        f"long_g={long_g:+5.2f}  gas={gas:.2f}  brake={brake:.2f}"
                    )

            time.sleep(0.2)  # throttle console spam
    except KeyboardInterrupt:
        print("\n[debug_sub] Stopped.")
    finally:
        sock.close()
        ctx.term()


if __name__ == "__main__":
    main()

