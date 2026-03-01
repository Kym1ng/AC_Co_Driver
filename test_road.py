"""
AC 共享内存连通性测试 — 嗅探器 Hello World

运行前：用 Content Manager 进入任意赛道、上车、停在赛道上（AC 才会写入共享内存）。
运行：python test_road.py
用 Ctrl+C 退出。
"""
import sys
import time

# 先尝试连接共享内存，失败则提示先开 AC
try:
    from sim_info import info
except OSError as e:
    print("无法连接 AC 共享内存。请先启动 Assetto Corsa 并进入赛道（车已在赛道上）。")
    print("错误:", e)
    sys.exit(1)


def main():
    print("=" * 60)
    print("  AC 数据嗅探器已连接 | 按 Ctrl+C 退出")
    print("=" * 60)
    print("  车速(km/h) | 纵向G | 横向G | 油门 | 刹车 | 档位 | 转速 | 平均打滑 | 后轮打滑")
    print("-" * 60)

    try:
        while True:
            # 物理层
            speed = info.physics.speedKmh
            gas = info.physics.gas
            brake = info.physics.brake
            gear = info.physics.gear
            rpms = info.physics.rpms

            # accG: [横向, 垂直, 纵向] — 纵向正=加速，负=刹车
            lateral_g = info.physics.accG[0]
            long_g = info.physics.accG[2]

            # 四轮打滑: 通常 FL, FR, RL, RR
            slip = info.physics.wheelSlip
            avg_slip = (slip[0] + slip[1] + slip[2] + slip[3]) / 4.0
            rear_slip = (slip[2] + slip[3]) / 2.0  # 后轮，漂移/烧胎常用

            # 车动起来再刷屏，否则只做静默轮询
            if speed > 1.0:
                line = (
                    f"  {speed:6.1f}   | {long_g:+5.2f} | {lateral_g:+5.2f} | "
                    f"{gas:.2f} | {brake:.2f} |  {gear:2d}  | {rpms:5d} | "
                    f"  {avg_slip:.2f}   |   {rear_slip:.2f}"
                )
                print(line, end="\r")

            time.sleep(1 / 60)  # 约 60Hz，与 AC 写入频率一致

    except KeyboardInterrupt:
        print("\n\n嗅探结束，退出程序。")


if __name__ == "__main__":
    main()
