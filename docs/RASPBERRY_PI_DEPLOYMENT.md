# 🍓 Raspberry Pi 5 Physical Deployment Guide

This guide details deploying **Aether AI Voice Assistant** onto a physical **Raspberry Pi 5** (or Pi 4B 4GB+) with physical microphones, speaker amplifiers, and optional touchscreen displays.

---

## 1. Hardware Requirements

| Component | Recommended Model | Connection Type |
|---|---|---|
| **SBC** | Raspberry Pi 5 (4GB / 8GB) or Pi 4B | USB-C Power (27W) |
| **Microphone** | ReSpeaker USB 4-Mic Array or I2S INMP441 | USB / GPIO (I2S) |
| **Speaker** | MAX98357A I2S DAC Amp + 3W Speaker / 3.5mm AUX | GPIO (I2S) / 3.5mm Jack |
| **Display (Optional)** | 7" Raspberry Pi Touchscreen / HDMI Display | DSI / Micro-HDMI |
| **Storage** | 32GB+ Class 10 MicroSD or NVMe SSD | PCIe / SD Slot |

---

## 2. Operating System & System Dependencies

1. Flash **Raspberry Pi OS (64-bit Bookworm)** via Raspberry Pi Imager.
2. Update system packages and install required audio and build libraries:
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo apt install -y python3-pip python3-venv git alsa-utils libasound2-dev \
                       portaudio19-dev ffmpeg libatlas-base-dev
   ```

---

## 3. Audio Device Configuration (ALSA / I2S)

1. Verify connected audio devices:
   ```bash
   arecord -l   # Lists capture devices (microphones)
   aplay -l     # Lists playback devices (speakers)
   ```
2. Set default card in `~/.asoundrc` or `/etc/asound.conf`:
   ```ini
   pcm.!default {
       type asym
       playback.pcm {
           type plug
           slave.pcm "hw:0,0"   # Change to speaker device number
       }
       capture.pcm {
           type plug
           slave.pcm "hw:1,0"   # Change to mic device number
       }
   }
   ```
3. Test recording and playback:
   ```bash
   # Record a 3-second test clip
   arecord -d 3 -f cd -t wav test.wav
   # Play back the test clip
   aplay test.wav
   ```

---

## 4. Software Installation & Environment

1. Clone repository to `/home/pi/ProductSpeaker`:
   ```bash
   cd /home/pi
   git clone <your-repo-url> ProductSpeaker
   cd ProductSpeaker
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
3. Configure environment variables in `.env`:
   ```bash
   cp .env.example .env
   nano .env
   # Add GEMINI_API_KEY=your_key_here
   ```
4. Set strict file permissions on `.env`:
   ```bash
   chmod 600 .env
   ```

---

## 5. systemd Service (Auto-Start & Restart on Failure)

Create a systemd unit file at `/etc/systemd/system/aether-assistant.service`:
```ini
[Unit]
Description=Aether AI Voice Assistant Daemon
After=network.target sound.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/ProductSpeaker
ExecStart=/home/pi/ProductSpeaker/.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
EnvironmentFile=/home/pi/ProductSpeaker/.env
ProtectSystem=full
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable aether-assistant.service
sudo systemctl start aether-assistant.service
sudo systemctl status aether-assistant.service
```

---

## 6. Optional: Chromium Kiosk Mode for Touchscreens

To automatically boot into the glowing AI orb interface on a physical display:
1. Edit `~/.config/wayfire.ini` or autostart script:
   ```ini
   [autostart]
   screensaver = false
   dpms = false
   kiosk = chromium-browser --kiosk --noerrdialogs --disable-infobars --check-for-update-interval=31536000 http://localhost:8000
   ```
