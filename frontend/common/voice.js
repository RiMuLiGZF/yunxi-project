/**
 * 云汐语音助手 - 前端语音组件
 * 功能: 语音录制、语音识别、语音合成播放
 * 依赖: 浏览器 MediaRecorder API + 后端 /api/voice 接口
 */

class YunxiVoice {
  constructor(options = {}) {
    this.apiBase = options.apiBase || '/api/voice';
    this.onResult = options.onResult || null;        // 语音识别结果回调
    this.onRecordingStart = options.onRecordingStart || null;
    this.onRecordingStop = options.onRecordingStop || null;
    this.onSpeakingStart = options.onSpeakingStart || null;
    this.onSpeakingEnd = options.onSpeakingEnd || null;

    // 录音相关
    this.mediaRecorder = null;
    this.audioChunks = [];
    this.isRecording = false;
    this.stream = null;
    this.startTime = 0;

    // 播放相关
    this.currentAudio = null;
    this.isSpeaking = false;

    // 状态缓存
    this._status = null;
  }

  // ===== 状态检查 =====

  async getStatus() {
    try {
      const res = await fetch(`${this.apiBase}/status`);
      const data = await res.json();
      this._status = data.data || {};
      return this._status;
    } catch (e) {
      console.warn('[Voice] 获取状态失败:', e);
      return {
        tts_available: false,
        asr_available: false,
        tts_engine: 'browser',
        asr_engine: 'none',
      };
    }
  }

