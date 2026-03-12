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

Run continuously (daily schedule from `.env`):

```bash
python main.py
```

Fast smoke-test mode (lower render cost):

- `VOICE_PROVIDER=silent`
- `DRY_RUN=true`
- `RENDER_WIDTH=640`
- `RENDER_HEIGHT=360`
- `VIDEO_FPS=12`
- `VIDEO_PRESET=ultrafast`

## Production Notes

- Set `DRY_RUN=false` for real YouTube uploads.
- Restore full render settings for production (`1920x1080`, `24 fps`, `medium` or slower preset).
- Keep `assets/stock` filled with short stock clips for more varied visuals.
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
