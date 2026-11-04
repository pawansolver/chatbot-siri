/**
 * AETHER AI - Neural Voice Assistant Client Controller (World-Class Production Edition)
 * Invariants & Features:
 *  - Real-time Starfield Particle Engine
 *  - AudioPlaybackManager (Single active playback invariant)
 *  - Dynamic 360-degree Frequency Waveform Visualizer
 *  - Latency HUD (STT / Gemini AI / TTS latency tracking)
 *  - Barge-In Interruption via Spacebar or Orb Click
 *  - Interactive Suggestion Prompt Chips
 *  - Local Command Router Instant Execution
 *  - Isolated Session Memory
 */

class AudioPlaybackManager {
  constructor(audioElement, onStateChange) {
    this.audio = audioElement;
    this.onStateChange = onStateChange;
    this.isPlaying = false;
    this.currentUrl = null;
    this.currentGenerationId = null;

    this.audio.addEventListener('play', () => {
      this.isPlaying = true;
      this.onStateChange('SPEAKING');
    });

    this.audio.addEventListener('ended', () => {
      this.isPlaying = false;
      this.currentGenerationId = null;
      this.onStateChange('IDLE');
    });

    this.audio.addEventListener('error', (err) => {
      console.warn('[AudioPlaybackManager] Playback error:', err);
      this.isPlaying = false;
      this.currentGenerationId = null;
      this.onStateChange('IDLE');
    });
  }

  play(url, generationId = null) {
    this.stop(false);
    this.currentUrl = url;
    this.currentGenerationId = generationId;
    this.audio.src = url;

    return this.audio.play().catch((err) => {
      console.warn('[AudioPlaybackManager] Autoplay prevented or failed:', err);
      this.onStateChange('IDLE');
    });
  }

  stop(isBargeIn = false) {
    if (this.audio) {
      this.audio.pause();
      this.audio.currentTime = 0;
    }
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    this.isPlaying = false;
    this.currentGenerationId = null;

    if (isBargeIn) {
      this.onStateChange('LISTENING');
    } else {
      this.onStateChange('IDLE');
    }
  }

  setVolume(delta) {
    if (this.audio) {
      this.audio.volume = Math.max(0, Math.min(1, this.audio.volume + delta));
      console.log(`[AudioPlaybackManager] Volume: ${Math.round(this.audio.volume * 100)}%`);
    }
  }

  setMute(mute = true) {
    if (this.audio) {
      this.audio.muted = mute;
      console.log(`[AudioPlaybackManager] Mute: ${mute}`);
    }
  }
}

class ParticleSystem {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas ? canvas.getContext('2d') : null;
    this.particles = [];
    this.count = 45;
    this.animationFrame = null;

    if (this.ctx) {
      this.resize();
      this.initParticles();
      window.addEventListener('resize', () => this.resize());
      this.animate();
    }
  }

  resize() {
    this.canvas.width = window.innerWidth;
    this.canvas.height = window.innerHeight;
  }

  initParticles() {
    this.particles = [];
    for (let i = 0; i < this.count; i++) {
      this.particles.push({
        x: Math.random() * this.canvas.width,
        y: Math.random() * this.canvas.height,
        size: Math.random() * 2 + 0.5,
        speedX: (Math.random() - 0.5) * 0.4,
        speedY: (Math.random() - 0.5) * 0.4,
        opacity: Math.random() * 0.6 + 0.2,
        color: Math.random() > 0.5 ? 'rgba(0, 240, 255,' : 'rgba(139, 92, 246,',
      });
    }
  }

  animate() {
    if (!this.ctx) return;
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    for (let p of this.particles) {
      p.x += p.speedX;
      p.y += p.speedY;

      if (p.x < 0) p.x = this.canvas.width;
      if (p.x > this.canvas.width) p.x = 0;
      if (p.y < 0) p.y = this.canvas.height;
      if (p.y > this.canvas.height) p.y = 0;

      this.ctx.beginPath();
      this.ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
      this.ctx.fillStyle = `${p.color} ${p.opacity})`;
      this.ctx.fill();
    }

    this.animationFrame = requestAnimationFrame(() => this.animate());
  }
}