  isASRSupported() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }

  isTTSSupported() {
    return !!window.speechSynthesis; // 浏览器TTS总是可用
  }

  // ===== 语音识别(ASR) =====

  async startRecording() {
    if (this.isRecording) return;
    if (!this.isASRSupported()) {
      throw new Error('当前浏览器不支持录音功能');
    }

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        }
      });

      // 尝试使用最佳MIME类型
      let mimeType = 'audio/webm';
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
        mimeType = 'audio/webm;codecs=opus';
      }

      this.mediaRecorder = new MediaRecorder(this.stream, { mimeType });
      this.audioChunks = [];

      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          this.audioChunks.push(e.data);
        }
      };

      this.mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(this.audioChunks, { type: mimeType });
        this._cleanupStream();

        if (audioBlob.size > 1000) { // 至少1KB才算有效录音
          await this._transcribeAudio(audioBlob);
        } else {
          console.log('[Voice] 录音太短，已忽略');
        }

        this.isRecording = false;
        if (this.onRecordingStop) {
          this.onRecordingStop({ duration: Date.now() - this.startTime });
        }
      };

      this.mediaRecorder.start();
      this.isRecording = true;
      this.startTime = Date.now();

      if (this.onRecordingStart) {
        this.onRecordingStart();
      }

      return true;
    } catch (e) {
      console.error('[Voice] 开始录音失败:', e);
      this._cleanupStream();
      throw e;
    }
  }

  stopRecording() {
    if (!this.isRecording || !this.mediaRecorder) return;

    try {
      this.mediaRecorder.stop();
    } catch (e) {
      console.error('[Voice] 停止录音失败:', e);
      this._cleanupStream();
      this.isRecording = false;
    }
  }

  toggleRecording() {
    if (this.isRecording) {
      this.stopRecording();
      return false;
    } else {
      this.startRecording();
      return true;
    }
  }

  async _transcribeAudio(audioBlob) {
    try {
      const formData = new FormData();
      formData.append('file', audioBlob, 'recording.webm');
      formData.append('language', 'zh');

      const res = await fetch(`${this.apiBase}/asr/transcribe`, {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();

      if (data.code === 0 && data.data && data.data.text) {
        if (this.onResult) {
          this.onResult({
            text: data.data.text,
            engine: data.data.engine,
            duration: data.data.duration,
          });
        }
      } else {
        console.warn('[Voice] 语音识别失败:', data.message);
        // 失败时用浏览器的Web Speech API兜底
        this._fallbackASR();
      }
    } catch (e) {
      console.error('[Voice] 语音识别请求失败:', e);
      this._fallbackASR();
    }
  }

  _fallbackASR() {
    // 浏览器Web Speech API兜底（如果支持的话）
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition();
      recognition.lang = 'zh-CN';
      recognition.onresult = (e) => {
        const text = e.results[0][0].transcript;
        if (this.onResult) {
          this.onResult({ text, engine: 'browser', duration: 0 });
        }
      };
      recognition.onerror = (e) => {
        console.warn('[Voice] 浏览器语音识别失败:', e.error);
      };
      try {
        recognition.start();
      } catch (e) {
        console.warn('[Voice] 浏览器语音识别启动失败:', e);
      }
    }
  }

  _cleanupStream() {
    if (this.stream) {
      this.stream.getTracks().forEach(track => track.stop());
      this.stream = null;
    }
    this.mediaRecorder = null;
    this.audioChunks = [];
  }

  // ===== 语音合成(TTS) =====

  async speak(text, options = {}) {
    if (!text || !text.trim()) return;

    this.stopSpeaking();

    const voiceType = options.voiceType || null;

    // 先尝试后端TTS
    try {
      const status = this._status || await this.getStatus();
      if (status.tts_available) {
        await this._speak_backend(text, voiceType);
        return;
      }
    } catch (e) {
      console.warn('[Voice] 后端TTS失败，使用浏览器TTS:', e);
    }

    // 浏览器TTS兜底
    this._speak_browser(text, options);
  }

  async _speak_backend(text, voiceType) {
    try {
      const url = `${this.apiBase}/tts/stream?text=${encodeURIComponent(text)}${voiceType ? `&voice_type=${voiceType}` : ''}`;
      this.currentAudio = new Audio(url);

      this.currentAudio.onplay = () => {
        this.isSpeaking = true;
        if (this.onSpeakingStart) this.onSpeakingStart();
      };

      this.currentAudio.onended = () => {
        this.isSpeaking = false;
        this.currentAudio = null;
        if (this.onSpeakingEnd) this.onSpeakingEnd();
      };

      this.currentAudio.onerror = (e) => {
        console.warn('[Voice] 音频播放失败，降级到浏览器TTS:', e);
        this.isSpeaking = false;
        this._speak_browser(text, {});
      };

      await this.currentAudio.play();
    } catch (e) {
      console.error('[Voice] 后端TTS播放失败:', e);
      this._speak_browser(text, {});
    }
  }

  _speak_browser(text, options) {
    if (!window.speechSynthesis) return;

    // 停止当前播放
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'zh-CN';
    utterance.rate = options.speed || 1.0;
    utterance.pitch = options.pitch || 1.0;

    // 尝试选择中文语音
    const voices = window.speechSynthesis.getVoices();
    const chineseVoice = voices.find(v => v.lang.includes('zh') || v.lang.includes('CN'));
    if (chineseVoice) {
      utterance.voice = chineseVoice;
    }

    utterance.onstart = () => {
      this.isSpeaking = true;
      if (this.onSpeakingStart) this.onSpeakingStart();
    };

    utterance.onend = () => {
      this.isSpeaking = false;
      if (this.onSpeakingEnd) this.onSpeakingEnd();
    };

    utterance.onerror = () => {
      this.isSpeaking = false;
    };

    window.speechSynthesis.speak(utterance);
  }

  stopSpeaking() {
    // 停止音频播放
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio.currentTime = 0;
      this.currentAudio = null;
    }

    // 停止浏览器TTS
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }

    this.isSpeaking = false;
  }

  // ===== 配置 =====

  async getConfig() {
    try {
      const res = await fetch(`${this.apiBase}/config`);
      const data = await res.json();
      return data.data || {};
    } catch (e) {
      return {};
    }
  }

  async updateConfig(config) {
    try {
      const res = await fetch(`${this.apiBase}/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      const data = await res.json();
      return data.code === 0;
    } catch (e) {
      return false;
    }
  }
}

// 导出为全局变量
if (typeof window !== 'undefined') {
  window.YunxiVoice = YunxiVoice;
}
