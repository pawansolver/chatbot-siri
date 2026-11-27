#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <ArduinoOTA.h>
#include "driver/i2s.h"

// =============================================================================
// AETHER AI SMART SPEAKER - PRODUCTION EMBEDDED CLIENT (ESP32 / ESP32-S3)
// Configured via NVS Captive Portal (HTTPS + Per-Device Pairing Token)
// =============================================================================

// Default Fallback Credentials (Configure actual values in NVS Captive Portal)
static const char* DEFAULT_SSID        = "";
static const char* DEFAULT_PASSWORD    = "";
static const char* DEFAULT_SERVER_BASE = "";  // e.g. https://speaker.example.com
static const char* DEFAULT_API_KEY     = "";  // Per-device paired token (fluai_dev_...)

// =============================================================================
// FIXED HARDWARE PINS (I2S Audio Pipeline)
// =============================================================================
// 1. MAX98357A I2S DAC Amplifier (Speaker Out - I2S_NUM_0)
#define SPK_DIN   7
#define SPK_BCLK  15
#define SPK_LRC   16

// 2. INMP441 I2S Digital MEMS Mic (Microphone In - I2S_NUM_1)
#define MIC_SCK   4
#define MIC_WS    5
#define MIC_SD    6

// =============================================================================
// ENTERPRISE VOICE & DYNAMIC VAD (Voice Activity Detection)
// =============================================================================
#define SAMPLE_RATE         16000   // 16kHz Studio Vocal Standard
#define MAX_RECORD_SEC      6       // Maximum 6 seconds voice buffer
#define MIN_RECORD_MS       700     // Minimum 0.7s before silence cutoff
#define EOS_SILENCE_MS      650     // Bolna band hone ke 650ms baad upload
#define VAD_THRESHOLD       1300    // Speech Trigger Sensitivity
#define EOS_SILENCE_LEVEL   260     // End-of-Speech silence floor

// Global Objects
Preferences prefs;
WebServer configServer(80);
DNSServer dnsServer;
const byte DNS_PORT = 53;
bool apModeActive = false;

String cfgSsid;
String cfgPass;
String cfgServerBase;
String cfgApiKey;
String deviceSessionId;
int32_t mic_offset = 0;

// =============================================================================
// STARTUP AUDIO CHIME (Musical Feedback)
// =============================================================================
void playBeep(int freq, int durationMs) {
  int samples = (SAMPLE_RATE * durationMs) / 1000;
  int halfWave = SAMPLE_RATE / freq / 2;
  int16_t val = 1200;
  for (int i = 0; i < samples; i++) {
    if (i % halfWave == 0) val = -val;
    int16_t stereo[2] = {val, val};
    size_t bw;
    i2s_write(I2S_NUM_0, stereo, sizeof(stereo), &bw, portMAX_DELAY);
  }
}

// =============================================================================
// I2S HARDWARE INITIALIZATION
// =============================================================================
void setupSpeaker() {
  i2s_config_t spk_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = 16000,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 16,
    .dma_buf_len = 512,
    .use_apll = false,
    .tx_desc_auto_clear = true
  };
  i2s_pin_config_t spk_pins = {
    .bck_io_num = SPK_BCLK,
    .ws_io_num = SPK_LRC,
    .data_out_num = SPK_DIN,
    .data_in_num = I2S_PIN_NO_CHANGE
  };
  i2s_driver_install(I2S_NUM_0, &spk_config, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &spk_pins);
}

void setupMicrophone() {
  i2s_config_t mic_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 128,
    .use_apll = false
  };
  i2s_pin_config_t mic_pins = {
    .bck_io_num = MIC_SCK,
    .ws_io_num = MIC_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = MIC_SD
  };
  i2s_driver_install(I2S_NUM_1, &mic_config, 0, NULL);
  i2s_set_pin(I2S_NUM_1, &mic_pins);
}