class VoiceAssistantApp {
  constructor() {
    this.state = 'IDLE'; // IDLE | LISTENING | THINKING | SPEAKING | ERROR
    this.deviceState = 'READY';
    this.isRecording = false;
    this.currentAudioUrl = null;
    this.hasApiKey = false;

    // Session and Generation Tracking
    this.sessionId = this.getOrCreateSessionId();
    this.generationCounter = 0;
    this.activeGenerationId = 'gen_0';

    // DOM Elements
    this.aiOrb = document.getElementById('aiOrb');
    this.stateBadge = document.getElementById('stateBadge');
    this.stateText = document.getElementById('stateText');
    this.statusPill = document.getElementById('statusPill');
    this.statusText = document.getElementById('statusText');
    this.devicePill = document.getElementById('devicePill');
    this.deviceText = document.getElementById('deviceText');
    this.latencyHud = document.getElementById('latencyHud');
    this.hudStt = document.getElementById('hudStt');
    this.hudGemini = document.getElementById('hudGemini');
    this.hudTts = document.getElementById('hudTts');
    this.detectedLangTag = document.getElementById('detectedLangTag');
    this.currentSessionLabel = document.getElementById('currentSessionLabel');

    this.alertBanner = document.getElementById('alertBanner');
    this.alertMessage = document.getElementById('alertMessage');
    this.dismissAlertBtn = document.getElementById('dismissAlertBtn');

    this.modelSelector = document.getElementById('modelSelector');
    this.langSelector = document.getElementById('langSelector');

    this.micBtn = document.getElementById('micBtn');
    this.micLabel = document.getElementById('micLabel');
    this.textChatForm = document.getElementById('textChatForm');
    this.textInput = document.getElementById('textInput');
    this.sendTextBtn = document.getElementById('sendTextBtn');

    this.liveTranscriptBox = document.getElementById('liveTranscriptBox');
    this.liveTranscriptText = document.getElementById('liveTranscriptText');
    this.aiResponseText = document.getElementById('aiResponseText');
    this.replayAudioBtn = document.getElementById('replayAudioBtn');
    this.copyResponseBtn = document.getElementById('copyResponseBtn');
    this.promptChips = document.getElementById('promptChips');

    this.toggleHistoryBtn = document.getElementById('toggleHistoryBtn');
    this.closeHistoryBtn = document.getElementById('closeHistoryBtn');
    this.historyDrawer = document.getElementById('historyDrawer');
    this.backdropOverlay = document.getElementById('backdropOverlay');
    this.historyList = document.getElementById('historyList');
    this.historyBadge = document.getElementById('historyBadge');
    this.clearChatBtn = document.getElementById('clearChatBtn');
    this.drawerClearBtn = document.getElementById('drawerClearBtn');

    this.ttsAudioPlayer = document.getElementById('ttsAudioPlayer');
    this.waveformCanvas = document.getElementById('waveformCanvas');
    this.canvasCtx = this.waveformCanvas ? this.waveformCanvas.getContext('2d') : null;
    this.particleCanvas = document.getElementById('particleCanvas');

    // Subsystems
    this.playbackManager = new AudioPlaybackManager(this.ttsAudioPlayer, (state) => {
      this.setState(state);
      if (state === 'IDLE') this.notifyStateReset();
    });

    this.particleSystem = new ParticleSystem(this.particleCanvas);

    this.audioCtx = null;
    this.analyser = null;
    this.recognition = null;
    this.mediaRecorder = null;
    this.audioChunks = [];
    this.finalTranscript = '';
    this.ws = null;

    this.init();
  }

  getOrCreateSessionId() {
    let sid = sessionStorage.getItem('aether_session_id');
    if (!sid) {
      sid = 'sess_' + Math.random().toString(36).substring(2, 11);
      sessionStorage.setItem('aether_session_id', sid);
    }
    return sid;
  }

  createNextGenerationId() {
    this.generationCounter += 1;
    this.activeGenerationId = `gen_${this.generationCounter}`;
    return this.activeGenerationId;
  }

  async init() {
    if (this.currentSessionLabel) {
      this.currentSessionLabel.textContent = `Session: ${this.sessionId}`;
    }
    this.setupEventListeners();
    await this.loadConfig();
    this.setupSpeechRecognition();
    this.setupAudioVisualizer();
    this.setupWebSocket();
    await this.checkSystemStatus();
    await this.loadHistory();
    this.startCanvasAnimation();
  }

