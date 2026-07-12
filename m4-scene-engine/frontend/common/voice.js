/**
 * 云汐语音助手 - 前端语音组件
 * 功能: 语音录制、语音识别、语音合成播放、唤醒词检测、音色管理
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

    // 唤醒词相关回调
    this.onWakeWord = options.onWakeWord || null;           // 检测到唤醒词回调
    this.onWakeStateChange = options.onWakeStateChange || null; // 唤醒状态变化回调

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

    // ===== 唤醒词检测相关 =====
    this._wakeRecorder = null;       // 唤醒词专用录音器
    this._wakeStream = null;         // 唤醒词专用音频流
    this._wakeState = 'idle';        // idle / listening / detecting / awake
    this._wakeChunks = [];           // 唤醒词录音片段缓存
    this._wakeSliceInterval = null;  // 切片定时器
    this._wakeSliceDuration = options.wakeSliceDuration || 2000; // 每片时长(ms)
    this._wakeMinSilence = options.wakeMinSilence || 300;        // 最小静音间隔(ms)
    this._wakeAutoRecord = options.wakeAutoRecord !== false;     // 唤醒后自动开始录音
    this._wakeDetectPromise = null;  // 当前检测请求的Promise，防止并发
    this._wakeLastDetectTime = 0;    // 上次检测时间，用于节流
    this._wakeCooldown = 1500;       // 检测冷却时间(ms)，避免重复触发

    // ===== 音色相关 =====
    this._currentVoice = options.voiceType || null;  // 当前选中的音色ID
    this._voiceOptions = null;                       // 缓存的音色列表
    this._voiceSpeed = options.speed || 1.0;         // 语速
    this._voicePitch = options.pitch || 1.0;         // 音调
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

    const voiceType = options.voiceType || this._currentVoice || null;
    const speed = options.speed !== undefined ? options.speed : this._voiceSpeed;
    const pitch = options.pitch !== undefined ? options.pitch : this._voicePitch;

    // 先尝试后端TTS
    try {
      const status = this._status || await this.getStatus();
      if (status.tts_available) {
        await this._speak_backend(text, voiceType, speed, pitch);
        return;
      }
    } catch (e) {
      console.warn('[Voice] 后端TTS失败，使用浏览器TTS:', e);
    }

    // 浏览器TTS兜底
    this._speak_browser(text, { speed, pitch });
  }

  async _speak_backend(text, voiceType, speed, pitch) {
    try {
      let url = `${this.apiBase}/tts/stream?text=${encodeURIComponent(text)}`;
      if (voiceType) url += `&voice_type=${encodeURIComponent(voiceType)}`;
      if (speed !== undefined && speed !== null) url += `&speed=${speed}`;
      if (pitch !== undefined && pitch !== null) url += `&pitch=${pitch}`;

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
        this._speak_browser(text, { speed, pitch });
      };

      await this.currentAudio.play();
    } catch (e) {
      console.error('[Voice] 后端TTS播放失败:', e);
      this._speak_browser(text, { speed, pitch });
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

  // ============================================================
  // 唤醒词检测 (Wake Word Detection)
  // ============================================================

  /**
   * 获取当前唤醒词检测状态
   * @returns {string} idle / listening / detecting / awake
   */
  getWakeState() {
    return this._wakeState;
  }

  /**
   * 设置唤醒词检测状态并触发回调
   * @param {string} state 新状态
   * @param {object} extra 附加信息
   */
  _setWakeState(state, extra = {}) {
    if (this._wakeState === state) return;
    this._wakeState = state;
    if (this.onWakeStateChange) {
      this.onWakeStateChange({ state, ...extra });
    }
  }

  /**
   * 开始唤醒词检测
   * 持续监听麦克风，按固定间隔切片发送到后端检测唤醒词
   * 检测到唤醒词后触发 onWakeWord 回调
   * @param {object} options 可选配置
   * @param {number} options.sliceDuration 每片音频时长(ms)，默认2000
   * @param {boolean} options.autoRecord 唤醒后是否自动开始录音，默认true
   * @returns {Promise<boolean>} 是否成功启动
   */
  async startWakeWordDetection(options = {}) {
    if (this._wakeState !== 'idle' && this._wakeState !== 'awake') {
      console.warn('[Voice] 唤醒词检测已在运行中');
      return false;
    }
    if (!this.isASRSupported()) {
      throw new Error('当前浏览器不支持录音功能，无法进行唤醒词检测');
    }

    // 应用配置
    if (options.sliceDuration) this._wakeSliceDuration = options.sliceDuration;
    if (options.autoRecord !== undefined) this._wakeAutoRecord = options.autoRecord;

    try {
      // 获取麦克风权限（低功耗模式）
      this._wakeStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      });

      // 选择合适的MIME类型
      let mimeType = 'audio/webm';
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
        mimeType = 'audio/webm;codecs=opus';
      }

      this._wakeRecorder = new MediaRecorder(this._wakeStream, { mimeType });
      this._wakeChunks = [];

      // 监听数据可用事件
      this._wakeRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          this._wakeChunks.push(e.data);
        }
      };

      // 启动录音
      this._wakeRecorder.start();
      this._setWakeState('listening');
      console.log('[Voice] 唤醒词检测已启动');

      // 启动定时切片检测
      this._startWakeSlicing();

      return true;
    } catch (e) {
      console.error('[Voice] 启动唤醒词检测失败:', e);
      this._cleanupWakeRecorder();
      this._setWakeState('idle', { error: e.message });
      throw e;
    }
  }

  /**
   * 停止唤醒词检测
   */
  stopWakeWordDetection() {
    if (this._wakeState === 'idle') return;

    // 停止切片定时器
    if (this._wakeSliceInterval) {
      clearInterval(this._wakeSliceInterval);
      this._wakeSliceInterval = null;
    }

    // 停止录音
    if (this._wakeRecorder && this._wakeRecorder.state !== 'inactive') {
      try {
        this._wakeRecorder.stop();
      } catch (e) {
        console.warn('[Voice] 停止唤醒词录音器失败:', e);
      }
    }

    // 清理资源
    this._cleanupWakeRecorder();
    this._setWakeState('idle');
    console.log('[Voice] 唤醒词检测已停止');
  }

  /**
   * 启动定时切片检测
   * 每隔 sliceDuration 毫秒，截取一段音频发送给后端检测
   */
  _startWakeSlicing() {
    if (this._wakeSliceInterval) {
      clearInterval(this._wakeSliceInterval);
    }

    this._wakeSliceInterval = setInterval(() => {
      this._processWakeSlice();
    }, this._wakeSliceDuration);
  }

  /**
   * 处理一个音频切片：取出当前缓存的音频数据，发送到后端检测
   */
  async _processWakeSlice() {
    // 如果当前正在检测中，跳过本次（节流）
    if (this._wakeDetectPromise) return;
    if (this._wakeState !== 'listening') return;

    // 检查是否有足够的音频数据
    if (this._wakeChunks.length === 0) return;

    // 取出当前所有chunk，构造Blob
    const chunks = this._wakeChunks.slice();
    // 保留最后一小段做重叠，避免唤醒词刚好落在切片边界
    if (this._wakeChunks.length > 1) {
      this._wakeChunks = [this._wakeChunks[this._wakeChunks.length - 1]];
    } else {
      this._wakeChunks = [];
    }

    if (chunks.length === 0) return;

    const audioBlob = new Blob(chunks, { type: 'audio/webm' });

    // 音频太小则跳过（可能是静音段）
    if (audioBlob.size < 2000) return;

    // 冷却时间检查
    const now = Date.now();
    if (now - this._wakeLastDetectTime < this._wakeCooldown) return;

    // 发送检测请求
    this._setWakeState('detecting');
    this._wakeLastDetectTime = now;

    try {
      this._wakeDetectPromise = this._detectWakeWord(audioBlob);
      const result = await this._wakeDetectPromise;

      if (result && result.detected) {
        // 检测到唤醒词！
        console.log('[Voice] 检测到唤醒词:', result.matched_word);
        this._handleWakeWordDetected(result);
      } else {
        // 未检测到，回到监听状态
        this._setWakeState('listening');
      }
    } catch (e) {
      console.warn('[Voice] 唤醒词检测请求失败:', e);
      this._setWakeState('listening', { error: e.message });
    } finally {
      this._wakeDetectPromise = null;
    }
  }

  /**
   * 调用后端唤醒词检测接口
   * @param {Blob} audioBlob 音频数据
   * @returns {Promise<object>} 检测结果
   */
  async _detectWakeWord(audioBlob) {
    const formData = new FormData();
    formData.append('file', audioBlob, 'wake_slice.webm');
    formData.append('language', 'zh');

    const res = await fetch(`${this.apiBase}/wake-word/detect`, {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }

    const data = await res.json();
    if (data.code === 0 && data.data) {
      return data.data;
    }
    throw new Error(data.message || '唤醒词检测失败');
  }

  /**
   * 处理唤醒词检测成功的情况
   * @param {object} result 检测结果
   */
  _handleWakeWordDetected(result) {
    this._setWakeState('awake', {
      matched_word: result.matched_word,
      confidence: result.confidence,
      text: result.text,
    });

    // 触发回调
    if (this.onWakeWord) {
      this.onWakeWord({
        matched_word: result.matched_word,
        confidence: result.confidence,
        text: result.text,
        timestamp: Date.now(),
      });
    }

    // 唤醒后自动开始录音（发送消息模式）
    if (this._wakeAutoRecord) {
      // 短暂延迟后开始录音，让用户说完唤醒词后有个停顿
      setTimeout(() => {
        // 停止唤醒检测，开始正式录音
        this.stopWakeWordDetection();
        this.startRecording().catch(e => {
          console.error('[Voice] 唤醒后自动录音失败:', e);
        });
      }, 300);
    }
  }

  /**
   * 清理唤醒词录音资源
   */
  _cleanupWakeRecorder() {
    if (this._wakeStream) {
      this._wakeStream.getTracks().forEach(track => track.stop());
      this._wakeStream = null;
    }
    this._wakeRecorder = null;
    this._wakeChunks = [];
    if (this._wakeSliceInterval) {
      clearInterval(this._wakeSliceInterval);
      this._wakeSliceInterval = null;
    }
    this._wakeDetectPromise = null;
  }

  /**
   * 获取唤醒词配置
   * @returns {Promise<object>} 唤醒词配置
   */
  async getWakeWordConfig() {
    try {
      const res = await fetch(`${this.apiBase}/wake-word/config`);
      const data = await res.json();
      return data.data || {};
    } catch (e) {
      console.warn('[Voice] 获取唤醒词配置失败:', e);
      return { wake_words: ['云汐', '你好云汐'] };
    }
  }

  /**
   * 更新唤醒词配置
   * @param {string[]} wakeWords 唤醒词列表
   * @returns {Promise<boolean>} 是否成功
   */
  async updateWakeWordConfig(wakeWords) {
    try {
      const res = await fetch(`${this.apiBase}/wake-word/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ wake_words: wakeWords }),
      });
      const data = await res.json();
      return data.code === 0;
    } catch (e) {
      console.warn('[Voice] 更新唤醒词配置失败:', e);
      return false;
    }
  }

  // ============================================================
  // 音色管理 (Voice Options)
  // ============================================================

  /**
   * 获取所有可用音色（带分类）
   * 优先从后端获取，后端不可用时返回内置默认音色列表
   * @param {boolean} forceRefresh 是否强制刷新缓存
   * @returns {Promise<object>} 音色数据 { voices, categories, engine }
   */
  async getVoiceOptions(forceRefresh = false) {
    // 如果已有缓存且不强制刷新，直接返回
    if (this._voiceOptions && !forceRefresh) {
      return this._voiceOptions;
    }

    try {
      // 尝试从后端获取
      const res = await fetch(`${this.apiBase}/voices`);
      const data = await res.json();

      if (data.code === 0 && data.data && data.data.voices && data.data.voices.length > 0) {
        const voices = data.data.voices;
        const engine = data.data.engine || 'unknown';
        const categorized = this._categorizeVoices(voices);

        this._voiceOptions = {
          voices,           // 扁平列表
          categories: categorized, // 按分类组织
          engine,
          source: 'backend',
        };
        return this._voiceOptions;
      }
    } catch (e) {
      console.warn('[Voice] 从后端获取音色列表失败，使用内置音色:', e);
    }

    // 后端不可用，返回内置默认音色
    const defaultVoices = this._getDefaultVoices();
    const categorized = this._categorizeVoices(defaultVoices);
    this._voiceOptions = {
      voices: defaultVoices,
      categories: categorized,
      engine: 'browser',
      source: 'builtin',
    };
    return this._voiceOptions;
  }

  /**
   * 内置默认音色列表（后端不可用时使用）
   * @returns {Array} 音色数组
   */
  _getDefaultVoices() {
    return [
      // 普通话女声
      { id: 'warm_female', name: '温暖女声', desc: '亲切自然，适合日常对话', category: 'mandarin_female', gender: 'female', language: 'zh-CN' },
      { id: 'clear_female', name: '清澈女声', desc: '明亮通透，适合播报', category: 'mandarin_female', gender: 'female', language: 'zh-CN' },
      { id: 'sweet_female', name: '甜美女声', desc: '甜美柔和，适合陪伴场景', category: 'mandarin_female', gender: 'female', language: 'zh-CN' },
      { id: 'professional_female', name: '知性女声', desc: '专业干练，适合商务场景', category: 'mandarin_female', gender: 'female', language: 'zh-CN' },
      // 普通话男声
      { id: 'gentle_male', name: '温柔男声', desc: '沉稳磁性，适合深度对话', category: 'mandarin_male', gender: 'male', language: 'zh-CN' },
      { id: 'deep_male', name: '浑厚男声', desc: '低沉有力，适合纪录片旁白', category: 'mandarin_male', gender: 'male', language: 'zh-CN' },
      { id: 'youth_male', name: '青年男声', desc: '活力阳光，适合年轻向内容', category: 'mandarin_male', gender: 'male', language: 'zh-CN' },
      // 方言
      { id: 'cantonese_female', name: '粤语女声', desc: '地道广东话', category: 'dialect', gender: 'female', language: 'zh-YUE' },
      { id: 'sichuan_female', name: '四川话女声', desc: '川味十足', category: 'dialect', gender: 'female', language: 'zh-SCH' },
      { id: 'northeast_male', name: '东北话男声', desc: '豪爽大气', category: 'dialect', gender: 'male', language: 'zh-NEM' },
      // 港澳台
      { id: 'taiwan_female', name: '台湾腔女声', desc: '温柔婉转', category: 'hk_mo_tw', gender: 'female', language: 'zh-TW' },
      { id: 'hongkong_male', name: '香港粤语男声', desc: '港式韵味', category: 'hk_mo_tw', gender: 'male', language: 'zh-HK' },
    ];
  }

  /**
   * 将音色数组按分类组织
   * @param {Array} voices 音色数组
   * @returns {object} 分类后的音色 { categoryKey: { label, voices: [] } }
   */
  _categorizeVoices(voices) {
    const categoryMap = {
      mandarin_female: { label: '普通话女声', order: 1, voices: [] },
      mandarin_male: { label: '普通话男声', order: 2, voices: [] },
      dialect: { label: '方言', order: 3, voices: [] },
      hk_mo_tw: { label: '港澳台', order: 4, voices: [] },
      other: { label: '其他', order: 99, voices: [] },
    };

    voices.forEach(voice => {
      const cat = voice.category || 'other';
      if (categoryMap[cat]) {
        categoryMap[cat].voices.push(voice);
      } else {
        categoryMap.other.voices.push(voice);
      }
    });

    // 转换为有序对象
    const result = {};
    Object.keys(categoryMap)
      .filter(key => categoryMap[key].voices.length > 0)
      .sort((a, b) => categoryMap[a].order - categoryMap[b].order)
      .forEach(key => {
        result[key] = {
          label: categoryMap[key].label,
          voices: categoryMap[key].voices,
        };
      });

    return result;
  }

  /**
   * 设置当前音色
   * @param {string} voiceId 音色ID
   * @returns {boolean} 是否设置成功
   */
  setVoice(voiceId) {
    if (!voiceId) {
      this._currentVoice = null;
      return true;
    }

    // 如果有音色列表，验证音色ID是否存在
    if (this._voiceOptions && this._voiceOptions.voices) {
      const exists = this._voiceOptions.voices.some(v => v.id === voiceId);
      if (!exists) {
        console.warn(`[Voice] 音色 "${voiceId}" 不存在于可用音色列表中`);
        // 仍然允许设置，后端可能支持更多音色
      }
    }

    this._currentVoice = voiceId;
    return true;
  }

  /**
   * 获取当前音色ID
   * @returns {string|null} 当前音色ID
   */
  getCurrentVoice() {
    return this._currentVoice;
  }

  /**
   * 获取当前音色的详细信息
   * @returns {object|null} 音色详情
   */
  getCurrentVoiceInfo() {
    if (!this._currentVoice || !this._voiceOptions) return null;
    return this._voiceOptions.voices.find(v => v.id === this._currentVoice) || null;
  }

  /**
   * 设置语速
   * @param {number} speed 语速倍率 (0.5 - 2.0)
   */
  setSpeed(speed) {
    this._voiceSpeed = Math.max(0.5, Math.min(2.0, parseFloat(speed) || 1.0));
  }

  /**
   * 设置音调
   * @param {number} pitch 音调倍率 (0.5 - 2.0)
   */
  setPitch(pitch) {
    this._voicePitch = Math.max(0.5, Math.min(2.0, parseFloat(pitch) || 1.0));
  }

  /**
   * 获取当前语速
   * @returns {number}
   */
  getSpeed() {
    return this._voiceSpeed;
  }

  /**
   * 获取当前音调
   * @returns {number}
   */
  getPitch() {
    return this._voicePitch;
  }
}

// 导出为全局变量
if (typeof window !== 'undefined') {
  window.YunxiVoice = YunxiVoice;
}
