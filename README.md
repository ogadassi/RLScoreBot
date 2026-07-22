# RLScoreBot - Rocket League Goal Scorer Bot

This is a Python-based Discord bot that watches your Rocket League gameplay and automatically plays a sound effect in your voice channel whenever a goal is scored.

## How It Works

The bot uses **Computer Vision** to "see" what is on your screen.

1.  It periodically takes a screenshot of the top center of your screen (where the score is).
2.  It processes the image to make it easier to read (converting to black and white).
3.  It compares the current score image to the previous one.
4.  If the score changes effectively (meaning a goal happened), it joins your voice channel and plays a random sound file.

## Prerequisites

- Windows OS (Required for `win32gui` screen capture)
- Python 3.8+
- Rocket League (Game must be running in specific resolution, default 1920x1080)
- `ffmpeg` installed and available in the project folder (included)

## Installation

1.  **Install Python Dependencies**:
    Open a terminal in this folder and run:

    ```bash
    pip install -r requirements.txt
    ```

2.  **Discord Bot Setup**:

    - Go to the [Discord Developer Portal](https://discord.com/developers/applications).
    - Create a new Application and add a Bot.
    - Copy the **Token**.
    - Enable **Message Content Intent** in the bot settings.
    - Invite the bot to your server using the OAuth2 URL generator (checking "Bot", "Manage Messages" (for uploads), "Connect", "Speak").

3.  **Configuration**:
    - Create a file named `.env` in this folder.
    - Add your token and owner ID:
      ```env
      DISCORD_TOKEN=your_token_here_do_not_share
      OWNER_ID=your_discord_user_id
      ```

## Usage

### 🚀 Running with Auto-Start (Recommended)
You can configure the bot to automatically monitor Rocket League in the background and launch the bot window only when the game is running.

1. **Register the Watcher**:
   Open a terminal in this folder and run:
   ```bash
   python install_autostart.py
   ```
   This registers `rl_watcher.py` to start silently on Windows login.
2. **How it works**:
   - The watcher runs invisibly in the background.
   - When Rocket League starts, the watcher launches the Discord bot in a visible PowerShell window.
   - When Rocket League closes, the bot gracefully exits.
3. **To uninstall**:
   ```bash
   python install_autostart.py --uninstall
   ```

### 💻 Running Manually
If you want to run the bot manually without the automatic game watcher:
```bash
python RLScoreBot.py
```

## Discord Commands

### 🔊 Voice & Detection
- `>join` — Join your current voice channel and start goal detection.
- `>leave` — Leave the voice channel and stop detection.
- `>play [id]` — Play a random sound or specify an ID from `>list`.
- 🔒 `>restart` — Restart the bot (owner only).

### 🎵 Sound Management
- `>list` — List all loaded sounds with their IDs.
- `>upload <name>` — Upload a new sound (attach audio file: `.mp3`, `.wav`, `.ogg`, `.flac`, `.m4a`) — auto-normalizes.
- 🔒 `>delete <id>` — Delete a sound by its ID (owner only).
- `>refresh` — Reload sounds from disk.
- 🔒 `>normalize` — Normalize all sounds to -14 LUFS (owner only).

### 🛠️ Utilities
- `>commands` / `>cmds` / `>help` — Show the visually pretty command list embed.
- `>stats` — Show play stats, total goals scored, and the top 10 most played sounds leaderboard.
- 🔒 `>status_sync` — Manually trigger an LLM-generated status update from random general chat history (owner only).
- 🔒 `>test` — Run a full self-test of bot systems and report pass/fail status (owner only).

*Note: Commands marked with 🔒 are restricted to the account configured in `OWNER_ID`.*

## Troubleshooting

- **Bot doesn't detect goals**: Ensure Rocket League is running in focus. The bot currently scales to standard resolutions but expects a 16:9 aspect ratio matching 1920x1080 UI layout.
- **FFmpeg error**: Ensure `ffmpeg.exe` is in the project folder.
- **Auto-Start issues**: Run `python install_autostart.py --status` to verify if the watcher is correctly registered in HKCU registry.

## Developer Info
- `rl_watcher.py`: Silent monitor process that spawns the bot console on game start.
- `logger.py`: Provides colorized terminal logging output.
- `score_detector.py`: Computer Vision module using PIL image comparison to detect score progression.