  /* --------------------------------------------------------------------------
     WebSocket Real-Time State & Streaming
     -------------------------------------------------------------------------- */
  setupWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/ws`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        console.log('[WS] Connected to Aether Assistant real-time WebSocket.');
      };

      this.ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);

          // Discard events belonging to superseded generations
          if (msg.generation_id && msg.generation_id !== this.activeGenerationId) {
            return;
          }

          if (msg.type === 'state_change' && msg.state) {
            this.setState(msg.state);
          } else if (msg.type === 'device_state_change' && msg.data?.device_state) {
            this.setDeviceState(msg.data.device_state);
          } else if (msg.type === 'stream_chunk' && msg.data?.chunk) {
            this.appendStreamingText(msg.data.chunk);
          } else if (msg.type === 'command_executed' && msg.data) {
            this.handleLocalCommandResult(msg.data);
          }
        } catch (e) {
          console.warn('[WS] Error parsing message:', e);
        }
      };

      this.ws.onclose = () => {
        setTimeout(() => this.setupWebSocket(), 3000);
      };
    } catch (e) {
      console.warn('[WS] WebSocket setup skipped:', e);
    }
  }

  sendWsCancel(generationId) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        type: 'cancel_generation',
        generation_id: generationId,
        session_id: this.sessionId,
      }));
    }
  }

  /* --------------------------------------------------------------------------
     State Management
     -------------------------------------------------------------------------- */
  setState(newState) {
    if (this.state === newState) return;
    this.state = newState;

    const orbClasses = ['state-idle', 'state-listening', 'state-thinking', 'state-speaking', 'state-error'];
    this.aiOrb.classList.remove(...orbClasses);
    this.stateBadge.classList.remove(...orbClasses);

    switch (newState) {
      case 'LISTENING':
        this.aiOrb.classList.add('state-listening');
        this.stateBadge.classList.add('state-listening');
        this.stateText.textContent = 'LISTENING...';
        this.micBtn.classList.add('active');
        this.micLabel.textContent = 'LISTENING...';
        this.liveTranscriptBox.classList.remove('hidden');
        this.liveTranscriptText.textContent = 'Listening to your voice...';
        break;

      case 'THINKING':
        this.aiOrb.classList.add('state-thinking');
        this.stateBadge.classList.add('state-thinking');
        this.stateText.textContent = 'THINKING...';
        this.micBtn.classList.remove('active');
        this.micLabel.textContent = 'PROCESSING...';
        break;

      case 'SPEAKING':
        this.aiOrb.classList.add('state-speaking');
        this.stateBadge.classList.add('state-speaking');
        this.stateText.textContent = 'SPEAKING...';
        this.micBtn.classList.remove('active');
        this.micLabel.textContent = 'SPEAKING...';
        break;

      case 'ERROR':
        this.aiOrb.classList.add('state-error');
        this.stateBadge.classList.add('state-error');
        this.stateText.textContent = 'SYSTEM ERROR';
        this.micBtn.classList.remove('active');
        this.micLabel.textContent = 'ERROR';
        break;

      case 'IDLE':
      default:
        this.aiOrb.classList.add('state-idle');
        this.stateBadge.classList.add('state-idle');
        this.stateText.textContent = 'STANDBY IDLE';
        this.micBtn.classList.remove('active');
        this.micLabel.textContent = 'TAP TO SPEAK';
        break;
    }
  }

  setDeviceState(newDeviceState) {
    this.deviceState = newDeviceState;
    if (this.deviceText) {
      this.deviceText.textContent = `Device: ${newDeviceState}`;
    }
    if (this.devicePill) {
      this.devicePill.className = `status-pill ${newDeviceState === 'READY' ? 'device-ready' : 'missing_key'}`;
    }
  }

  /* --------------------------------------------------------------------------
     Event Listeners & Barge-in Controls
     -------------------------------------------------------------------------- */
  setupEventListeners() {
    this.micBtn.addEventListener('click', () => this.handleMicInteraction());
    this.aiOrb.addEventListener('click', () => this.handleMicInteraction());

    this.textChatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const message = this.textInput.value.trim();
      if (message) {
        this.textInput.value = '';
        this.sendChatMessage(message, true);
      }
    });

    this.replayAudioBtn.addEventListener('click', () => {
      if (this.currentAudioUrl) {
        this.playbackManager.play(this.currentAudioUrl, this.activeGenerationId);
      }
    });

    if (this.copyResponseBtn) {
      this.copyResponseBtn.addEventListener('click', () => {
        const text = this.aiResponseText.textContent.replace(/^"|"$/g, '').trim();
        if (text) {
          navigator.clipboard.writeText(text);
          const origHtml = this.copyResponseBtn.innerHTML;
          this.copyResponseBtn.innerHTML = '<span>✓ Copied</span>';
          setTimeout(() => {
            this.copyResponseBtn.innerHTML = origHtml;
          }, 2000);
        }
      });
    }

    if (this.promptChips) {
      this.promptChips.addEventListener('click', (e) => {
        const chip = e.target.closest('.prompt-chip');
        if (chip && chip.dataset.prompt) {
          this.sendChatMessage(chip.dataset.prompt, true, 'chip');
        }
      });
    }

    this.toggleHistoryBtn.addEventListener('click', () => this.openHistory());
    this.closeHistoryBtn.addEventListener('click', () => this.closeHistory());
    this.backdropOverlay.addEventListener('click', () => this.closeHistory());

    this.clearChatBtn.addEventListener('click', () => this.clearConversationHistory());
    this.drawerClearBtn.addEventListener('click', () => this.clearConversationHistory());

    this.dismissAlertBtn.addEventListener('click', () => {
      this.alertBanner.classList.add('hidden');
    });

    if (this.modelSelector) {
      this.modelSelector.addEventListener('change', async (e) => {
        const model = e.target.value;
        try {
          await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ gemini_model: model }),
          });
          await this.checkSystemStatus();
        } catch (err) {
          console.error('[Config Error]', err);
        }
      });
    }

    if (this.langSelector) {
      this.langSelector.addEventListener('change', async (e) => {
        const langMode = e.target.value;
        try {
          await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ language_mode: langMode }),
          });
          if (this.recognition) {
            this.recognition.lang = langMode === 'hi' ? 'hi-IN' : (langMode === 'en-US' ? 'en-US' : 'en-IN');
          }
        } catch (err) {
          console.error('[Config Error]', err);
        }
      });
    }

    window.addEventListener('keydown', (e) => {
      if (
        e.code === 'Space' &&
        document.activeElement !== this.textInput &&
        document.activeElement !== this.modelSelector &&
        document.activeElement !== this.langSelector
      ) {
        e.preventDefault();
        this.handleMicInteraction();
      }
    });
  }

  handleMicInteraction() {
    if (this.state === 'SPEAKING' || this.playbackManager.isPlaying) {
      console.log('⚡ Barge-in triggered.');
      const oldGenId = this.activeGenerationId;
      this.playbackManager.stop(true);
      this.sendWsCancel(oldGenId);
      this.createNextGenerationId();
      this.startVoiceRecording();
      return;
    }

    if (this.isRecording) {
      this.stopVoiceRecording();
    } else {
      this.createNextGenerationId();
      this.startVoiceRecording();
    }
  }

  /* --------------------------------------------------------------------------
     Speech Recognition (STT)
     -------------------------------------------------------------------------- */
  setupSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (SpeechRecognition) {
      this.recognition = new SpeechRecognition();
      this.recognition.continuous = false;
      this.recognition.interimResults = true;
      this.recognition.lang = 'en-IN';

      this.recognition.onstart = () => {
        this.isRecording = true;
        this.finalTranscript = '';
        this.setState('LISTENING');
      };

      this.recognition.onresult = (event) => {
        let interimTranscript = '';
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            this.finalTranscript += event.results[i][0].transcript;
          } else {
            interimTranscript += event.results[i][0].transcript;
          }
        }
        const displayText = this.finalTranscript || interimTranscript;
        if (displayText) {
          this.liveTranscriptText.textContent = `"${displayText}"`;
        }
      };

      this.recognition.onerror = (event) => {
        console.warn('[STT] Error:', event.error);
        if (event.error === 'not-allowed') {
          this.showAlert('Microphone permission denied. Please allow mic access in your browser.', 'error');
        }
      };

      this.recognition.onend = () => {
        this.isRecording = false;
        if (this.finalTranscript.trim()) {
          const promptToSend = this.finalTranscript.trim();
          this.sendChatMessage(promptToSend, true, 'voice');
        } else {
          this.setState('IDLE');
          setTimeout(() => {
            if (this.state === 'IDLE') {
              this.liveTranscriptBox.classList.add('hidden');
            }
          }, 2000);
        }
      };
    }
  }

  startVoiceRecording() {
    if (this.recognition) {
      try {
        this.recognition.start();
      } catch (err) {
        console.warn('[STT] Recognition already running or error:', err);
      }
    } else {
      this.startMediaRecording();
    }
  }

  stopVoiceRecording() {
    if (this.recognition) {
      try {
        this.recognition.stop();
      } catch (err) {}
    }
    if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
      this.mediaRecorder.stop();
    }
  }

  async startMediaRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.audioChunks = [];
      this.mediaRecorder = new MediaRecorder(stream);

      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) this.audioChunks.push(e.data);
      };

      this.mediaRecorder.onstop = async () => {
        this.isRecording = false;
        const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
        await this.uploadAudioForProcessing(audioBlob);
        stream.getTracks().forEach((track) => track.stop());
      };

      this.mediaRecorder.start();
      this.isRecording = true;
      this.setState('LISTENING');
    } catch (err) {
      this.showAlert('Could not access microphone: ' + err.message, 'error');
      this.setState('IDLE');
    }
  }

  async uploadAudioForProcessing(blob) {
    const currentGen = this.activeGenerationId;
    this.setState('THINKING');
    try {
      const formData = new FormData();
      formData.append('file', blob, 'recording.webm');
      formData.append('session_id', this.sessionId);

      const response = await fetch('/api/voice/process-audio', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (currentGen !== this.activeGenerationId) {
        return;
      }

      if (response.ok && data.success) {
        this.handleAssistantResponse(data);
      } else {
        throw new Error(data.detail || data.error || 'Failed to process audio');
      }
    } catch (err) {
      this.showAlert(err.message, 'error');
      this.setState('IDLE');
    }
  }

  /* --------------------------------------------------------------------------
     Chat Pipeline & Command Handling
     -------------------------------------------------------------------------- */
  async sendChatMessage(message, speak = true, source = 'text') {
    if (!message || !message.trim()) return;

    // Instant local hardware actions
    const lower = message.toLowerCase().trim();
    if (lower === 'mute' || lower === 'आवाज़ बंद करो') {
      this.playbackManager.setMute(true);
    } else if (lower === 'unmute' || lower === 'आवाज़ चालू करो') {
      this.playbackManager.setMute(false);
    } else if (lower === 'volume up' || lower === 'awaaz badhao' || lower === 'आवाज़ बढ़ाओ') {
      this.playbackManager.setVolume(0.2);
    } else if (lower === 'volume down' || lower === 'awaaz kam karo' || lower === 'आवाज़ कम करो') {
      this.playbackManager.setVolume(-0.2);
    } else if (lower === 'stop' || lower === 'cancel' || lower === 'ruko' || lower === 'रुको') {
      this.playbackManager.stop(false);
    }

    const currentGen = this.createNextGenerationId();
    this.setState('THINKING');
    this.liveTranscriptBox.classList.remove('hidden');
    this.liveTranscriptText.textContent = `"${message}"`;
    this.aiResponseText.textContent = 'Synthesizing neural response...';

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          speak,
          session_id: this.sessionId,
          generation_id: currentGen,
          model: this.modelSelector ? this.modelSelector.value : null,
          language: this.langSelector ? this.langSelector.value : null,
        }),
      });

      const data = await response.json();

      if (currentGen !== this.activeGenerationId) {
        return;
      }

      if (response.ok && data.success) {
        this.handleAssistantResponse(data);
        await this.loadHistory();
      } else {
        throw new Error(data.detail || data.error || 'Request failed');
      }
    } catch (err) {
      this.showAlert(err.message, 'error');
      this.setState('IDLE');
    }
  }

  handleLocalCommandResult(data) {
    this.aiResponseText.textContent = `[Action] ${data.response || data.command_name}`;

    if (data.action === 'STOP_PLAYBACK') {
      this.playbackManager.stop(false);
    } else if (data.action === 'MUTE_AUDIO') {
      this.playbackManager.setMute(true);
    } else if (data.action === 'UNMUTE_AUDIO') {
      this.playbackManager.setMute(false);
    } else if (data.action === 'VOLUME_UP') {
      this.playbackManager.setVolume(0.2);
    } else if (data.action === 'VOLUME_DOWN') {
      this.playbackManager.setVolume(-0.2);
    } else if (data.action === 'CLEAR_HISTORY') {
      this.loadHistory();
    }
  }

  appendStreamingText(chunk) {
    if (this.aiResponseText.textContent === 'Synthesizing neural response...') {
      this.aiResponseText.textContent = '';
    }
    this.aiResponseText.textContent += chunk;
  }

  handleAssistantResponse(data) {
    if (data.is_command) {
      this.handleLocalCommandResult(data);
    }

    const replyText = data.response || 'No response generated.';
    this.aiResponseText.textContent = replyText;

    // Update Latency HUD
    if (data.metrics && this.latencyHud) {
      this.latencyHud.classList.remove('hidden');
      if (this.hudGemini) this.hudGemini.textContent = `AI: ${data.metrics.gemini_latency_ms || 0}ms`;
      if (this.hudTts) this.hudTts.textContent = `TTS: ${data.metrics.tts_latency_ms || 0}ms`;
      if (this.hudStt) this.hudStt.textContent = `Total: ${data.metrics.total_duration_ms || 0}ms`;
    }

    if (data.audio_url) {
      this.currentAudioUrl = data.audio_url;
      this.replayAudioBtn.classList.remove('hidden');
      this.playbackManager.play(data.audio_url, data.generation_id);
    } else {
      this.setState('IDLE');
    }
  }

  async notifyStateReset() {
    try {
      await fetch('/api/state/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state: 'IDLE', session_id: this.sessionId }),
      });
    } catch (e) {}
  }

  /* --------------------------------------------------------------------------
     Configuration & History
     -------------------------------------------------------------------------- */
  async loadConfig() {
    try {
      const res = await fetch('/api/config');
      const data = await res.json();
      if (data.active_model && this.modelSelector) {
        this.modelSelector.value = data.active_model;
      }
      if (data.active_language_mode && this.langSelector) {
        this.langSelector.value = data.active_language_mode;
      }
    } catch (err) {}
  }

  async checkSystemStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();

      this.hasApiKey = data.has_api_key;
      this.statusPill.className = 'status-pill';

      if (data.device_state) {
        this.setDeviceState(data.device_state);
      }

      if (data.gemini && data.gemini.status === 'connected') {
        this.statusPill.classList.add('connected');
        this.statusText.textContent = `Online • ${data.model}`;
        this.alertBanner.classList.add('hidden');
        if (this.modelSelector) {
          this.modelSelector.value = data.model;
        }
      } else if (!data.has_api_key || data.gemini?.status === 'missing_key') {
        this.statusPill.classList.add('missing_key');
        this.statusText.textContent = 'API Key Needed (.env)';
        this.showAlert('Please set your GEMINI_API_KEY in .env file to enable Gemini AI.', 'warning');
      } else {
        this.statusPill.classList.add('error');
        this.statusText.textContent = 'Gemini Error';
        this.showAlert(data.gemini?.message || 'Error communicating with Gemini API', 'error');
      }
    } catch (err) {
      this.statusPill.className = 'status-pill error';
      this.statusText.textContent = 'Server Offline';
    }
  }

  async loadHistory() {
    try {
      const res = await fetch(`/api/history?session_id=${encodeURIComponent(this.sessionId)}`);
      const data = await res.json();
      const history = data.history || [];

      this.historyBadge.textContent = history.length;
      this.renderHistoryList(history);
    } catch (err) {}
  }

  renderHistoryList(messages) {
    if (!messages.length) {
      this.historyList.innerHTML = `
        <div class="history-empty">
          <div class="empty-spark-icon">✨</div>
          <p>No messages recorded in this session yet.<br>Start speaking or typing to begin.</p>
        </div>
      `;
      return;
    }

    this.historyList.innerHTML = messages
      .map((msg) => {
        const isUser = msg.role === 'user';
        const timeStr = new Date(msg.timestamp * 1000).toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        });
        return `
          <div class="history-item ${isUser ? 'user' : 'assistant'}">
            <div class="item-meta">
              <span class="item-role">${isUser ? 'You (' + msg.source + ')' : 'Aether AI'}</span>
              <span class="item-time">${timeStr}</span>
            </div>
            <p class="item-text">${this.escapeHtml(msg.text)}</p>
          </div>
        `;
      })
      .join('');

    this.historyList.scrollTop = this.historyList.scrollHeight;
  }

  async clearConversationHistory() {
    if (!confirm('Are you sure you want to clear this session history?')) return;
    try {
      await fetch(`/api/history?session_id=${encodeURIComponent(this.sessionId)}`, { method: 'DELETE' });
      await this.loadHistory();
      this.aiResponseText.textContent = '"Session history cleared. How can I assist you now?"';
      this.replayAudioBtn.classList.add('hidden');
      this.liveTranscriptBox.classList.add('hidden');
    } catch (err) {}
  }

  openHistory() {
    this.historyDrawer.classList.add('open');
    this.backdropOverlay.classList.add('active');
  }

  closeHistory() {
    this.historyDrawer.classList.remove('open');
    this.backdropOverlay.classList.remove('active');
  }

  showAlert(message, type = 'warning') {
    this.alertMessage.textContent = message;
    this.alertBanner.className = `alert-banner ${type}`;
    this.alertBanner.classList.remove('hidden');
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /* --------------------------------------------------------------------------
     Canvas Visualizer
     -------------------------------------------------------------------------- */
  setupAudioVisualizer() {
    if (!this.waveformCanvas) return;
    try {
      const AudioCtxClass = window.AudioContext || window.webkitAudioContext;
      if (AudioCtxClass) {
        this.audioCtx = new AudioCtxClass();
        this.analyser = this.audioCtx.createAnalyser();
        this.analyser.fftSize = 64;

        if (this.ttsAudioPlayer) {
          const source = this.audioCtx.createMediaElementSource(this.ttsAudioPlayer);
          source.connect(this.analyser);
          this.analyser.connect(this.audioCtx.destination);
        }
      }
    } catch (e) {}
  }

  startCanvasAnimation() {
    if (!this.canvasCtx) return;

    const canvas = this.waveformCanvas;
    const ctx = this.canvasCtx;
    let angle = 0;

    const render = () => {
      requestAnimationFrame(render);
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const centerX = canvas.width / 2;
      const centerY = canvas.height / 2;
      const baseRadius = 104;

      let frequencyData = new Uint8Array(32);
      if (this.analyser && this.state === 'SPEAKING') {
        this.analyser.getByteFrequencyData(frequencyData);
      }

      ctx.save();
      ctx.translate(centerX, centerY);

      angle += this.state === 'THINKING' ? 0.08 : 0.02;
      ctx.rotate(angle);

      const barCount = 40;
      for (let i = 0; i < barCount; i++) {
        const barAngle = (i * 2 * Math.PI) / barCount;
        let barHeight = 0;

        if (this.state === 'SPEAKING') {
          const freqIndex = i % frequencyData.length;
          barHeight = (frequencyData[freqIndex] / 255) * 26;
        } else if (this.state === 'LISTENING') {
          barHeight = Math.sin(angle * 2.5 + i) * 8 + 6;
        } else if (this.state === 'THINKING') {
          barHeight = Math.cos(angle * 4 + i) * 9 + 5;
        } else {
          barHeight = Math.sin(angle + i * 0.5) * 3;
        }

        const r1 = baseRadius;
        const r2 = baseRadius + Math.max(3, barHeight);

        const x1 = Math.cos(barAngle) * r1;
        const y1 = Math.sin(barAngle) * r1;
        const x2 = Math.cos(barAngle) * r2;
        const y2 = Math.sin(barAngle) * r2;

        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);

        if (this.state === 'LISTENING') {
          ctx.strokeStyle = `rgba(16, 185, 129, ${0.5 + (barHeight / 24) * 0.5})`;
          ctx.lineWidth = 3;
        } else if (this.state === 'THINKING') {
          ctx.strokeStyle = `rgba(236, 72, 153, ${0.5 + (barHeight / 24) * 0.5})`;
          ctx.lineWidth = 3;
        } else if (this.state === 'SPEAKING') {
          ctx.strokeStyle = `rgba(139, 92, 246, ${0.6 + (barHeight / 26) * 0.4})`;
          ctx.lineWidth = 3.5;
        } else {
          ctx.strokeStyle = `rgba(0, 240, 255, 0.22)`;
          ctx.lineWidth = 1.8;
        }

        ctx.stroke();
      }

      ctx.restore();
    };

    render();
  }
}

window.addEventListener('DOMContentLoaded', () => {
  window.assistantApp = new VoiceAssistantApp();
});
