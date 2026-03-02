# AI Co-Driver — 项目总体计划 (Project Plan)

## 产品基调

**低门槛、解压即用**：面向 Assetto Corsa 玩家的桌面端"外挂式"驾驶伴侣，无需在游戏内装任何现代 Python 环境。

**技术现实**：AC 内置 Python 为 3.3，无法安装现代 LLM/TTS 库 → 采用**外挂式独立程序**架构，在 Windows 上单独运行，通过共享内存读取游戏遥测。

---

## 1. 核心架构与数据流向

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Assetto Corsa (Shared Memory)                                          │
└───────────────────────────────┬─────────────────────────────────────────┘
                                 │ mmap @ 60Hz
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  sniffer.py  [✅ 完成]                                                   │
│  ZMQ PUB @ tcp://127.0.0.1:5555，60Hz 广播 JSON payload                 │
│  字段：speed, long_g, lateral_g, gas, brake, gear, rpms,               │
│        wheel_slip[4], wheel_load[4], suspension_travel[4],             │
│        abs_active, tc_active, steer_angle, pitch, roll                 │
└───────────────────────────────┬─────────────────────────────────────────┘
                                 │ JSON @ 60Hz (ZMQ PUB/SUB)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  rule_engine.py  [✅ 完成]                                               │
│  ZMQ SUB，deque(maxlen=60) 滑动窗口，10Hz 规则扫描                       │
│  Events：hard_brake / hard_accel / launch_slip /                        │
│           sharp_corner / drift                                          │
│  触发后：① print Event  ② submit 到 LLMWorker（可选）                   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                 │ event_type + context dict
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  llm_worker.py  [✅ 框架完成，待实车验证]                                 │
│  llama-cpp-python + Qwen2.5-1.5B-Instruct-Q4_K_M.gguf                  │
│  后台线程 + queue(maxsize=3) 防堆积，tsundere 人设 Prompt（英文）        │
│  on_response() 可覆写 → 默认 print，后续接 TTS                          │
└───────────────────────────────┬─────────────────────────────────────────┘
                                 │ 生成文本
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  TTS  [⏳ 待开发]                                                        │
│  edge-tts（微软在线）或 Windows SAPI5 本地                               │
│  覆写 LLMWorker.on_response() 接入即可                                   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                 │ 音频
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  test_ui.py / Overlay  [✅ MVP 完成，待恢复规则+LLM联动]                  │
│  PyQt5 置顶透明窗口，FramelessWindowHint + WA_TranslucentBackground      │
│  RuleWorker(QThread) 内嵌规则逻辑，event_fired signal → 显示文字 2.5s   │
└─────────────────────────────────────────────────────────────────────────┘
```

| 模块 | 文件 | 状态 | 技术选型 |
|------|------|------|----------|
| 数据契约 | `payload.py` | ✅ | `build_payload()` 定义全量字段，两侧共用 |
| 数据采集 | `sniffer.py` | ✅ | mmap + ctypes，60Hz ZMQ PUB |
| 规则引擎 | `rule_engine.py` | ✅ | 阈值规则 + deque 窗口 + 冷却机制 |
| LLM 推理 | `llm_worker.py` | ✅ 框架 / ⏳ 待实车验证 | llama-cpp-python + GGUF，后台队列 |
| TTS | — | ⏳ 待开发 | edge-tts / SAPI5，覆写 on_response() |
| Overlay UI | `test_ui.py` | ✅ MVP | PyQt5 无边框透明置顶，QThread 驱动 |

---

## 2. 里程碑计划 (Milestones)

### Sprint 1：物理外挂与规则引擎 ✅

**交付物已完成**：
- `sim_info.py`：AC 共享内存翻译官（mmap + ctypes 结构体）
- `payload.py`：数据契约，含 15 个物理字段（per-wheel slip/load/suspension 等）
- `sniffer.py`：60Hz 遥测采集，ZMQ PUB
- `rule_engine.py`：5 类事件规则引擎（ZMQ SUB + 滑动窗口 + 冷却）
- `test_road.py`：终端实时仪表盘，连通性验证工具

---

### Sprint 2：灵魂注入 (LLM & TTS) — 进行中

**已完成**：
- `llm_worker.py`：后台线程封装，queue 防堆积，5 个事件各有 Prompt 模板，人设改为英文 tsundere
- `rule_engine.py` 已接入：`fire()` 触发时自动 `submit` 给 LLM，LLM 不可用时静默降级
- `test_ui.py`：PyQt5 Overlay MVP，窗口弹出、Banner 显示均验证通过
- `debug_sub.py`：极简 ZMQ SUB 调试工具，直接打印 sniffer 原始帧
- `run_co_driver.bat`：一键启动两个进程（sniffer + debug_sub / test_ui）

**调试记录（已全部解决）**：

1. **端口占用 (`ZMQError: Address in use`)**
   - 老 `sniffer.py` 进程未退出时新进程无法 `bind`，需要 `netstat -ano | findstr 5555` + `taskkill /PID xxx /F` 清理。
   - ✅ 已修复：`bind` 后立即加 `sock.setsockopt(zmq.LINGER, 0)`，Ctrl+C 后端口立刻释放，不再拖泥带水。

2. **SUB 端 drain 循环阻塞导致幽灵延迟 30s+**
   - 根本原因：`recv_string()`（无 flag）配合 `RCVTIMEO=500ms`，每次队列排空时会死等 500ms 才抛 `zmq.Again`，60Hz 数据流在底层缓冲区疯狂堆积，表现为"SUB 长期收不到帧"或"UI 严重卡顿"。
   - ✅ 已修复：改为 `recv_string(flags=zmq.NOBLOCK)`，队列空时立刻跳出。三个文件均已修改：`debug_sub.py`、`rule_engine.py`、`test_ui.py`。

3. **AC 关闭后共享内存残留假数据**
   - AC 退出后 Windows 命名共享内存不清零，`sniffer.py` 可以连上并持续广播上次游戏最后一帧（如 speed=12.4 km/h），让 `debug_sub` 误以为游戏在运行。
   - ✅ 已修复：`sniffer.py` 的发布循环加 `if info.graphics.status != 2: continue`，只有 AC 处于 `AC_LIVE` 状态才发布帧，其余状态静默空转。

**当前状态（链路已通）**：
- `sniffer.py` → ZMQ PUB → `debug_sub.py` 全链路验证通过，数据实时、无延迟、无假帧。
- `test_ui.py` Overlay 窗口弹出正常，Banner 可见，当前处于"显示原始 telemetry 调试模式"，规则引擎 + LLM 联动待恢复。

**待完成**：
- [ ] 把 `test_ui.py` 从"纯调试 Banner"恢复为"规则引擎事件可视化 + LLM 吐槽"，端到端联调。
- [ ] 实机验证 LLM：`qwen2.5-1.5b-instruct-q4_k_m.gguf`（已下载到 `models/`），验证响应延迟与吐槽质量。
- [ ] 接入 edge-tts：覆写 `LLMWorker.on_response()`，文本 → 语音。
- [ ] 调试蓝牙 / 扬声器音频通道。
- [ ] 跑通完整链路：游戏操作 → Sniffer → Rule → LLM → TTS 播放。

---

### Sprint 3：包装与分发 (Productization) — 待开始

**目标**：小白玩家解压即用。

- [ ] PyInstaller 打包：所有脚本 + 依赖 + GGUF 路径 → 单 .exe 或目录
- [ ] Overlay 像素表情细化（替换现在的文字为像素艺术动画）
- [ ] 整理 Content Manager 兼容的文件夹结构 + 用户说明文档

---

## 3. 当前文件结构（实际）

```
co_driver/
├── PLAN.md                 # 本文件
├── README.md               # 项目简介
├── requirements.txt        # 依赖（zmq, llama-cpp-python, PyQt5, edge-tts…）
├── run_co_driver.bat       # 一键启动脚本（sniffer + test_ui / debug_sub）
├── sim_info.py             # AC 共享内存结构体（官方翻译官）
├── payload.py              # 数据契约：build_payload() 定义 JSON 帧格式
├── sniffer.py              # Node A：60Hz 采集 → ZMQ PUB（仅 AC_LIVE 时发布）
├── rule_engine.py          # Node B：ZMQ SUB → 规则 → Event → LLM submit
├── llm_worker.py           # LLM 推理模块（llama-cpp-python + GGUF）
├── test_road.py            # 终端仪表盘（连通性测试）
├── test_ui.py              # PyQt5 Overlay MVP（当前为调试 Banner 模式）
├── debug_sub.py            # 极简 ZMQ SUB 调试工具
├── models/                 # GGUF 模型存放处（.gitignore 大文件）
└── .venv/                  # 虚拟环境（.gitignore）
```

---

## 4. 下一步（最近优先）

1. 恢复 `test_ui.py` 的规则引擎 + LLM 联动，在 AC 上实车跑通完整链路
2. 覆写 `LLMWorker.on_response()` 接入 edge-tts，实现文字 → 语音
3. 全链路联调：游戏操作 → Sniffer → Rule → LLM → TTS 播放

---

*最后更新：Sprint 1 全部完成；Sprint 2 ZMQ 链路调试完毕（三个 bug 已修复），Overlay MVP 就绪，LLM 实车验证与 TTS 接入为下一步。*
