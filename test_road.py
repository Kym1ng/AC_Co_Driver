"""
AC shared memory connectivity test — Sniffer Hello World

Before running: Use Content Manager to enter any track, get in the car, and be on track
(AC only writes to shared memory then). Run: python test_road.py. Press Ctrl+C to exit.
"""
import sys
import time

# Try to connect to shared memory first; on failure prompt to start AC
try:
    from sim_info import info
except OSError as e:
    print("Cannot connect to AC shared memory. Please start Assetto Corsa and enter a track (car on track) first.")
    print("Error:", e)
    sys.exit(1)


def main():
    print("=" * 60)
    print("  AC data sniffer connected | Press Ctrl+C to exit")
    print("=" * 60)
    print("  Speed(km/h) | Long.G | Lat.G | Gas | Brake | Gear | RPM | Avg slip | Rear slip")
    print("-" * 60)

    try:
        while True:
            # Physics
            speed = info.physics.speedKmh
            gas = info.physics.gas
            brake = info.physics.brake
            gear = info.physics.gear
            rpms = info.physics.rpms

            # accG: [lateral, vertical, longitudinal] — long positive=accel, negative=brake
            lateral_g = info.physics.accG[0]
            long_g = info.physics.accG[2]

            # Wheel slip: usually FL, FR, RL, RR
            slip = info.physics.wheelSlip
            avg_slip = (slip[0] + slip[1] + slip[2] + slip[3]) / 4.0
            rear_slip = (slip[2] + slip[3]) / 2.0  # rear wheels, drift/burnout

            # Only refresh display when car is moving; otherwise poll silently
            if speed > 1.0:
                line = (
                    f"  {speed:6.1f}   | {long_g:+5.2f} | {lateral_g:+5.2f} | "
                    f"{gas:.2f} | {brake:.2f} |  {gear:2d}  | {rpms:5d} | "
                    f"  {avg_slip:.2f}   |   {rear_slip:.2f}"
                )
                print(line, end="\r")

            time.sleep(1 / 60)  # ~60Hz, matches AC write rate

    except KeyboardInterrupt:
        print("\n\nSniffer stopped. Exiting.")


if __name__ == "__main__":
    main()