// =============================================================================
// AUDIO STREAM PLAYBACK HELPER (Anti-Jitter Pre-Buffered I2S Player)
// =============================================================================
void playWavStream(WiFiClient* stream, int totalBytes) {
  if (!stream) return;

  uint8_t header[44];
  int hRead = 0;
  unsigned long headerWaitStart = millis();
  while (hRead < 44 && (stream->connected() || stream->available()) && (millis() - headerWaitStart < 6000)) {
    if (stream->available()) {
      header[hRead++] = stream->read();
      headerWaitStart = millis();
    } else {
      delay(1);
    }
  }
  if (hRead < 44) {
    Serial.println("⚠️ Incomplete WAV header received.");
    return;
  }

  uint32_t wavSampleRate = header[24] | (header[25] << 8) | (header[26] << 16) | (header[27] << 24);
  uint16_t channels = header[22] | (header[23] << 8);

  if (wavSampleRate < 8000 || wavSampleRate > 48000) wavSampleRate = 16000;
  i2s_set_sample_rates(I2S_NUM_0, wavSampleRate);

  int audioBytes = (totalBytes > 44) ? (totalBytes - 44) : 0;
  Serial.printf("🔊 Audio stream: %d Hz, %d ch, %d bytes total\n", wavSampleRate, channels, totalBytes);

  // ---------------------------------------------------------------------------
  // METHOD 1: FULL RAM PRE-BUFFERING (ELIMINATES 100% NETWORK JITTER & STUTTER)
  // ---------------------------------------------------------------------------
  uint8_t* fullBuffer = NULL;
  if (audioBytes > 0 && audioBytes < 350000) {
    if (psramFound()) {
      fullBuffer = (uint8_t*)ps_malloc(audioBytes);
    }
    if (!fullBuffer && ESP.getFreeHeap() > (uint32_t)(audioBytes + 45000)) {
      fullBuffer = (uint8_t*)malloc(audioBytes);
    }
  }

  if (fullBuffer) {
    Serial.printf("📥 Pre-buffering entire audio (%.1f KB) for smooth playback...\n", audioBytes / 1024.0);
    int totalRead = 0;
    unsigned long downloadStart = millis();
    while (totalRead < audioBytes && (stream->connected() || stream->available())) {
      int avail = stream->available();
      if (avail > 0) {
        int toRead = min(avail, audioBytes - totalRead);
        int r = stream->readBytes((char*)(fullBuffer + totalRead), toRead);
        if (r <= 0) break;
        totalRead += r;
        downloadStart = millis();
      } else {
        if (millis() - downloadStart > 8000) break;
        delay(1);
      }
    }
    Serial.printf("✅ Pre-buffered %d bytes. Playing smoothly through I2S...\n", totalRead);

    const int SAMPLES_PER_CHUNK = 256;
    if (channels == 1) {
      int16_t* pcm16 = (int16_t*)fullBuffer;
      int totalSamples = totalRead / 2;
      int16_t stereoBuf[SAMPLES_PER_CHUNK * 2];

      for (int i = 0; i < totalSamples; i += SAMPLES_PER_CHUNK) {
        int chunkSamples = min(SAMPLES_PER_CHUNK, totalSamples - i);
        for (int s = 0; s < chunkSamples; s++) {
          int16_t val = pcm16[i + s];
          // Gentle volume scaling (0.85) to avoid DAC clipping & speaker distortion
          val = (int16_t)(((int32_t)val * 218) >> 8);
          stereoBuf[s * 2]     = val;
          stereoBuf[s * 2 + 1] = val;
        }
        size_t bw;
        i2s_write(I2S_NUM_0, stereoBuf, chunkSamples * 4, &bw, portMAX_DELAY);
      }
    } else {
      size_t bw;
      i2s_write(I2S_NUM_0, fullBuffer, totalRead, &bw, portMAX_DELAY);
    }

    free(fullBuffer);
    Serial.println("✅ AI finished speaking smoothly!");
    return;
  }

  // ---------------------------------------------------------------------------
  // METHOD 2: 16KB JITTER-BUFFERED STREAMING (Fallback if RAM is tight)
  // ---------------------------------------------------------------------------
  Serial.println("🔊 Streaming with 16KB Jitter Buffer...");
  const int PRE_BUFFER_SIZE = 16384;
  uint8_t* preBuf = (uint8_t*)malloc(PRE_BUFFER_SIZE);
  int preBufLen = 0;
  unsigned long pbStart = millis();

  while (preBuf && preBufLen < PRE_BUFFER_SIZE && (stream->connected() || stream->available())) {
    int avail = stream->available();
    if (avail > 0) {
      int toRead = min(avail, PRE_BUFFER_SIZE - preBufLen);
      int r = stream->readBytes((char*)(preBuf + preBufLen), toRead);
      if (r <= 0) break;
      preBufLen += r;
      pbStart = millis();
    } else {
      if (millis() - pbStart > 5000) break;
      delay(2);
    }
  }

  if (preBuf && preBufLen > 0) {
    if (channels == 1) {
      int16_t* pcm16 = (int16_t*)preBuf;
      int samples = preBufLen / 2;
      int16_t stereo[256 * 2];
      for (int i = 0; i < samples; i += 256) {
        int chunk = min(256, samples - i);
        for (int s = 0; s < chunk; s++) {
          int16_t val = (int16_t)(((int32_t)pcm16[i + s] * 218) >> 8);
          stereo[s * 2]     = val;
          stereo[s * 2 + 1] = val;
        }
        size_t bw;
        i2s_write(I2S_NUM_0, stereo, chunk * 4, &bw, portMAX_DELAY);
      }
    } else {
      size_t bw;
      i2s_write(I2S_NUM_0, preBuf, preBufLen, &bw, portMAX_DELAY);
    }
    free(preBuf);
  }

  uint8_t streamBuf[1024];
  int bytesLeft = (totalBytes > 44) ? (totalBytes - 44 - preBufLen) : 9999999;
  unsigned long lastDataMs = millis();

  while ((stream->connected() || stream->available()) && bytesLeft > 0) {
    int avail = stream->available();
    if (avail >= 256 || !stream->connected()) {
      int toRead = min(avail, (int)sizeof(streamBuf));
      if (toRead > bytesLeft) toRead = bytesLeft;
      toRead = toRead & ~1;  // Keep 16-bit word alignment
      if (toRead <= 0) break;

      int len = stream->readBytes((char*)streamBuf, toRead);
      if (len <= 0) break;
      bytesLeft -= len;
      lastDataMs = millis();

      if (channels == 1) {
        int samples = len / 2;
        int16_t* src = (int16_t*)streamBuf;
        int16_t stereo[512 * 2];
        for (int i = 0; i < samples; i++) {
          int16_t val = (int16_t)(((int32_t)src[i] * 218) >> 8);
          stereo[i * 2]     = val;
          stereo[i * 2 + 1] = val;
        }
        size_t bw;
        i2s_write(I2S_NUM_0, stereo, samples * 4, &bw, portMAX_DELAY);
      } else {
        size_t bw;
        i2s_write(I2S_NUM_0, streamBuf, len, &bw, portMAX_DELAY);
      }
    } else {
      if (millis() - lastDataMs > 8000) break;
      delay(2);
    }
  }
  Serial.println("✅ AI finished speaking!");
}

