> 🟢 **excellent** — streak running 12m
> 🟡 **fair** — corrections needed
> 🔴 **poor posture** — alert fired

A tiny tray app that watches your webcam, scores your posture every second on a 0–100 scale, and pings you when you start slouching. No cloud. No accounts. No telemetry. Just a webcam and `uv run`.

## Why

Most posture apps are either subscription SaaS or a Pomodoro timer that yells "stand up!" every 30 minutes. BatesPosture actually looks at you with MediaPipe, computes seven weighted geometric metrics (head tilt, neck angle, shoulder balance, spine alignment, …), and only nudges you when your score drops — calibrated to *your* posture, not a generic threshold.

It's free, open source, and the entire pipeline runs on-device. Nothing leaves your computer.

## Features

| | |
|---|---|
| 🎯 **Live 0–100 score** | Color-coded tray icon updated every second |
| 📊 **Session dashboard** | Sparkline history, average, min/max, best streak, duration |
| 🔔 **Smart alerts** | Native OS notifications with threshold + cooldown + focus mode |
| ⏱️ **Scheduling** | Continuous or interval tracking, plus 50-min break reminders |
| 💾 **Local logging** | Optional SQLite + CSV export, all on your machine |
| ⚡ **Adaptive perf** | Auto-downscales on slow hardware, optional GPU mode |
| 👤 **Auto-pause** | Stops counting away-from-desk time after ~2s no-detection |
| 🔒 **100% local** | No cloud, no accounts, no telemetry, ever |

## Install

Requires [Python 3.10+](https://www.python.org/) and [uv](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/redko-jane/posturecontrol.git
cd posturecontrol
uv sync --all-groups
uv run posturecontrol
```
That's it. Grant camera permission, complete the 6-second calibration, and the tray icon takes over.
## How it works
1. **Calibrate** — a 6-second baseline of your natural posture so alerts are tuned to *you*.
2. **Track** — MediaPipe extracts pose landmarks → seven weighted metrics → one 0–100 score → tray color.
3. **Alert** — score drops below your threshold → native desktop notification (with cooldown to prevent fatigue).
4. **Review** — open the dashboard for the live frame, score sparkline, session stats, and streaks.

**Shortcuts:** `Ctrl+Shift+T` start/stop · `Ctrl+Shift+D` dashboard · `Ctrl+,` settings · `Ctrl+Q` quit
|

