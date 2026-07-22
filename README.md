# ⚡ RLScoreBot — Custom Goal Anthems for Rocket League

[![Release](https://img.shields.io/badge/release-v2.0.0--cloud-00f0ff.svg)](https://github.com/ogadassi/RLScoreBot/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-orange.svg)](LICENSE)
[![Discord API](https://img.shields.io/badge/Discord-Slash%20Commands-5865F2.svg)](https://discord.com/developers/docs)
[![BakkesMod](https://img.shields.io/badge/BakkesMod-Telemetry-green.svg)](https://www.bakkesmod.com/)

**RLScoreBot** is a 24/7 Cloud-Hosted Discord Bot & 2026 Web Application that plays **custom uploaded goal celebration anthems** in your Discord Voice Channel whenever you score in Rocket League!

> 📜 **Looking for the legacy v1.0 Standalone Desktop version (Computer Vision / PyWin32)?**  
> Check out the [v1.0.0-desktop Release](https://github.com/ogadassi/RLScoreBot/releases/tag/v1.0.0-desktop) or switch to the [`legacy/desktop-cv`](https://github.com/ogadassi/RLScoreBot/tree/legacy/desktop-cv) branch.

---

## 🚀 Key Features

* 🎵 **User-Uploaded Custom Anthems**: Every player can upload their own custom sound clips (`/upload`). When **Player A** scores, **Player A's custom anthem** plays! When **Player B** scores, **Player B's custom anthem** plays!
* 🎚️ **-14 LUFS Audio Normalization Engine**: Every user-uploaded sound file (`.mp3`, `.wav`, `.ogg`, `.flac`) is automatically processed with `ffmpeg` to match standard broadcasting loudness (-14 LUFS).
* 🔌 **Zero-Friction BakkesMod Telemetry**: A silent C++ BakkesMod plugin catches goal events in Rocket League memory with **0% CPU/GPU overhead** and pings the cloud bot.
* 🌐 **2026 Gaming Web Application**: Embedded web interface featuring an interactive soundboard preview, command search explorer, and 1-click Discord invite generator.
* 🐳 **Docker & Cloud Ready**: Fully containerized with `Dockerfile` and `docker-compose.yml` for 1-click deployment on free cloud tiers (Oracle Cloud, Koyeb, Render).

---

## 🏗️ System Architecture

```
 ┌─────────────────────────┐               ┌─────────────────────────────────┐               ┌─────────────────────────┐
 │   Gamer's PC (RL)       │               │      Cloud Server (24/7)        │               │   Friends' Discord VC   │
 │                         │               │                                 │               │                         │
 │  BakkesMod Plugin       │──HTTP Webhook─►  FastAPI / aiohttp Web Endpoint  │               │  Bot joins VC & plays   │
 │  (Detects Goal Event)   │   (/api/goal) │                │                │──Voice Audio─►│  Player's Custom Anthem │
 └─────────────────────────┘               │  Discord Bot (discord.py)       │               └─────────────────────────┘
                                           └─────────────────────────────────┘
                                                            ▲
                                                            │ Serves Web App
                                           ┌────────────────┴────────────────┐
                                           │  2026 Gaming Website / Landing  │
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
| `/upload <file>` | Upload a custom goal celebration anthem (auto-normalized to -14 LUFS). |
| `/sound [name]` | Set your active goal anthem from your uploaded library or default starters. |
| `/my_sounds` | List all custom goal anthems uploaded by you. |
| `/join` | Connect RLScoreBot to your current Discord voice channel. |
| `/leave` | Disconnect RLScoreBot from voice channel. |
| `/stats` | Display server goal leaderboards and play counts. |

---

## ⚡ Quick Setup Guide

1. **Add Bot to Discord**: Click the 1-click invite link on the website or Developer Portal.
2. **Pair Game**: Type `/link` in Discord to get your 6-digit code. Paste it into the BakkesMod plugin settings (**F2** menu in Rocket League).
3. **Upload Your Anthem**: Attach a sound clip using `/upload <file>` and set it with `/sound`.
4. **Score & Celebrate!** Join a voice channel with `/join` and play Rocket League!

---

## 🐳 Self-Hosting with Docker

```bash
# 1. Clone the repository
git clone https://github.com/ogadassi/RLScoreBot.git
cd RLScoreBot

# 2. Configure environment
cp .env.example .env
# Edit .env with your DISCORD_TOKEN and OWNER_ID

# 3. Launch Docker Container
docker-compose up -d
```

---

## 📄 License & Credits

Distributed under the **MIT License**. Created by [ogadassi](https://github.com/ogadassi).