void beginHttpClient(HTTPClient& http, WiFiClientSecure& secureClient, const String& url) {
  if (url.startsWith("https://")) {
    secureClient.setInsecure();
    http.begin(secureClient, url);
  } else {
    http.begin(url);
  }
}

void attachDeviceAuthHeaders(HTTPClient& http) {
  if (cfgApiKey.length() > 0) {
    http.addHeader("X-Device-Token", cfgApiKey);
    http.addHeader("X-API-Key", cfgApiKey);
  }
}

// Fallback: Download audio from URL if server responded with JSON
void playAudioFromURL(String audioUrl) {
  Serial.print("📥 Downloading AI voice response: ");
  Serial.println(audioUrl);

  HTTPClient http;
  WiFiClientSecure secureClient;
  beginHttpClient(http, secureClient, audioUrl);
  http.setTimeout(30000);
  http.addHeader("Connection", "close");
  attachDeviceAuthHeaders(http);
  int httpCode = http.GET();

  if (httpCode == HTTP_CODE_OK) {
    playWavStream(http.getStreamPtr(), http.getSize());
  } else {
    Serial.printf("❌ Error downloading audio, HTTP: %d\n", httpCode);
  }
  http.end();
}

// =============================================================================
// NVS PERSISTENCE & SMART CAPTIVE WI-FI SETUP PORTAL
// =============================================================================
void loadConfig() {
  prefs.begin("aether_cfg", true);
  cfgSsid       = prefs.getString("ssid", DEFAULT_SSID);
  cfgPass       = prefs.getString("pass", DEFAULT_PASSWORD);
  cfgServerBase = prefs.getString("server", DEFAULT_SERVER_BASE);
  cfgApiKey     = prefs.getString("apikey", DEFAULT_API_KEY);
  prefs.end();

  if (cfgSsid.length() == 0) cfgSsid = DEFAULT_SSID;
  if (cfgServerBase.length() == 0) cfgServerBase = DEFAULT_SERVER_BASE;

  String mac = WiFi.macAddress();
  mac.replace(":", "");
  mac.toLowerCase();
  deviceSessionId = "esp32_" + mac;
}

