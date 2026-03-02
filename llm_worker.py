"""
LLM Worker — Sprint 2.

Loads a GGUF model once at startup, then runs a background thread that
drains an event queue and generates short 傲娇-style commentary.

Usage (standalone test):
    python llm_worker.py

Integration with rule_engine / test_ui:
    from llm_worker import LLMWorker
    llm = LLMWorker("models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf")
    llm.start()
    ...
    llm.submit("hard_brake", {"speed": 120, "long_g": -1.1})

Recommended model (small, fast, great Chinese output):
    Qwen2.5-1.5B-Instruct-Q4_K_M.gguf  (~1 GB)

Download with huggingface-cli:
    pip install huggingface_hub
    huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF \
        Qwen2.5-1.5B-Instruct-Q4_K_M.gguf --local-dir ./models
"""
import queue
import threading
from pathlib import Path

from llama_cpp import Llama

# ── Model config ──────────────────────────────────────────────────────
DEFAULT_MODEL_PATH = "models/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
N_CTX      = 512    # context window (small = fast)
N_GPU_LAYERS = -1   # -1 = offload all layers to GPU/Metal; 0 = CPU only
MAX_TOKENS = 40     # hard cap on output length
TEMPERATURE = 0.85  # a little creative but not unhinged

# ── System persona ────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "你是坐在副驾的傲娇赛车手助手。"
    "驾驶员做了某个动作，你要用简短、毒舌、傲娇的方式吐槽他。"
    "回复不超过15个字，不要解释，直接说。"
)

# ── Per-event user prompt templates ──────────────────────────────────
EVENT_PROMPTS = {
    "hard_brake":   "驾驶员刚才踩了一脚重刹，车头猛地点下去，speed={speed:.0f}km/h。",
    "hard_accel":   "驾驶员地板油起步，推背感很强，speed={speed:.0f}km/h。",
    "launch_slip":  "驾驶员起步时后轮打滑，烧胎声巨大，rear_slip={rear_slip:.2f}。",
    "sharp_corner": "驾驶员高速激烈过弯，lateral_g={lateral_g:.2f}G。",
    "drift":        "驾驶员在漂移，车尾甩出来，lateral_g={lateral_g:.2f}G，rear_slip={rear_slip:.2f}。",
}


class LLMWorker:
    """
    Wraps llama-cpp-python in a background thread.
    Call submit(event_type, data_dict) from any thread.
    Override on_response(event_type, text) to consume output.
    """

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH):
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(
                f"GGUF model not found: {path}\n"
                "Download with:\n"
                "  pip install huggingface_hub\n"
                "  huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF "
                "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf --local-dir ./models"
            )

        print(f"Loading GGUF model: {path} …")
        self._llm = Llama(
            model_path=str(path),
            n_ctx=N_CTX,
            n_gpu_layers=N_GPU_LAYERS,
            verbose=False,
        )
        print("Model loaded.")

        self._queue: queue.Queue = queue.Queue(maxsize=3)   # cap at 3; drop if backed up
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def submit(self, event_type: str, data: dict):
        """Non-blocking. Drops the event if worker is busy (avoids heat buildup)."""
        try:
            self._queue.put_nowait((event_type, data))
        except queue.Full:
            pass  # previous event still processing — skip this one

    def on_response(self, event_type: str, text: str):
        """Override this to pipe output to TTS / UI / anywhere."""
        print(f"[LLM] ({event_type}) → {text}")

    # ── internal ─────────────────────────────────────────────────────
    def _loop(self):
        while True:
            event_type, data = self._queue.get()
            text = self._generate(event_type, data)
            if text:
                self.on_response(event_type, text)

    def _generate(self, event_type: str, data: dict) -> str:
        template = EVENT_PROMPTS.get(event_type)
        if not template:
            return ""
        try:
            user_msg = template.format_map({**data, **{"speed": data.get("speed", 0)}})
        except KeyError:
            user_msg = f"驾驶员发生了 {event_type} 事件。"

        response = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            stop=["\n", "。", "！", "!"],
        )
        raw = response["choices"][0]["message"]["content"].strip()
        return raw


# ── Standalone smoke test ─────────────────────────────────────────────
if __name__ == "__main__":
    import time

    worker = LLMWorker()
    worker.start()

    test_events = [
        ("hard_brake",   {"speed": 130, "long_g": -1.1, "lateral_g": 0.1, "rear_slip": 0.05}),
        ("hard_accel",   {"speed": 20,  "long_g":  0.9, "lateral_g": 0.0, "rear_slip": 0.1}),
        ("launch_slip",  {"speed": 10,  "long_g":  0.6, "lateral_g": 0.1, "rear_slip": 0.7}),
        ("sharp_corner", {"speed": 80,  "long_g": -0.2, "lateral_g": 1.2, "rear_slip": 0.15}),
        ("drift",        {"speed": 60,  "long_g":  0.1, "lateral_g": 0.9, "rear_slip": 0.55}),
    ]

    for ev, data in test_events:
        print(f"\n→ Submitting: {ev}")
        worker.submit(ev, data)
        time.sleep(6)  # wait for LLM to respond before next event
