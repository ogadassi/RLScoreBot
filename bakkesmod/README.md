# RLScoreBot BakkesMod Telemetry Plugin

This BakkesMod C++ plugin connects Rocket League to your 24/7 **RLScoreBot** Cloud Instance.

## 🚀 How It Works

1. When you score a goal in any Rocket League match, the plugin catches the `StatGoal` event in memory with **0% CPU/GPU overhead**.
2. It sends an asynchronous HTTP POST request to your cloud bot (`/api/v1/goal`) carrying your 6-digit API pairing token.
3. The bot joins your Discord Voice Channel instantly and plays your **custom uploaded goal anthem**!

## 📥 Installation Guide

1. Make sure [BakkesMod](https://www.bakkesmod.com/) is installed and running.
2. In Discord, type `/link` to generate your private API token.
3. Open Rocket League and press **F2** to open the BakkesMod menu.
4. Go to **Plugins** ➔ **RLScoreBot Client** and paste your API Token.
5. Play Rocket League and enjoy custom goal celebration anthems with your squad!