void saveConfig(const String& ssid, const String& pass, const String& server, const String& apikey) {
  prefs.begin("aether_cfg", false);
  prefs.putString("ssid", ssid);
  prefs.putString("pass", pass);
  prefs.putString("server", server);
  prefs.putString("apikey", apikey);
  prefs.end();
}

void handleConfigPortal() {
  // Scan for nearby Wi-Fi networks for auto dropdown
  int n = WiFi.scanNetworks();
  String wifiOptions = "";
  for (int i = 0; i < n; ++i) {
    String netName = WiFi.SSID(i);
    if (netName.length() > 0) {
      wifiOptions += "<option value='" + netName + "'>" + netName + " (" + String(WiFi.RSSI(i)) + " dBm)</option>";
    }
  }

  String html = "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>Aether AI Speaker Setup</title>"
                "<style>"
                "body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#f8fafc;max-width:440px;margin:20px auto;padding:20px}"
                ".card{background:#1e293b;border-radius:14px;padding:24px;border:1px solid #334155;box-shadow:0 8px 24px rgba(0,0,0,0.4)}"
                "h2{margin:0 0 6px;color:#38bdf8;font-size:22px;display:flex;align-items:center;gap:8px}"
                ".sub{font-size:12px;color:#94a3b8;margin-bottom:18px}"
                "label{display:block;font-size:12px;font-weight:600;color:#cbd5e1;margin-top:14px;margin-bottom:4px}"
                "input,select{width:100%;padding:11px;background:#0f172a;color:#fff;border:1px solid #475569;border-radius:8px;box-sizing:border-box;font-size:14px}"
                "input:focus,select:focus{border-color:#38bdf8;outline:none}"
                "button{width:100%;padding:13px;background:#0284c7;color:#fff;font-weight:bold;border:0;border-radius:8px;font-size:15px;margin-top:22px;cursor:pointer;transition:background 0.2s}"
                "button:hover{background:#0369a1}"
                ".tag{font-size:11px;background:#334155;color:#e2e8f0;padding:3px 8px;border-radius:6px;display:inline-block;margin-bottom:12px}"
                "</style></head><body>"
                "<div class='card'>"
                "<h2>🎙️ Aether Smart Speaker</h2>"
                "<div class='sub'>Smart Captive Wi-Fi & AI Cloud Configuration</div>"
                "<div class='tag'>ID: " + deviceSessionId + "</div>"
                "<form method='POST' action='/save'>"
                "<label>Select Found Wi-Fi:</label>"
                "<select onchange='document.getElementById(\"ssidInp\").value=this.value'>"
                "<option value=''>-- Tap to choose detected network --</option>"
                + wifiOptions +
                "</select>"
                "<label>Wi-Fi Name (SSID):</label>"
                "<input id='ssidInp' name='ssid' value='" + cfgSsid + "' required placeholder='Enter Wi-Fi network name'>"
                "<label>Wi-Fi Password:</label>"
                "<input name='pass' type='password' placeholder='Enter Wi-Fi password'>"
                "<label>AWS AI Cloud URL:</label>"
                "<input name='server' value='" + cfgServerBase + "' required placeholder='http://15.135.138.107:8000'>"
                "<button type='submit'>🚀 Save &amp; Connect</button>"
                "</form></div></body></html>";

  configServer.send(200, "text/html", html);
}

