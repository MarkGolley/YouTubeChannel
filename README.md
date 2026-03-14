# Automated Faceless YouTube Pipeline

This project generates and uploads fact-style YouTube videos automatically on a schedule.

## Pipeline

1. Generate topic (`topic_generator.py`)
2. Generate script + metadata (`script_generator.py`)
3. Generate narration (`voice_generator.py`)
4. Build video (`video_builder.py`)
5. Generate thumbnail (`thumbnail_generator.py`)
6. Upload and schedule on YouTube (`youtube_uploader.py`)
7. Repeat on schedule (`scheduler.py`)

## Setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy config template and edit:
   ```bash
   cp .env.example .env
   ```
4. Add YouTube OAuth desktop client JSON to `secrets/client_secret.json`.
5. Install system FFmpeg and confirm it is available in PATH.

## Run

Run once:

```bash
python main.py --once
```

Run once in fast draft mode:

```bash
python main.py --once --draft
```

Run once in production mode:

```bash
python main.py --once --production
```

Check pending checkpoint status:

```bash
python main.py --status
```

Run once and force resume from pending checkpoint:

```bash
python main.py --once --resume
```

Run once and ignore pending checkpoint:

```bash
python main.py --once --fresh
```

Run continuously (daily schedule from `.env`):

```bash
python main.py
```

Fast smoke-test mode (lower render cost):

- `VOICE_PROVIDER=silent`
- `DRY_RUN=true`
- `RUN_PROFILE=draft`

Quality mode switch:

- `RUN_PROFILE=draft` for fast iteration
- `RUN_PROFILE=production` for final output
- CLI flags override env: `--draft` or `--production`
- On-screen text overlay is off by default (`VIDEO_OVERLAY_TEXT_ENABLED=false`)
- Branded spoken intro is enabled by default via `CHANNEL_INTRO_TEXT`

## Stock Footage Folder (`assets/stock`)

- This app uses stock clips as visual B-roll behind narration.
- If the folder is empty, it falls back to generated backgrounds only.
- If `PEXELS_API_KEY` is set and `AUTO_FETCH_STOCK=true`, the app auto-downloads topic-specific stock media from Pexels before render.
- Topic assets are stored under `assets/stock/topics/<topic-slug>` and are prioritized for that video.
- Add royalty-safe clips to `assets/stock` in `.mp4`, `.mov`, or `.mkv`.
- You can also add still images in `.jpg`, `.jpeg`, `.png`, `.webp` (app applies motion zoom).
- Best results:
  - 16:9 aspect ratio
  - 1080p
  - 5 to 20 seconds per clip
  - 20+ mixed clips (space, ocean, nature, labs, maps, time-lapse)
- Keep only clips you have rights to use on YouTube.

## Production Notes

- Set `DRY_RUN=false` for real YouTube uploads.
- Restore full render settings for production (`1920x1080`, `24 fps`, `medium` or slower preset).
- Add `PEXELS_API_KEY` in `.env` to let the app maintain stock library automatically.
- On first real upload, OAuth browser login is required to create `secrets/token.json`.
- Logs are written to `logs/automation.log`.

## Continuous Server Run

### Linux systemd example

Create `/etc/systemd/system/youtube-automation.service`:

```ini
[Unit]
Description=Automated YouTube Pipeline
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/youtube-channel
ExecStart=/opt/youtube-channel/.venv/bin/python /opt/youtube-channel/main.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable youtube-automation
sudo systemctl start youtube-automation
sudo systemctl status youtube-automation
```

### Windows Task Scheduler

- Trigger: At startup
- Action: `python.exe C:\path\to\project\main.py`
- Start in: project folder
- Configure to restart on failure.
