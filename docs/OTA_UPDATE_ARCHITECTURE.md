# 🔄 Physical Device Software Update (OTA) Architecture

This document describes the software update strategy for physical **Raspberry Pi 5** AI assistant devices.

---

## 1. Update Lifecycle

```
[Central GitHub Release / Update Server]
                   │
                   ▼ (Check version daily via cron)
       [Raspberry Pi Update Agent]
                   │
                   ▼ (1. Download Signed Package / Git Tag)
          [SHA-256 / GPG Verify]
                   │
                   ▼ (2. Install Virtualenv Dependencies)
          [pip install -r requirements.txt]
                   │
                   ▼ (3. Run Self-Diagnostic Tests)
          [pytest tests/]
                   │
                   ▼ (4. Reload Service)
     [sudo systemctl restart aether-assistant]
```

---

## 2. Safe Fallback & Rollback Mechanism

1. **A/B Slot or Git Branch Rollback**:
   - If `pytest tests/` or health check `/health/live` fails after update, the updater automatically rolls back to the previous stable Git commit / tag.
2. **Health Check Verification**:
   - Before completing update, verify `curl http://localhost:8000/health/ready` returns HTTP 200.
3. **Atomic Symlink Switching**:
   - `/home/pi/aether-current -> /home/pi/releases/v1.1.0`
