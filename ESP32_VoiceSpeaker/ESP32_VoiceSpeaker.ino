#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WebServer.h>
#include <ArduinoOTA.h>
#include "driver/i2s.h"

// =============================================================================
// DEFAULT FALLBACK CREDENTIALS (Auto-saved/overridable via NVS Web Portal)
// =============================================================================
static const char* DEFAULT_SSID        = "Arvind";
static const char* DEFAULT_PASSWORD    = "G7654321";
static const char* DEFAULT_SERVER_BASE = "http://192.168.31.15:8000";
static const char* DEFAULT_API_KEY     = "";  // Optional: must match DEVICE_API_KEY in .env if set

// =============================================================================
// FIXED HARDWARE PINS (DO NOT CHANGE)
// =============================================================================
// स्पीकर पिन (I2S_NUM_0)
#define SPK_DIN   7
#define SPK_BCLK  15
#define SPK_LRC   16

// माइक पिन (I2S_NUM_1)
#define MIC_SCK   4
#define MIC_WS    5
#define MIC_SD    6

// =============================================================================
// ENTERPRISE VOICE & DYNAMIC VAD SETTINGS
// =============================================================================
#define SAMPLE_RATE         16000
#define MAX_RECORD_SEC      5       // अधिकतम 5 सेकंड रिकॉर्डिंग (लंबे सवालों के लिए)
#define MIN_RECORD_MS       700     // कम से कम 0.7 सेकंड रिकॉर्डिंग
#define EOS_SILENCE_MS      650     // बोलना बंद होने के 650ms बाद तुरंत अपलोड (Dynamic End-of-Speech)
#define VAD_THRESHOLD       1300    // वेक-स्पीच सेंसिटिविटी
#define EOS_SILENCE_LEVEL   260     // End-of-speech चंक औसत साइलेंस थ्रेशोल्ड

Preferences prefs;
WebServer configServer(80);
bool apModeActive = false;

String cfgSsid;
String cfgPass;
String cfgServerBase;
String cfgApiKey;
String deviceSessionId;

int32_t mic_offset = 0;

// स्टार्टअप चाइम फंक्शन
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

// I2S स्पीकर सेटअप (FIXED PINS: DIN=7, BCLK=15, LRC=16)
void setupSpeaker() {
  i2s_config_t spk_config = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate = 24000,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = 128,
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

// I2S माइक सेटअप (FIXED PINS: SCK=4, WS=5, SD=6)
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

// 44-बाइट WAV स्ट्रीम को सीधे I2S स्पीकर पर बजाना (Shared Helper)
void playWavStream(WiFiClient* stream, int totalBytes) {
  if (!stream) return;

  uint8_t header[44];
  int hRead = 0;
  unsigned long headerWaitStart = millis();
  while (hRead < 44 && (stream->connected() || stream->available()) && (millis() - headerWaitStart < 5000)) {
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

  Serial.printf("🔊 Playing on speaker (Rate: %d Hz, Channels: %d, Bytes: %d)...\n", wavSampleRate, channels, totalBytes);

  uint8_t buffer[512];
  int bytesLeft = (totalBytes > 44) ? (totalBytes - 44) : 9999999;
  unsigned long lastDataMs = millis();

  while ((stream->connected() || stream->available()) && bytesLeft > 0) {
    int avail = stream->available();
    if (avail > 0) {
      int toRead = avail > (int)sizeof(buffer) ? (int)sizeof(buffer) : avail;
      if (toRead > bytesLeft) toRead = bytesLeft;
      int len = stream->readBytes((char*)buffer, toRead);
      if (len <= 0) break;
      bytesLeft -= len;
      lastDataMs = millis();

      if (channels == 1) {
        int samples = len / 2;
        int16_t* src = (int16_t*)buffer;
        int16_t stereo[256 * 2];
        for (int i = 0; i < samples && i < 256; i++) {
          stereo[i * 2] = src[i];
          stereo[i * 2 + 1] = src[i];
        }
        size_t bw;
        i2s_write(I2S_NUM_0, stereo, samples * 4, &bw, portMAX_DELAY);
      } else {
        size_t bw;
        i2s_write(I2S_NUM_0, buffer, len, &bw, portMAX_DELAY);
      }
    } else {
      if (millis() - lastDataMs > 8000) {
        Serial.println("⚠️ Audio stream timeout.");
        break;
      }
      delay(2);
    }
  }
  Serial.println("✅ AI finished speaking!");
}

// JSON fallback केस में URL से WAV डाउनलोड कर बजाना
void playAudioFromURL(String audioUrl) {
  Serial.print("📥 Downloading AI voice response: ");
  Serial.println(audioUrl);

  HTTPClient http;
  http.begin(audioUrl);
  http.setTimeout(30000);
  http.addHeader("Connection", "close");
  if (cfgApiKey.length() > 0) {
    http.addHeader("X-API-Key", cfgApiKey);
  }
  int httpCode = http.GET();

  if (httpCode == HTTP_CODE_OK) {
    playWavStream(http.getStreamPtr(), http.getSize());
  } else {
    Serial.printf("❌ Error downloading audio, HTTP: %d\n", httpCode);
  }
  http.end();
}

// =============================================================================
// NVS PERSISTENT CONFIG & WEB PORTAL (SoftAP Fallback + LAN Runtime Settings)
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

void setupConfigWebServer() {
  configServer.on("/", HTTP_GET, []() {
    String html = "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
                  "<title>Aether Speaker Setup</title>"
                  "<style>body{font-family:sans-serif;max-width:420px;margin:24px auto;padding:16px}"
                  "input{width:100%;padding:8px;margin:6px 0 14px;box-sizing:border-box}"
                  "button{padding:10px 18px;background:#111;color:#fff;border:0;border-radius:6px;cursor:pointer}</style></head><body>"
                  "<h2>Aether AI Speaker Settings</h2>"
                  "<p><b>Device Session ID:</b> " + deviceSessionId + "</p>"
                  "<form method='POST' action='/save'>"
                  "Wi-Fi SSID:<input name='ssid' value='" + cfgSsid + "' required>"
                  "Wi-Fi Password:<input name='pass' type='password' placeholder='Leave unchanged if empty'>"
                  "AI Server URL:<input name='server' value='" + cfgServerBase + "' required>"
                  "Device API Key (Optional):<input name='apikey' value='" + cfgApiKey + "'>"
                  "<button type='submit'>Save &amp; Reboot</button></form></body></html>";
    configServer.send(200, "text/html", html);
  });

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
    configServer.send(200, "text/html", "<h3>Saved! Rebooting speaker now...</h3>");
    delay(800);
    ESP.restart();
  });

  configServer.begin();
}