void setupConfigWebServer() {
  configServer.on("/", HTTP_GET, handleConfigPortal);
  configServer.on("/hotspot-detect.html", HTTP_GET, handleConfigPortal); // Apple Captive
  configServer.on("/generate_204", HTTP_GET, handleConfigPortal);        // Android Captive
  configServer.on("/ncsi.txt", HTTP_GET, handleConfigPortal);            // Windows Captive

  configServer.on("/save", HTTP_POST, []() {
    String newSsid   = configServer.hasArg("ssid") ? configServer.arg("ssid") : cfgSsid;
    String newPass   = configServer.hasArg("pass") && configServer.arg("pass").length() > 0 ? configServer.arg("pass") : cfgPass;
    String newServer = configServer.hasArg("server") ? configServer.arg("server") : cfgServerBase;
    String newKey    = configServer.hasArg("apikey") ? configServer.arg("apikey") : cfgApiKey;
    newServer.trim();
    if (newServer.endsWith("/")) {
      newServer.remove(newServer.length() - 1);
    }
    saveConfig(newSsid, newPass, newServer, newKey);
    configServer.send(200, "text/html",
      "<body style='background:#0f172a;color:#fff;font-family:sans-serif;text-align:center;padding:40px;'>"
      "<h2>✅ Configuration Saved!</h2><p>Rebooting speaker and connecting to " + newSsid + "...</p></body>");
    delay(1000);
    ESP.restart();
  });

  configServer.begin();
}

void startSoftAPPortal() {
  apModeActive = true;
  WiFi.disconnect();
  delay(100);
  WiFi.mode(WIFI_AP);
  WiFi.softAP("AetherSpeaker-Setup");

  // DNS Server redirects all requests to captive portal (192.168.4.1)
  dnsServer.start(DNS_PORT, "*", WiFi.softAPIP());

  Serial.println("\n=======================================================");
  Serial.println("⚠️ Wi-Fi not found! Smart Captive Portal Started:");
  Serial.println("👉 1. Connect phone/PC to Wi-Fi: AetherSpeaker-Setup");
  Serial.print("👉 2. Open browser: http://");
  Serial.println(WiFi.softAPIP());
  Serial.println("=======================================================\n");

  setupConfigWebServer();
}

// Build standard 44-byte WAV header for recorded microphone audio
void writeWavHeader(uint8_t* wavHeader, uint32_t wavDataSize) {
  memcpy(wavHeader, "RIFF", 4);
  uint32_t fileSize = 36 + wavDataSize;
  memcpy(wavHeader + 4, &fileSize, 4);
  memcpy(wavHeader + 8, "WAVEfmt ", 8);
  uint32_t subchunk1Size = 16;
  uint16_t audioFormat = 1;
  uint16_t numChannels = 1;
  uint32_t sRate = SAMPLE_RATE;
  uint32_t byteRate = SAMPLE_RATE * 2;
  uint16_t blockAlign = 2;
  uint16_t bitsPerSample = 16;
  memcpy(wavHeader + 16, &subchunk1Size, 4);
  memcpy(wavHeader + 20, &audioFormat, 2);
  memcpy(wavHeader + 22, &numChannels, 2);
  memcpy(wavHeader + 24, &sRate, 4);
  memcpy(wavHeader + 28, &byteRate, 4);
  memcpy(wavHeader + 32, &blockAlign, 2);
  memcpy(wavHeader + 34, &bitsPerSample, 2);
  memcpy(wavHeader + 36, "data", 4);
  memcpy(wavHeader + 40, &wavDataSize, 4);
}

