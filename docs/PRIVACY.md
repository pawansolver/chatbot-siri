# 🔒 Privacy Architecture & Data Protection

This document details the privacy protections engineered into the **Aether AI Voice Assistant**.

---

## 1. Zero Persistent Audio Storage Policy

- **No Permanent Voice Recordings**: Audio streams from microphones are processed in-memory or converted to temporary audio buffers solely for speech transcription.
- **Automated TTL Eviction**: Temporary TTS audio files stored in `backend/temp_audio/` are automatically deleted after 30 minutes.
- **No Background Audio Uploads**: Voice audio is ONLY captured when the user explicitly triggers recording or when a local wake-word is detected.

---

## 2. Telemetry & Log Sanitization

- **No Credential Logging**: `GEMINI_API_KEY`, passwords, and authentication tokens are strictly stripped and never logged to stdout, files, or telemetry.
- **Anonymized Metrics**: Observability metrics measure only numerical latencies (`stt_duration_ms`, `gemini_latency_ms`, `tts_latency_ms`), language type, and model identifiers.
- **Trace ID Correlation**: Traces use random UUIDs (`req_xxxx`) without personally identifiable user data.

---

## 3. Session Isolation & Clear Controls

- **Isolated Sessions**: Conversation histories are partitioned by unique `session_id` tokens.
- **Instant Deletion**: Users can invoke `DELETE /api/history?session_id=...` at any time to permanently erase all conversation turns from server memory.

---

## 4. Third-Party Data Transmission

| Data Item | Destination | Purpose | Storage Duration |
|---|---|---|---|
| User Prompt (Text) | Google Gemini API | Generating conversational response | Subject to Google API Data Policy |
| Spoken Audio Bytes (STT) | Google Speech / Gemini | Audio transcription | Ephemeral processing |
| AI Response (Text) | Microsoft Edge Neural TTS | Synthesizing spoken audio | Ephemeral processing |
