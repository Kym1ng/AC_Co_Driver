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
│  后台线程 + queue(maxsize=3) 防堆积，傲娇人设 Prompt                     │
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
│  test_ui.py / Overlay  [✅ MVP 完成，待像素表情细化]                      │
│  PyQt5 置顶透明窗口，FramelessWindowHint + WA_TranslucentBackground      │
│  RuleWorker(QThread) 内嵌规则逻辑，event_fired signal → 显示文字 2.5s   │
└─────────────────────────────────────────────────────────────────────────┘
```

| 模块 | 文件 | 状态 | 技术选型 |
|------|------|------|----------|
| 数据契约 | `payload.py` | ✅ | `build_payload()` 定义全量字段，两侧共用 |
| 数据采集 | `sniffer.py` | ✅ | mmap + ctypes，60Hz ZMQ PUB |
| 规则引擎 | `rule_engine.py` | ✅ | 阈值规则 + deque 窗口 + 冷却机制 |
| LLM 推理 | `llm_worker.py` | ✅ 框架 / ⏳ 待验证 | llama-cpp-python + GGUF，后台队列 |
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
- `test_ui.py`：PyQt5 Overlay MVP，事件触发后屏幕居中显示彩色文字 2.5s（当前作为调试用 UI）
- `debug_sub.py`：极简 ZMQ SUB，用来直接打印 `sniffer.py` 发出的原始 JSON 帧做链路排查

**当前已知问题 / 调试记录**：
- `sniffer.py` 能成功 `bind` 到 `tcp://127.0.0.1:5555`，进 AC 上车后也能从 `sim_info.py` 读到物理量（用 `test_road.py` 验证 OK）。
- 但在实机测试中，`debug_sub.py` / `test_ui.py` 订阅同一地址时，偶尔会出现“PUB 正常、SUB 却长期收不到帧”的情况。
- 期间发现两个干扰因素：
  - 端口占用：老的 `sniffer.py` 进程没有退出，导致新的进程 `ZMQError: Address in use`，需要 `netstat / taskkill` 清理。
  - 调试脚本自身的延迟：早期版本的 `debug_sub.py` 每次只读 1 帧再 `sleep(0.2)`，会在 SUB 侧堆积大量历史消息，看起来像“延迟 30 秒以上”，后续已改为一次性 drain ZMQ 队列，只保留最后一帧。
- 当前状态：`sniffer.py` + 新版 `debug_sub.py` 在命令行里可以看到稳定的 60Hz 数据，但 Overlay UI 还没完全恢复接入（临时改成只显示调试文本），且 Sniffer/ZMQ 对 AC 会话的生命周期行为还需要在更多赛道 / 维修区场景下实车复测。

**待完成**：
- [ ] 把 `test_ui.py` 从“纯调试 Banner（直显 telemetry）”恢复为“基于 rule_engine 的事件可视化 + LLM 吐槽”，并在纽北 / 其他赛道做端到端联调。
- [ ] 下载并实机验证模型：`qwen2.5-1.5b-instruct-q4_k_m.gguf`（~1 GB，已下载到 `models/`，仍需长时间跑车验证稳定性和性能）
- [ ] 接入 edge-tts：覆写 `LLMWorker.on_response()`，文本 → 语音
- [ ] 调试蓝牙 / 扬声器音频通道
- [ ] 跑通完整链路：游戏操作 → Sniffer → Rule → LLM → TTS 播放

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
├── requirements.txt        # 依赖（ollama, zmq, llama-cpp-python, PyQt5, edge-tts…）
├── sim_info.py             # AC 共享内存结构体（官方翻译官）
├── payload.py              # 数据契约：build_payload() 定义 JSON 帧格式
├── sniffer.py              # Node A：60Hz 采集 → ZMQ PUB
├── rule_engine.py          # Node B：ZMQ SUB → 规则 → Event → LLM submit
├── llm_worker.py           # LLM 推理模块（llama-cpp-python + GGUF）
├── test_road.py            # 终端仪表盘（连通性测试）
├── test_ui.py              # PyQt5 Overlay MVP（事件触发 → 屏幕显示）
├── models/                 # GGUF 模型存放处（.gitignore 大文件）
└── venv/                   # 虚拟环境（.gitignore）
```

---

## 4. 下一步（最近优先）

1. `pip install llama-cpp-python` 并下载 GGUF 模型到 `models/`
2. 跑 `python llm_worker.py` 离线验证 5 种事件的吐槽输出
3. 覆写 `LLMWorker.on_response()` 接入 edge-tts，实现文字 → 语音
4. 同时开 sniffer + rule_engine + test_ui，完整实车联调

---

*最后更新：Sprint 1 全部完成；Sprint 2 LLM 框架完成，TTS 待接入；Overlay MVP 就绪。*