void startSoftAPPortal() {
  apModeActive = true;
  WiFi.mode(WIFI_AP);
  WiFi.softAP("AetherSpeaker-Setup");
  Serial.println("\n⚠️ Wi-Fi failed! SoftAP Config Portal started:");
  Serial.println("👉 Connect phone/PC to Wi-Fi: AetherSpeaker-Setup");
  Serial.print("👉 Open browser: http://");
  Serial.println(WiFi.softAPIP());
  setupConfigWebServer();
}

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

void setup() {
  Serial.begin(115200);
  delay(800);

  Serial.println("\n==========================================");
  Serial.println("🤖 ENTERPRISE AI VOICE ASSISTANT - BOOTING");
  Serial.println("==========================================");

  setupSpeaker();
  setupMicrophone();

  WiFi.mode(WIFI_STA);
  loadConfig();

  Serial.print("Connecting to Wi-Fi: ");
  Serial.println(cfgSsid);
  WiFi.setSleep(false);        // Wi-Fi स्लीप बंद (रॉक-सॉलिड कनेक्शन)
  WiFi.setAutoReconnect(true); // बैकग्राउंड में ऑटो री-कनेक्ट चालू
  WiFi.begin(cfgSsid.c_str(), cfgPass.c_str());

  unsigned long connectStart = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - connectStart < 15000)) {
    delay(300);
    Serial.print(".");
  }

  if (WiFi.status() != WL_CONNECTED) {
    startSoftAPPortal();
    return;
  }

  Serial.println("\n🎉 Wi-Fi Connected!");
  Serial.print("📡 Speaker IP: ");
  Serial.println(WiFi.localIP());
  Serial.print("🆔 Device Session ID: ");
  Serial.println(deviceSessionId);

  // Over-The-Air (OTA) Firmware Update + LAN Settings Portal
  ArduinoOTA.setHostname("aether-voice-speaker");
  ArduinoOTA.begin();
  setupConfigWebServer();
  Serial.println("🔄 ArduinoOTA & Config UI ready at http://" + WiFi.localIP().toString());

  // AI सर्वर पिंग करना
  HTTPClient http;
  String checkUrl = cfgServerBase + "/health/live";
  http.begin(checkUrl);
  http.setTimeout(10000);
  http.addHeader("Connection", "close");
  int code = http.GET();
  if (code == 200) {
    Serial.println("🧠 Connected to AI Backend successfully!");
    playBeep(523, 120);
    playBeep(659, 160);
  } else {
    Serial.printf("⚠️ Server health check failed (%d), check IP: %s\n", code, cfgServerBase.c_str());
  }
  http.end();

  Serial.println("\n🎙️ READY! Speak into the mic to talk with AI...\n");
}

void loop() {
  configServer.handleClient();
  if (apModeActive) {
    delay(10);
    return;
  }

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

    // अगर यूज़र ने बोलना शुरू किया
    if (sound > VAD_THRESHOLD) {
      Serial.println("\n🗣️ Speech Detected! Listening (Dynamic VAD up to 5s)...");

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
        // Fallback to 4s buffer if heap without PSRAM is tight
        maxSamples = SAMPLE_RATE * 4;
        maxWavDataSize = maxSamples * 2;
        maxPayloadLen = headLen + 44 + maxWavDataSize + tailLen;
        payload = (uint8_t*)malloc(maxPayloadLen);
      }

      if (!payload) {
        Serial.println("❌ Out of memory!");
        delay(500);
        return;
      }

      // मल्टीपार्ट हेडर कॉपी करना
      memcpy(payload, head.c_str(), headLen);

      // माइक से 256 सैंपल्स के चंक में साफ़ रिकॉर्डिंग + Dynamic End-of-Speech VAD
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

      Serial.printf("📤 Sending %.1f KB WAV (Session: %s)...\n",
                    actualPayloadLen / 1024.0, deviceSessionId.c_str());

      HTTPClient http;
      String uploadUrl = cfgServerBase + "/api/voice/process-audio";
      http.begin(uploadUrl);
      http.setTimeout(45000);
      const char* headerKeys[] = {"Content-Type", "X-AI-Response", "X-Prompt"};
      http.collectHeaders(headerKeys, 3);
      http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
      http.addHeader("Accept", "audio/wav, application/json");
      http.addHeader("Connection", "close");
      if (cfgApiKey.length() > 0) {
        http.addHeader("X-API-Key", cfgApiKey);
      }

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
        Serial.printf("❌ Server error: %d\n", resCode);
        http.end();
      }

      // स्पीकर का इको साफ़ करने के लिए बफ़र क्लियर और छोटा पॉज़
      i2s_zero_dma_buffer(I2S_NUM_1);
      delay(900);

      Serial.println("\n🎙️ Listening again...\n");
    }
  }
}
