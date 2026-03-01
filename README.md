# AC Co-Driver

A small **external companion** for Assetto Corsa: it reads the game’s shared memory (no in-game mods), uses rule-based triggers, and will speak back via a local LLM and TTS.

**Right now:** telemetry sniffer only. Enter a track in AC, then run:

```bash
python test_road.py
```

You’ll see live speed, G-forces, throttle/brake, and wheel slip in the terminal. Next steps: trigger rules → LLM + TTS → overlay UI. See [PLAN.md](PLAN.md) for the roadmap.
