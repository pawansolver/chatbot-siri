# 🎙️ Aether AI — Neural Voice Assistant (Production Prototype)

An end-to-end, ultra-responsive **AI Voice Assistant** built in Python with **FastAPI**, **Google Gemini AI**, **Microsoft Edge Neural TTS**, and a state-reactive **Animated AI Orb Web Interface**.

Engineered for **Windows** software prototype testing and designed for zero-friction migration to a **Raspberry Pi 5** physical hardware appliance.

---

## ⚡ Assistant Architecture & Pipeline

```text
🎤 USER SPEECH (English / Hindi / Hinglish)
      ↓
[Audio Normalizer] (WAV / WebM / MP3 validation)
      ↓
[Replaceable STT: Google / Gemini / Whisper]
      ↓
[Local Command Router] (backend/core/command_router.py)
   /             \
  /               \
[Local Action]     [AI Request with Generation ID]
(Stop/Mute/Vol)    (backend/core/assistant.py)
                   │
                   ▼
          [Assistant Core] (Session Isolation & Barge-in Guard)
                   │
                   ▼
          [Google Gemini API] (gemini-2.5-flash / 1.5-pro)
                   │
                   ▼ (Future MCP Tool Routing)
          [Multilingual Neural TTS] (hi-IN-Swara / en-IN-Neerja / en-US-Ava)
                   │
                   ▼
          [AudioPlaybackManager] (Single Active Playback Invariant)
                   │
                   ▼
          🔊 SPEAKER AUDIO OUTPUT
```

---

## 🌟 Key Production Invariants & Features

### 1. 🛡️ Safe Cancellation & Generation IDs
Every assistant request is stamped with `request_id`, `session_id`, and an incremental `generation_id` (e.g. `gen_1`, `gen_2`).
- When a user interrupts the assistant or speaks a new prompt, a new `generation_id` is created, and the prior generation is **strictly invalidated**.
- Any delayed response or audio from a stale generation is **discarded** and can never update the conversation history, UI, or audio player.

### 2. ⚡ Deterministic Local Command Router
Commands are executed instantly on the device without making unnecessary Gemini API calls:
- **Playback**: `stop`, `cancel`, `pause`, `resume`, `रुको`, `बंद करो`, `ruko`, `chup ho jao`
- **Volume & Mute**: `mute`, `unmute`, `volume up`, `volume down`, `आवाज़ बंद करो`, `आवाज़ बढ़ाओ`, `awaaz badhao`
- **Session**: `clear history`, `status`, `इतिहास साफ़ करो`
- *Normal questions* containing command words (e.g. *"What is stop codon?"*) are safely routed to Gemini.

### 3. 🍓 Physical Device State vs Assistant State Separation
- **AssistantState**: Conversational state (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING`, `ERROR`).
- **DeviceState**: Physical hardware state (`BOOTING`, `INITIALIZING`, `READY`, `OFFLINE`, `ERROR`, `SHUTDOWN`).
- Monitored independently via `/health/ready` and `GET /api/device/state`.

### 4. 🔊 Single Active Audio Playback Invariant
`AudioPlaybackManager` enforces that only one audio response can play at any moment. Starting new audio or triggering barge-in immediately purges previous audio.

---

## 🚀 Quick Start on Windows

### 1. Prerequisites
- **Python 3.11+** installed.
- Microphone and speakers connected.

### 2. Configure `.env`
```bash
copy .env.example .env
```
Open `.env` and configure your **Google Gemini API Key**:
```ini
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
LANGUAGE_MODE=auto
STT_ENGINE=google
```

### 3. Run Automated Tests
```bash
python -m pytest tests/ -v
# 21 passed
```

### 4. Launch Assistant Server
```bash
python backend/main.py
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in Chrome or Edge.

---

## 🎤 Manual Verification & Barge-In Test on Windows

1. **Microphone Voice Test**:
   - Tap **🎤 TAP TO SPEAK** (or press `Spacebar`).
   - Ask: *"Hello, who are you?"*
   - Observe: State changes `IDLE` ➔ `LISTENING` ➔ `THINKING` ➔ `SPEAKING` (with neural audio output) ➔ `IDLE`.
2. **Multilingual Test**:
   - Hindi: *"नमस्ते, आप क्या कर सकते हैं?"* (Answered in Hindi with `hi-IN-SwaraNeural`).
   - Hinglish: *"Aapka naam kya hai aur weather kaisa hai?"* (Answered in Hinglish with `en-IN-NeerjaNeural`).
3. **Barge-In / Interruption Test**:
   - Ask: *"Tell me a long story about space exploration."*
   - While the assistant is actively speaking, click **🎤 TAP TO SPEAK** or press `Spacebar`.
   - **Result**: Speech immediately cuts off, the old generation is invalidated, state switches to `LISTENING`, and your new command is processed without overlapping audio.
4. **Local Command Test**:
   - Say: *"Volume up"* or *"रुको"* or *"Mute"*.
   - **Result**: Handled instantly on the local device without invoking Gemini.

---

## 🍓 Raspberry Pi 5 Hardware Migration

The software architecture is decoupled from the host OS:
- **Windows**: `WindowsAudioAdapter` connects to browser audio / DirectSound.
- **Raspberry Pi 5**: `RaspberryPiAudioAdapter` connects to ALSA / I2S microphones and MAX98357A DAC amplifiers.

See full instructions in:
- [RASPBERRY_PI_DEPLOYMENT.md](file:///c:/ProductSpeaker/docs/RASPBERRY_PI_DEPLOYMENT.md)
- [SECURITY.md](file:///c:/ProductSpeaker/SECURITY.md)
- [PRIVACY.md](file:///c:/ProductSpeaker/docs/PRIVACY.md)
- [MCP_INTEGRATION.md](file:///c:/ProductSpeaker/docs/MCP_INTEGRATION.md)
- [OTA_UPDATE_ARCHITECTURE.md](file:///c:/ProductSpeaker/docs/OTA_UPDATE_ARCHITECTURE.md)