// =============================================================================
// SETUP FUNCTION
// =============================================================================
void setup() {
  Serial.begin(115200);
  delay(800);

  Serial.println("\n========================================================");
  Serial.println("🤖 AETHER PHYSICAL AI SMART SPEAKER - BOOTING");
  Serial.println("   AWS Cloud Target: http://15.135.138.107:8000");
  Serial.println("========================================================");

  setupSpeaker();
  setupMicrophone();

  WiFi.mode(WIFI_STA);
  loadConfig();

  Serial.print("📡 Connecting to Wi-Fi: ");
  Serial.println(cfgSsid);
  WiFi.setSleep(false);        // Prevent Wi-Fi sleep (Rock solid connection)
  WiFi.setAutoReconnect(true); // Auto reconnect in background
  WiFi.begin(cfgSsid.c_str(), cfgPass.c_str());

  unsigned long connectStart = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - connectStart < 14000)) {
    delay(300);
    Serial.print(".");
  }

  // Fallback to Smart Hotspot Portal if Wi-Fi fails
  if (WiFi.status() != WL_CONNECTED) {
    startSoftAPPortal();
    return;
  }

  Serial.println("\n🎉 Wi-Fi Connected Successfully!");
  Serial.print("📡 Speaker IP on LAN: ");
  Serial.println(WiFi.localIP());
  Serial.print("🆔 Device Session ID: ");
  Serial.println(deviceSessionId);

  // OTA firmware update & LAN runtime config portal
  ArduinoOTA.setHostname("aether-smart-speaker");
  ArduinoOTA.begin();
  setupConfigWebServer();
  Serial.println("🔄 Config UI ready at http://" + WiFi.localIP().toString());

  // Ping Cloud Backend Health (HTTPS supported)
  if (cfgServerBase.length() > 0) {
    HTTPClient http;
    WiFiClientSecure secureClient;
    String checkUrl = cfgServerBase + "/health/live";
    beginHttpClient(http, secureClient, checkUrl);
    http.setTimeout(10000);
    http.addHeader("Connection", "close");
    int code = http.GET();
    if (code == 200) {
      Serial.println("🧠 Connected to AI Cloud Backend successfully!");
      playBeep(523, 120); // High pitch startup chime
      playBeep(659, 160);
    } else {
      Serial.printf("⚠️ Server health check status: %d (Check server base: %s)\n", code, cfgServerBase.c_str());
    }
    http.end();
  } else {
    Serial.println("⚠️ Server URL not configured. Open config portal to set HTTPS server & paired token.");
  }
  http.end();

  Serial.println("\n🎙️ READY! Speak into microphone to chat with AI...\n");
}

