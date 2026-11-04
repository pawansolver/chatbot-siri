# 🛡️ Production Security Architecture & Key Hardening Plan

This document outlines the security architecture for deploying the **Aether AI Voice Assistant** to production on cloud servers, private networks, and physical **Raspberry Pi 5** hardware.

---

## 🔒 1. Core Principle: Zero Client Key Exposure

```
[Web UI / Mobile App]      [Physical Raspberry Pi Client]
          │                               │
          ▼                               ▼
    (JWT / Device Token)            (mTLS / Hardware Token)
          │                               │
          └───────────────┬───────────────┘
                          │ (HTTPS / TLS 1.3)
                          ▼
            ┌───────────────────────────┐
            │   FASTAPI BACKEND CORE    │
            │   • Authenticates Clients │
            │   • Rate Limiting         │
            │   • Payload Sanitization  │
            └─────────────┬─────────────┘
                          │ (Secure Server-to-Server)
                          ▼
               [ Google Gemini API ]
             (API Key Never Leaves Backend)
```

1. **No Frontend Secrets**: Neither web browsers nor client apps ever store or transmit `GEMINI_API_KEY`.
2. **Backend Proxying**: All communication with Google Gemini is handled exclusively by the server-side `GeminiService`.

---

## 🔑 2. Production Secret Management

### A. Cloud Deployment (GCP / AWS / Azure)
Do not store raw `.env` files on production virtual machines. Instead, fetch secrets dynamically at container startup using Cloud KMS / Secret Managers:

- **Google Cloud Platform (GCP)**:
  ```bash
  # Using Google Secret Manager
  gcloud secrets create gemini-api-key --data-file=-
  ```
  ```python
  # backend/config/settings.py production secret fetcher
  from google.cloud import secretmanager

  def fetch_gcp_secret(secret_id: str, project_id: str) -> str:
      client = secretmanager.SecretManagerServiceClient()
      name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
      response = client.access_secret_version(request={"name": name})
      return response.payload.data.decode("UTF-8")
  ```

- **Docker Compose Production Secret Mounting**:
  ```yaml
  services:
    assistant-backend:
      image: aether-assistant:latest
      secrets:
        - gemini_api_key
      environment:
        - GEMINI_API_KEY_FILE=/run/secrets/gemini_api_key
  secrets:
    gemini_api_key:
      external: true
  ```

### B. Physical Raspberry Pi Edge Security
When running on physical hardware:
1. **File System Permissions**:
   ```bash
   chmod 600 /home/pi/ProductSpeaker/.env
   chown pi:pi /home/pi/ProductSpeaker/.env
   ```
2. **Systemd Sandboxing**:
   Run the backend as an isolated systemd service with restricted capabilities (`ProtectSystem=strict`, `NoNewPrivileges=true`).
3. **Encrypted Storage**: Enable LUKS full-disk encryption on the Raspberry Pi's NVMe SSD or MicroSD card to prevent offline extraction of API keys if the physical device is stolen.

---

## 🚦 3. Rate Limiting & Abuse Prevention

Prevent unexpected API billing spikes and denial-of-service:

1. **IP & Session Rate Limiting**:
   - Maximum **20 voice requests per minute** per client.
   - Maximum audio clip length: **15 seconds** (or 2MB audio payload).
   - Maximum text prompt size: **1,000 characters**.
2. **Cost Safeguards in Google Cloud Console**:
   - Set strict monthly budget alerts ($5 / $20 / $50 thresholds).
   - Restrict API key usage in Google Cloud Console to Gemini API endpoints only.

---

## 🌐 4. Transport & Network Hardening

1. **Reverse Proxy with TLS 1.3**:
   Use Caddy or Nginx with automated Let's Encrypt certificates:
   ```nginx
   server {
       listen 443 ssl http2;
       server_name assistant.yourdomain.com;

       ssl_certificate /etc/letsencrypt/live/yourdomain/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/yourdomain/privkey.pem;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-Proto https;
       }
   }
   ```
2. **CORS Restriction**:
   In `backend/main.py`, lock `allow_origins` to your production domain rather than `["*"]`:
   ```python
   app.add_middleware(
       CORSMiddleware,
       allow_origins=["https://assistant.yourdomain.com"],
       allow_credentials=True,
       allow_methods=["GET", "POST", "DELETE"],
       allow_headers=["*"],
   )
   ```

---

## 📋 5. Security Checklist Before Going Live

- [ ] `GEMINI_API_KEY` is added to `.gitignore` and never committed to Git.
- [ ] API Key restricted in Google AI Studio / GCP Console.
- [ ] HTTPS / WSS configured via Reverse Proxy.
- [ ] Input payload lengths sanitized and validated via Pydantic.
- [ ] Temporary audio files cleaned automatically via TTL eviction.
- [ ] Monthly budget cap configured in Google Cloud Billing.
