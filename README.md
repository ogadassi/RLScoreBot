# ⚡ RLScoreBot — Automated Goal Soundboard for Rocket League

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/ogadassi/RLScoreBot)
[![Website](https://img.shields.io/badge/Website-2026%20Gaming%20UI-00f0ff.svg)](https://ogadassi.github.io/RLScoreBot/)
[![Release](https://img.shields.io/badge/release-v2.0.0--cloud-ff6b00.svg)](https://github.com/ogadassi/RLScoreBot/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-orange.svg)](LICENSE)
[![Discord API](https://img.shields.io/badge/Discord-Slash%20Commands-5865F2.svg)](https://discord.com/developers/docs)

🌐 **Live Web Application**: [https://ogadassi.github.io/RLScoreBot/](https://ogadassi.github.io/RLScoreBot/)  
🚀 **1-Click 24/7 Cloud Host**: [![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/ogadassi/RLScoreBot)

**RLScoreBot** is a 24/7 Cloud-Hosted Discord Bot & 2026 Web Application that plays **custom uploaded goal celebration sounds** in your Discord Voice Channel whenever a goal is scored in Rocket League!

> 📜 **Looking for the legacy v1.0 Standalone Desktop version (Computer Vision / PyWin32)?**  
> Check out the [v1.0.0-desktop Release](https://github.com/ogadassi/RLScoreBot/releases/tag/v1.0.0-desktop) or switch to the [`legacy/desktop-cv`](https://github.com/ogadassi/RLScoreBot/tree/legacy/desktop-cv) branch.

---

## 🚀 1-Click Free 24/7 Cloud Deployment

Click the button below to automatically deploy RLScoreBot to **Render.com** (100% Free 24/7 Hosting):

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/ogadassi/RLScoreBot)

1. Click **Deploy to Render**.
2. Sign in with GitHub (`ogadassi`).
3. Enter your `DISCORD_TOKEN` and `OWNER_ID`.
4. Click **Apply** — Render will build the Docker container and keep your bot online 24/7!

---

## ⚙️ Key Features

* 🎵 **Custom Soundboard Library**: Server members can upload custom celebration sound clips (`/upload`). All uploads are automatically processed via `ffmpeg` to match standard broadcasting loudness (**-14 LUFS**).
* 🔌 **Zero-Friction BakkesMod Telemetry**: A silent C++ BakkesMod plugin catches goal events in Rocket League memory with **0% CPU/GPU overhead** and pings the cloud bot.
* 🌐 **2026 Gaming Web Application**: Interactive Web UI featuring sound previews, command search explorer, and 1-click Discord invite generator.
* 🐳 **1-Click Container Deployment**: Built with `Dockerfile` and `docker-compose.yml` for instant deployment.

---

## 🏗️ System Architecture

```
 ┌─────────────────────────┐               ┌─────────────────────────────────┐               ┌─────────────────────────┐
 │   Gamer's PC (RL)       │               │      Cloud Server (24/7)        │               │   Friends' Discord VC   │
 │                         │               │                                 │               │                         │
 │  BakkesMod Plugin       │──HTTP Webhook─►  FastAPI / aiohttp Web Endpoint  │               │  Bot joins VC & plays   │
 │  (Detects Goal Event)   │   (/api/goal) │                │                │──Voice Audio─►│  Goal Celebration Sound │
 └─────────────────────────┘               │  Discord Bot (discord.py)       │               └─────────────────────────┘
                                           └─────────────────────────────────┘
                                                            ▲
                                                            │ GitHub Actions
                                           ┌────────────────┴────────────────┐
                                           │  Live GitHub Pages Web App      │
                                           │  https://ogadassi.github.io     │
                                           │  • 1-Click Discord Invite       │
                                           │  • Custom Sound Test & Upload   │
                                           │  • Live Command List & Stats    │
                                           └─────────────────────────────────┘
```

---

## 🤖 Discord Slash Commands

| Command | Description |
| :--- | :--- |
| `/link` | Generate a private 6-digit code to pair your BakkesMod plugin with Discord. |
| `/upload <file>` | Upload a custom goal celebration sound (auto-normalized to -14 LUFS). |
| `/list` | List all available sounds loaded in the goal soundboard. |
| `/play [name]` | Manually trigger a goal sound in the voice channel. |
| `/join` | Connect RLScoreBot to your current Discord voice channel. |
| `/leave` | Disconnect RLScoreBot from voice channel. |
| `/stats` | Display server goal statistics and play counts. |

---

## 📄 License & Credits

Distributed under the **MIT License**. Created by [ogadassi](https://github.com/ogadassi).