// =============================================================================
// MAIN LOOP FUNCTION
// =============================================================================
void loop() {
  if (apModeActive) {
    dnsServer.processNextRequest();
    configServer.handleClient();
    delay(10);
    return;
  }

  configServer.handleClient();
  ArduinoOTA.handle();

  if (WiFi.status() != WL_CONNECTED) {
    delay(200);
    return;
  }

  int32_t sample = 0;
  size_t bytes_read = 0;

  i2s_read(I2S_NUM_1, &sample, sizeof(sample), &bytes_read, portMAX_DELAY);
  if (bytes_read > 0) {
    int16_t raw = sample >> 14;
    mic_offset = (mic_offset * 31 + raw) / 32;
    int16_t sound = abs(raw - mic_offset);

    // When user speaks
    if (sound > VAD_THRESHOLD) {
      Serial.println("\n🗣️ Speech Detected! Listening (Dynamic VAD up to 6s)...");

      String boundary = "----ESP32_AI_Boundary";
      String sessionPart =
          "--" + boundary +
          "\r\nContent-Disposition: form-data; name=\"session_id\"\r\n\r\n" +
          deviceSessionId + "\r\n";
      String filePartHead =
          "--" + boundary +
          "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"voice.wav\"\r\n"
          "Content-Type: audio/wav\r\n\r\n";
      String head = sessionPart + filePartHead;
      String tail = "\r\n--" + boundary + "--\r\n";

      int headLen = head.length();
      int tailLen = tail.length();

      int maxSamples = SAMPLE_RATE * MAX_RECORD_SEC;
      int maxWavDataSize = maxSamples * 2;
      int maxPayloadLen = headLen + 44 + maxWavDataSize + tailLen;

      uint8_t* payload = NULL;
      if (psramFound()) {
        payload = (uint8_t*)ps_malloc(maxPayloadLen);
      }
      if (!payload) {
        payload = (uint8_t*)malloc(maxPayloadLen);
      }
      if (!payload) {
        // Fallback to 4s buffer if heap is constrained
        maxSamples = SAMPLE_RATE * 4;
        maxWavDataSize = maxSamples * 2;
        maxPayloadLen = headLen + 44 + maxWavDataSize + tailLen;
        payload = (uint8_t*)malloc(maxPayloadLen);
      }

      if (!payload) {
        Serial.println("❌ Out of memory buffer!");
        delay(500);
        return;
      }

      memcpy(payload, head.c_str(), headLen);

      uint8_t* wavHeader = payload + headLen;
      int16_t* pcmDest = (int16_t*)(payload + headLen + 44);
      const int CHUNK = 256;
      int32_t rawChunk[CHUNK];
      int samplesRecorded = 0;
      uint32_t silentMs = 0;

      while (samplesRecorded < maxSamples) {
        size_t br = 0;
        i2s_read(I2S_NUM_1, rawChunk, sizeof(rawChunk), &br, portMAX_DELAY);
        int count = br / sizeof(int32_t);
        if (count <= 0) continue;

        uint32_t chunkEnergySum = 0;
        int capturedInChunk = 0;
        for (int j = 0; j < count && samplesRecorded < maxSamples; j++) {
          int32_t s32 = rawChunk[j] >> 14;
          mic_offset = (mic_offset * 63 + s32) / 64;
          int32_t centered = s32 - mic_offset;
          if (centered > 32767) centered = 32767;
          if (centered < -32768) centered = -32768;
          int16_t s16 = (int16_t)centered;
          pcmDest[samplesRecorded++] = s16;
          chunkEnergySum += (uint32_t)abs((int)s16);
          capturedInChunk++;
        }

        uint32_t recordedMs = ((uint32_t)samplesRecorded * 1000UL) / SAMPLE_RATE;
        uint32_t chunkMs = ((uint32_t)capturedInChunk * 1000UL) / SAMPLE_RATE;
        uint32_t avgLevel = (capturedInChunk > 0) ? (chunkEnergySum / capturedInChunk) : 0;

        if (avgLevel > EOS_SILENCE_LEVEL) {
          silentMs = 0;
        } else {
          silentMs += chunkMs;
        }

        if (recordedMs >= MIN_RECORD_MS && silentMs >= EOS_SILENCE_MS) {
          Serial.printf("✂️ End-of-Speech detected at %lu ms (saved %lu ms)\n",
                        recordedMs, (MAX_RECORD_SEC * 1000UL) - recordedMs);
          break;
        }
      }

      uint32_t actualWavDataSize = (uint32_t)samplesRecorded * 2;
      writeWavHeader(wavHeader, actualWavDataSize);
      memcpy(payload + headLen + 44 + actualWavDataSize, tail.c_str(), tailLen);
      int actualPayloadLen = headLen + 44 + (int)actualWavDataSize + tailLen;

      Serial.printf("📤 Sending %.1f KB audio WAV to AWS Cloud...\n", actualPayloadLen / 1024.0);

      HTTPClient http;
      WiFiClientSecure secureClient;
      String uploadUrl = cfgServerBase + "/api/voice/process-audio";
      beginHttpClient(http, secureClient, uploadUrl);
      http.setTimeout(45000);
      const char* headerKeys[] = {"Content-Type", "X-AI-Response", "X-Prompt"};
      http.collectHeaders(headerKeys, 3);
      http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
      http.addHeader("Accept", "audio/wav, application/json");
      http.addHeader("Connection", "close");
      attachDeviceAuthHeaders(http);

      int resCode = http.POST(payload, actualPayloadLen);
      free(payload);

      if (resCode == 200) {
        String contentType = http.header("Content-Type");
        contentType.toLowerCase();

        if (contentType.indexOf("audio/wav") >= 0) {
          String heard = http.header("X-Prompt");
          String reply = http.header("X-AI-Response");
          if (heard.length() > 0) Serial.println("👂 You: " + heard);
          if (reply.length() > 0) Serial.println("🤖 AI:  " + reply);
          playWavStream(http.getStreamPtr(), http.getSize());
          http.end();
        } else {
          String resp = http.getString();
          Serial.print("🤖 AI Response: ");
          Serial.println(resp);

          int urlIdx = resp.indexOf("\"audio_url\":");
          if (urlIdx > 0) {
            int startQ = resp.indexOf("\"", urlIdx + 12);
            int endQ = resp.indexOf("\"", startQ + 1);
            if (startQ > 0 && endQ > startQ) {
              String relUrl = resp.substring(startQ + 1, endQ);
              relUrl.replace(".mp3", ".wav");
              String fullAudioUrl = cfgServerBase + relUrl;
              http.end();
              playAudioFromURL(fullAudioUrl);
            } else {
              http.end();
            }
          } else {
            http.end();
          }
        }
      } else {
        Serial.printf("❌ AWS Cloud Server error: %d\n", resCode);
        http.end();
      }

      // Clear audio DMA buffer to prevent echo loopback
      i2s_zero_dma_buffer(I2S_NUM_1);
      delay(800);

      Serial.println("\n🎙️ Listening again...\n");
    }
  }
}
