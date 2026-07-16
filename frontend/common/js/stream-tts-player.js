/**
 * 云汐系统 - 流式 TTS 播放器
 * =========================
 *
 * 功能：
 *   - SSE 流式接收音频数据，边生成边播放
 *   - 支持 WAV 格式（base64 编码的 SSE 数据）
 *   - 播放、暂停、停止、打断
 *   - 音量调节、语速调节
 *   - 事件回调：onStart、onChunk、onEnd、onError
 *   - 自动重连（意外断开时）
 *   - 向后兼容：不支持流式时降级为完整音频播放
 *
 * 后端 SSE 接口约定（GET /v1/tts/stream）：
 *   参数：text, speaker, emotion, speed, format=wav
 *   返回：text/event-stream 格式，包含以下事件类型：
 *     - tts_start   : 合成开始
 *     - audio_chunk : 音频数据块（base64 编码的 WAV 数据）
 *     - tts_end     : 合成结束
 *     - error       : 错误信息
 *
 * 使用方式：见文件底部 "使用示例"
 *
 * 依赖：无外部依赖，纯原生 JS
 */

(function (global) {
  'use strict';

  // ============================================================
  // 工具函数
  // ============================================================

  /**
   * 将 base64 字符串解码为 ArrayBuffer
   */
  function base64ToArrayBuffer(base64) {
    const binaryString = atob(base64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes.buffer;
  }

  /**
   * 解析 WAV 文件头，提取音频格式信息
   * @param {ArrayBuffer} buffer - WAV 文件数据
   * @returns {Object|null} { sampleRate, channels, bitDepth, dataOffset, dataLength } 或 null（解析失败）
   */
  function parseWavHeader(buffer) {
    const view = new DataView(buffer);

    // 检查 RIFF 标识
    if (view.getUint32(0, true) !== 0x46464952) { // "RIFF"
      return null;
    }

    // 检查 WAVE 标识
    if (view.getUint32(8, true) !== 0x45564157) { // "WAVE"
      return null;
    }

    let offset = 12;
    let fmt = null;
    let dataOffset = null;
    let dataLength = 0;

    // 遍历 chunk
    while (offset < buffer.byteLength - 8) {
      const chunkId = view.getUint32(offset, true);
      const chunkSize = view.getUint32(offset + 4, true);

      if (chunkId === 0x20746d66) { // "fmt "
        const audioFormat = view.getUint16(offset + 8, true);
        const numChannels = view.getUint16(offset + 10, true);
        const sampleRate = view.getUint32(offset + 12, true);
        const bitsPerSample = view.getUint16(offset + 22, true);

        fmt = {
          audioFormat: audioFormat,       // 1 = PCM
          channels: numChannels,
          sampleRate: sampleRate,
          bitDepth: bitsPerSample,
          byteRate: view.getUint32(offset + 16, true),
          blockAlign: view.getUint16(offset + 20, true),
        };
      } else if (chunkId === 0x61746164) { // "data"
        dataOffset = offset + 8;
        dataLength = chunkSize;
        break; // 找到 data chunk 就停止（假设 data 是最后一个重要 chunk）
      }

      offset += 8 + chunkSize;
      // 对齐到偶数
      if (chunkSize % 2 !== 0) {
        offset += 1;
      }
    }

    if (!fmt || dataOffset === null) {
      return null;
    }

    return {
      sampleRate: fmt.sampleRate,
      channels: fmt.channels,
      bitDepth: fmt.bitDepth,
      audioFormat: fmt.audioFormat,
      dataOffset: dataOffset,
      dataLength: dataLength,
      byteRate: fmt.byteRate,
      blockAlign: fmt.blockAlign,
    };
  }

  /**
   * 将 WAV PCM 数据转换为 Float32Array（Web Audio API 使用的格式）
   * @param {ArrayBuffer} buffer - 完整 WAV 数据
   * @param {Object} format - 从 parseWavHeader 获取的格式信息
   * @param {number} [startOffset=0] - 数据起始偏移（相对于 data chunk 起点）
   * @param {number} [length] - 要转换的字节数（默认全部）
   * @returns {Float32Array[]} 每个声道一个 Float32Array
   */
  function wavToFloat32(buffer, format, startOffset, length) {
    const dataStart = format.dataOffset + (startOffset || 0);
    const dataEnd = length !== undefined
      ? dataStart + length
      : format.dataOffset + format.dataLength;

    const view = new DataView(buffer);
    const numChannels = format.channels;
    const bitDepth = format.bitDepth;
    const bytesPerSample = bitDepth / 8;
    const totalSamples = Math.floor((dataEnd - dataStart) / (bytesPerSample * numChannels));

    // 每个声道一个数组
    const channels = [];
    for (let ch = 0; ch < numChannels; ch++) {
      channels.push(new Float32Array(totalSamples));
    }

    const isLittleEndian = true; // WAV 总是小端

    for (let i = 0; i < totalSamples; i++) {
      for (let ch = 0; ch < numChannels; ch++) {
        const sampleOffset = dataStart + (i * numChannels + ch) * bytesPerSample;
        let sample;

        switch (bitDepth) {
          case 8:
            sample = view.getUint8(sampleOffset);
            sample = (sample - 128) / 128; // 8-bit 是无符号的
            break;
          case 16:
            sample = view.getInt16(sampleOffset, isLittleEndian);
            sample = sample / 32768;
            break;
          case 24:
            // 24-bit 需要特殊处理
            const b0 = view.getUint8(sampleOffset);
            const b1 = view.getUint8(sampleOffset + 1);
            const b2 = view.getInt8(sampleOffset + 2); // 有符号最高位
            sample = (b2 << 16 | b1 << 8 | b0) / 8388608;
            break;
          case 32:
            if (format.audioFormat === 3) {
              // 32-bit float
              sample = view.getFloat32(sampleOffset, isLittleEndian);
            } else {
              // 32-bit integer
              sample = view.getInt32(sampleOffset, isLittleEndian) / 2147483648;
            }
            break;
          default:
            sample = 0;
        }

        channels[ch][i] = sample;
      }
    }

    return channels;
  }

  /**
   * 从原始 PCM 字节数据转换为 Float32Array（用于后续 chunk，不含 WAV 头）
   */
  function pcmToFloat32(pcmData, format) {
    const view = new DataView(pcmData);
    const numChannels = format.channels;
    const bitDepth = format.bitDepth;
    const bytesPerSample = bitDepth / 8;
    const totalSamples = Math.floor(pcmData.byteLength / (bytesPerSample * numChannels));

    const channels = [];
    for (let ch = 0; ch < numChannels; ch++) {
      channels.push(new Float32Array(totalSamples));
    }

    for (let i = 0; i < totalSamples; i++) {
      for (let ch = 0; ch < numChannels; ch++) {
        const sampleOffset = (i * numChannels + ch) * bytesPerSample;
        let sample;

        switch (bitDepth) {
          case 16:
            sample = view.getInt16(sampleOffset, true) / 32768;
            break;
          case 8:
            sample = (view.getUint8(sampleOffset) - 128) / 128;
            break;
          case 32:
            sample = view.getInt32(sampleOffset, true) / 2147483648;
            break;
          default:
            sample = 0;
        }

        channels[ch][i] = sample;
      }
    }

    return channels;
  }

  // ============================================================
  // 流式 TTS 播放器主类
  // ============================================================

  class StreamTTSPlayer {
    /**
     * 构造函数
     * @param {Object} options - 配置选项
     * @param {string} [options.apiBase='/v1/tts/stream'] - TTS 流式接口地址
     * @param {string} [options.speaker] - 默认说话人
     * @param {string} [options.emotion] - 默认情感
     * @param {number} [options.speed=1.0] - 默认语速 (0.5 - 2.0)
     * @param {number} [options.volume=1.0] - 默认音量 (0.0 - 1.0)
     * @param {string} [options.format='wav'] - 音频格式
     * @param {boolean} [options.autoReconnect=true] - 是否自动重连
     * @param {number} [options.maxReconnectAttempts=3] - 最大重连次数
     * @param {number} [options.reconnectDelay=1000] - 重连延迟（毫秒）
     * @param {Function} [options.onStart] - 开始播放回调
     * @param {Function} [options.onChunk] - 收到音频块回调
     * @param {Function} [options.onEnd] - 播放结束回调
     * @param {Function} [options.onError] - 错误回调
     * @param {Function} [options.onStreamEnd] - 流结束回调（所有数据接收完成）
     */
    constructor(options = {}) {
      // 配置
      this.apiBase = options.apiBase || '/v1/tts/stream';
      this.defaultSpeaker = options.speaker || '';
      this.defaultEmotion = options.emotion || '';
      this.defaultSpeed = options.speed !== undefined ? options.speed : 1.0;
      this._volume = options.volume !== undefined ? options.volume : 1.0;
      this.format = options.format || 'wav';
      this.autoReconnect = options.autoReconnect !== false;
      this.maxReconnectAttempts = options.maxReconnectAttempts || 3;
      this.reconnectDelay = options.reconnectDelay || 1000;

      // 事件回调
      this.onStart = options.onStart || null;
      this.onChunk = options.onChunk || null;
      this.onEnd = options.onEnd || null;
      this.onError = options.onError || null;
      this.onStreamEnd = options.onStreamEnd || null;

      // 内部状态
      this._state = 'idle'; // idle / connecting / streaming / playing / paused / stopped / error
      this._eventSource = null;
      this._audioContext = null;
      this._gainNode = null;
      this._format = null; // WAV 格式信息
      this._firstChunkReceived = false;

      // 播放队列：存储待播放的 AudioBuffer
      this._bufferQueue = [];
      this._currentSource = null;
      this._nextPlayTime = 0; // 下一个 buffer 应该开始播放的时间（AudioContext 时间）
      this._totalPlayedDuration = 0; // 已播放的总时长（秒）

      // 统计
      this._chunkCount = 0;
      this._totalBytesReceived = 0;
      this._streamComplete = false; // 流是否已经全部接收完成
      this._reconnectCount = 0;
      this._currentText = '';

      // 用于暂停/恢复
      this._pauseAtTime = 0; // 暂停时的 AudioContext 时间
      this._pauseOffset = 0; // 暂停时已播放的时长（秒）

      // 用于降级模式
      this._fallbackAudio = null;

      // 绑定方法（防止 this 丢失）
      this._onSSEMessage = this._onSSEMessage.bind(this);
      this._onSSEOpen = this._onSSEOpen.bind(this);
      this._onSSEError = this._onSSEError.bind(this);
    }

    // ============================================================
    // 公共属性
    // ============================================================

    /**
     * 当前播放状态
     * @returns {string} idle / connecting / streaming / playing / paused / stopped / error
     */
    get state() {
      return this._state;
    }

    /**
     * 是否正在播放
     */
    get isPlaying() {
      return this._state === 'playing' || this._state === 'streaming';
    }

    /**
     * 是否暂停
     */
    get isPaused() {
      return this._state === 'paused';
    }

    /**
     * 当前音量
     */
    get volume() {
      return this._volume;
    }

    set volume(value) {
      this._volume = Math.max(0, Math.min(1, value));
      if (this._gainNode) {
        this._gainNode.gain.value = this._volume;
      }
    }

    /**
     * 当前语速
     */
    get speed() {
      return this.defaultSpeed;
    }

    set speed(value) {
      this.defaultSpeed = Math.max(0.5, Math.min(2.0, value));
      // 注意：已在播放中的音频语速不会改变，只影响后续播放
    }

    /**
     * 获取已播放时长（秒）
     */
    get currentTime() {
      if (this._state === 'paused') {
        return this._pauseOffset;
      }
      if (this._audioContext && (this._state === 'playing' || this._state === 'streaming')) {
        return Math.max(0, this._audioContext.currentTime - this._playStartTime);
      }
      return 0;
    }

    /**
     * 检查浏览器是否支持流式播放
     * @returns {boolean}
     */
    static isStreamSupported() {
      return !!(window.EventSource && window.AudioContext && window.AudioBuffer);
    }

    // ============================================================
    // 公共方法 - 播放控制
    // ============================================================

    /**
     * 开始流式播放语音
     * @param {string} text - 要合成的文本
     * @param {Object} [options] - 可选参数
     * @param {string} [options.speaker] - 说话人
     * @param {string} [options.emotion] - 情感
     * @param {number} [options.speed] - 语速
     * @param {number} [options.volume] - 音量
     * @returns {Promise<boolean>} 是否成功开始
     */
    async speak(text, options = {}) {
      if (!text || !text.trim()) {
        return false;
      }

      // 先停止当前播放
      this.stop();

      this._currentText = text;
      const speaker = options.speaker || this.defaultSpeaker;
      const emotion = options.emotion || this.defaultEmotion;
      const speed = options.speed !== undefined ? options.speed : this.defaultSpeed;
      const volume = options.volume !== undefined ? options.volume : this._volume;

      this._volume = volume;

      // 检查是否支持流式播放
      if (!StreamTTSPlayer.isStreamSupported()) {
        console.warn('[StreamTTS] 浏览器不支持流式播放，使用降级模式');
        return this._speakFallback(text, { speaker, emotion, speed, volume });
      }

      try {
        this._setState('connecting');

        // 初始化 AudioContext
        await this._initAudioContext();

        // 重置状态
        this._resetState();

        // 构建 SSE URL
        const url = this._buildStreamUrl(text, { speaker, emotion, speed });

        console.log('[StreamTTS] 连接流式接口:', url);

        // 建立 SSE 连接
        this._eventSource = new EventSource(url);
        this._eventSource.addEventListener('open', this._onSSEOpen);
        this._eventSource.addEventListener('error', this._onSSEError);

        // 监听消息事件（默认 event 类型）
        this._eventSource.onmessage = this._onSSEMessage;

        // 监听自定义事件类型
        this._eventSource.addEventListener('tts_start', (e) => this._onTTSStart(e));
        this._eventSource.addEventListener('audio_chunk', (e) => this._onAudioChunk(e));
        this._eventSource.addEventListener('tts_end', (e) => this._onTTSEnd(e));
        this._eventSource.addEventListener('error', (e) => this._onTTSError(e));

        return true;
      } catch (e) {
        console.error('[StreamTTS] 启动流式播放失败:', e);
        this._setState('error');
        if (this.onError) this.onError(e);
        // 失败时尝试降级
        return this._speakFallback(text, { speaker, emotion, speed, volume });
      }
    }

    /**
     * 暂停播放
     * @returns {boolean} 是否成功暂停
     */
    pause() {
      if (this._state !== 'playing' && this._state !== 'streaming') {
        return false;
      }

      try {
        if (this._audioContext && this._audioContext.state === 'running') {
          this._pauseOffset = this._audioContext.currentTime - this._playStartTime;
          this._audioContext.suspend();
          this._setState('paused');
          return true;
        }
      } catch (e) {
        console.warn('[StreamTTS] 暂停失败:', e);
      }
      return false;
    }

    /**
     * 恢复播放
     * @returns {boolean} 是否成功恢复
     */
    resume() {
      if (this._state !== 'paused') {
        return false;
      }

      try {
        if (this._audioContext && this._audioContext.state === 'suspended') {
          // 调整播放开始时间，使 currentTime 计算正确
          this._playStartTime = this._audioContext.currentTime - this._pauseOffset;
          this._audioContext.resume();
          this._setState(this._streamComplete ? 'playing' : 'streaming');
          return true;
        }
      } catch (e) {
        console.warn('[StreamTTS] 恢复播放失败:', e);
      }
      return false;
    }

    /**
     * 停止播放并关闭连接
     */
    stop() {
      // 关闭 SSE 连接
      if (this._eventSource) {
        try {
          this._eventSource.close();
        } catch (e) { /* ignore */ }
        this._eventSource = null;
      }

      // 停止当前播放的音频
      if (this._currentSource) {
        try {
          this._currentSource.onended = null;
          this._currentSource.stop();
        } catch (e) { /* ignore */ }
        this._currentSource = null;
      }

      // 清空队列
      this._bufferQueue = [];

      // 关闭降级模式的音频
      if (this._fallbackAudio) {
        try {
          this._fallbackAudio.pause();
          this._fallbackAudio.currentTime = 0;
        } catch (e) { /* ignore */ }
        this._fallbackAudio = null;
      }

      // 重置状态
      this._state = 'idle';
      this._firstChunkReceived = false;
      this._format = null;
      this._streamComplete = false;
      this._reconnectCount = 0;
      this._chunkCount = 0;
      this._totalBytesReceived = 0;
      this._totalPlayedDuration = 0;
      this._nextPlayTime = 0;
    }

    /**
     * 打断当前播放（等同于 stop，语义更清晰）
     */
    interrupt() {
      this.stop();
    }

    /**
     * 销毁播放器，释放所有资源
     */
    destroy() {
      this.stop();

      if (this._audioContext) {
        try {
          this._audioContext.close();
        } catch (e) { /* ignore */ }
        this._audioContext = null;
      }

      this._gainNode = null;
      this._format = null;
    }

    // ============================================================
    // 私有方法 - 初始化
    // ============================================================

    /**
     * 初始化 AudioContext
     */
    async _initAudioContext() {
      if (this._audioContext) {
        // 如果已经关闭了，重新创建
        if (this._audioContext.state === 'closed') {
          this._audioContext = null;
        } else {
          // 确保处于运行状态
          if (this._audioContext.state === 'suspended') {
            await this._audioContext.resume();
          }
          return;
        }
      }

      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) {
        throw new Error('浏览器不支持 Web Audio API');
      }

      this._audioContext = new AudioContextClass();

      // 创建增益节点（音量控制）
      this._gainNode = this._audioContext.createGain();
      this._gainNode.gain.value = this._volume;
      this._gainNode.connect(this._audioContext.destination);
    }

    /**
     * 重置播放状态（保留 AudioContext）
     */
    _resetState() {
      this._bufferQueue = [];
      this._currentSource = null;
      this._firstChunkReceived = false;
      this._format = null;
      this._chunkCount = 0;
      this._totalBytesReceived = 0;
      this._streamComplete = false;
      this._reconnectCount = 0;
      this._totalPlayedDuration = 0;
      this._nextPlayTime = 0;
      this._pauseOffset = 0;
    }

    /**
     * 构建流式接口 URL
     */
    _buildStreamUrl(text, options) {
      const params = new URLSearchParams();
      params.append('text', text);
      params.append('format', this.format);

      if (options.speaker) params.append('speaker', options.speaker);
      if (options.emotion) params.append('emotion', options.emotion);
      if (options.speed !== undefined) params.append('speed', options.speed);

      return this.apiBase + '?' + params.toString();
    }

    // ============================================================
    // 私有方法 - SSE 事件处理
    // ============================================================

    _onSSEOpen() {
      console.log('[StreamTTS] SSE 连接已建立');
      // 连接建立后状态可能仍为 connecting，等收到 tts_start 或第一个 audio_chunk 再变
    }

    _onSSEError(event) {
      if (event.eventPhase === EventSource.CLOSED) {
        console.log('[StreamTTS] SSE 连接已关闭');

        // 如果是流已经完成后正常关闭，不做处理
        if (this._streamComplete) {
          return;
        }

        // 意外断开，尝试重连
        if (this.autoReconnect && this._reconnectCount < this.maxReconnectAttempts) {
          this._reconnectCount++;
          console.log(`[StreamTTS] 尝试重连 (${this._reconnectCount}/${this.maxReconnectAttempts})`);

          setTimeout(() => {
            if (this._state !== 'stopped' && this._state !== 'idle') {
              this._reconnectStream();
            }
          }, this.reconnectDelay * this._reconnectCount);
        } else {
          console.warn('[StreamTTS] SSE 连接断开，且无法重连');
          if (!this._streamComplete) {
            this._setState('error');
            if (this.onError) {
              this.onError(new Error('流式连接断开'));
            }
          }
        }
      } else if (event.eventPhase === EventSource.CONNECTING) {
        console.log('[StreamTTS] SSE 正在重连...');
      }
    }

    /**
     * 默认消息处理（未指定 event 类型的消息）
     */
    _onSSEMessage(event) {
      // 默认消息类型，尝试解析为 JSON
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'audio_chunk' || data.audio_data) {
          this._processAudioChunk(data);
        } else if (data.type === 'tts_start') {
          this._setState('streaming');
        } else if (data.type === 'tts_end') {
          this._streamComplete = true;
        } else if (data.type === 'error') {
          console.error('[StreamTTS] 服务端错误:', data.message);
          if (this.onError) this.onError(new Error(data.message || 'TTS 服务错误'));
        }
      } catch (e) {
        // 不是 JSON，可能是纯文本，忽略
      }
    }

    _onTTSStart(event) {
      console.log('[StreamTTS] 合成开始');
      this._setState('streaming');
    }

    _onAudioChunk(event) {
      try {
        const data = JSON.parse(event.data);
        this._processAudioChunk(data);
      } catch (e) {
        // 如果不是 JSON，可能是纯 base64 数据
        if (event.data && event.data.length > 0) {
          this._processAudioChunk({
            audio_data: event.data,
            chunk_index: this._chunkCount,
          });
        }
      }
    }

    _onTTSEnd(event) {
      console.log('[StreamTTS] 流接收完成，共', this._chunkCount, '个 chunk');
      this._streamComplete = true;

      // 关闭 SSE 连接（服务端已结束）
      if (this._eventSource) {
        this._eventSource.close();
        this._eventSource = null;
      }

      if (this.onStreamEnd) {
        this.onStreamEnd({
          chunkCount: this._chunkCount,
          totalBytes: this._totalBytesReceived,
        });
      }

      // 如果队列已经空了且不在播放中，触发结束
      if (this._bufferQueue.length === 0 && !this._currentSource) {
        this._handlePlaybackEnd();
      }
    }

    _onTTSError(event) {
      try {
        const data = JSON.parse(event.data);
        console.error('[StreamTTS] TTS 错误:', data.message || data);
        if (this.onError) this.onError(new Error(data.message || 'TTS 合成错误'));
      } catch (e) {
        console.error('[StreamTTS] TTS 错误:', event.data);
        if (this.onError) this.onError(new Error(event.data || 'TTS 合成错误'));
      }
      this._setState('error');
    }

    // ============================================================
    // 私有方法 - 音频数据处理
    // ============================================================

    /**
     * 处理一个音频 chunk
     */
    _processAudioChunk(data) {
      const base64Data = data.audio_data || data.data || data.chunk;
      if (!base64Data) return;

      try {
        const arrayBuffer = base64ToArrayBuffer(base64Data);
        this._totalBytesReceived += arrayBuffer.byteLength;
        this._chunkCount++;

        // 回调
        if (this.onChunk) {
          this.onChunk({
            index: this._chunkCount,
            bytes: arrayBuffer.byteLength,
            totalBytes: this._totalBytesReceived,
          });
        }

        if (!this._firstChunkReceived) {
          // 第一个 chunk：解析 WAV 头
          this._firstChunkReceived = true;
          const format = parseWavHeader(arrayBuffer);

          if (!format) {
            console.warn('[StreamTTS] 无法解析 WAV 头，尝试降级播放');
            this._fallbackFromChunk(arrayBuffer);
            return;
          }

          this._format = format;
          console.log('[StreamTTS] 音频格式:', format.sampleRate + 'Hz',
            format.channels + '声道', format.bitDepth + 'bit');

          // 提取第一个 chunk 的 PCM 数据
          const pcmData = arrayBuffer.slice(format.dataOffset, format.dataOffset + format.dataLength);
          this._enqueueAudioBuffer(pcmData);
        } else {
          // 后续 chunk：直接作为 PCM 数据处理
          this._enqueueAudioBuffer(arrayBuffer);
        }
      } catch (e) {
        console.error('[StreamTTS] 处理音频 chunk 失败:', e);
        if (this.onError) this.onError(e);
      }
    }

    /**
     * 将 PCM 数据转换为 AudioBuffer 并加入播放队列
     */
    _enqueueAudioBuffer(pcmData) {
      if (!this._format || !this._audioContext) return;

      // 转换为 Float32Array（每声道一个）
      const channelData = pcmToFloat32(pcmData, this._format);
      const numSamples = channelData[0].length;

      if (numSamples === 0) return;

      // 创建 AudioBuffer
      const audioBuffer = this._audioContext.createBuffer(
        this._format.channels,
        numSamples,
        this._format.sampleRate
      );

      // 填充数据
      for (let ch = 0; ch < this._format.channels; ch++) {
        audioBuffer.getChannelData(ch).set(channelData[ch]);
      }

      // 加入队列
      this._bufferQueue.push(audioBuffer);

      // 如果当前没有在播放，立即开始播放
      if (!this._currentSource && this._state !== 'paused') {
        this._playNextBuffer();
      }
    }

    /**
     * 播放队列中的下一个 buffer
     */
    _playNextBuffer() {
      if (this._bufferQueue.length === 0) {
        // 队列为空，如果流已经完成，则结束播放
        if (this._streamComplete) {
          this._handlePlaybackEnd();
        }
        return;
      }

      if (!this._audioContext || !this._gainNode) return;

      const buffer = this._bufferQueue.shift();
      const source = this._audioContext.createBufferSource();
      source.buffer = buffer;
      source.connect(this._gainNode);

      // 计算开始播放的时间
      const now = this._audioContext.currentTime;
      let startTime;

      if (this._nextPlayTime > now) {
        startTime = this._nextPlayTime;
      } else {
        startTime = now + 0.02; // 稍微延迟一点，减少爆音
        // 如果这是第一个 buffer，记录播放开始时间
        if (this._totalPlayedDuration === 0) {
          this._playStartTime = startTime;
        }
      }

      // 更新下一次播放时间（无缝衔接）
      this._nextPlayTime = startTime + buffer.duration;

      // 播放结束回调
      source.onended = () => {
        if (source === this._currentSource) {
          this._totalPlayedDuration += buffer.duration;
          this._currentSource = null;
          // 继续播放下一个
          this._playNextBuffer();
        }
      };

      source.start(startTime);
      this._currentSource = source;

      // 首次播放触发 onStart
      if (this._state === 'streaming' && this._chunkCount === 1) {
        this._setState('streaming'); // 保持 streaming 状态（同时接收和播放）
        if (this.onStart) {
          this.onStart({
            sampleRate: this._format.sampleRate,
            channels: this._format.channels,
            bitDepth: this._format.bitDepth,
          });
        }
      } else if (this._state === 'idle' && this._streamComplete) {
        // 流已经完成后的播放（比如暂停后恢复的情况）
        this._setState('playing');
      }
    }

    /**
     * 播放结束处理
     */
    _handlePlaybackEnd() {
      if (this._state === 'stopped' || this._state === 'idle') return;

      this._setState('idle');
      this._currentSource = null;

      if (this.onEnd) {
        this.onEnd({
          chunkCount: this._chunkCount,
          totalBytes: this._totalBytesReceived,
          duration: this._totalPlayedDuration,
        });
      }
    }

    // ============================================================
    // 私有方法 - 重连
    // ============================================================

    /**
     * 重新连接流式接口（续传）
     * 注意：这需要后端支持断点续传，否则会重新开始
     */
    _reconnectStream() {
      if (this._state === 'stopped' || this._state === 'idle') return;

      try {
        // 简单重连：重新请求完整文本
        // 更完善的方案可以记录已接收的数据量并请求续传
        const url = this._buildStreamUrl(this._currentText, {
          speaker: this.defaultSpeaker,
          emotion: this.defaultEmotion,
          speed: this.defaultSpeed,
        });

        this._eventSource = new EventSource(url);
        this._eventSource.onmessage = this._onSSEMessage;
        this._eventSource.addEventListener('tts_start', (e) => this._onTTSStart(e));
        this._eventSource.addEventListener('audio_chunk', (e) => this._onAudioChunk(e));
        this._eventSource.addEventListener('tts_end', (e) => this._onTTSEnd(e));
        this._eventSource.addEventListener('error', (e) => this._onTTSError(e));

        console.log('[StreamTTS] 重连成功');
      } catch (e) {
        console.error('[StreamTTS] 重连失败:', e);
      }
    }

    // ============================================================
    // 私有方法 - 降级模式
    // ============================================================

    /**
     * 降级为完整音频播放（不支持流式时使用）
     */
    async _speakFallback(text, options) {
      console.log('[StreamTTS] 使用降级模式：完整音频播放');

      try {
        // 使用非流式接口
        let url = this.apiBase.replace('/stream', '');
        if (!url.endsWith('/tts')) {
          url = this.apiBase.replace('/stream', '/tts');
        }

        const params = new URLSearchParams();
        params.append('text', text);
        params.append('format', this.format);
        if (options.speaker) params.append('speaker', options.speaker);
        if (options.emotion) params.append('emotion', options.emotion);
        if (options.speed !== undefined) params.append('speed', options.speed);

        const fullUrl = url + '?' + params.toString();

        this._fallbackAudio = new Audio(fullUrl);
        this._fallbackAudio.volume = this._volume;

        this._fallbackAudio.onplay = () => {
          this._setState('playing');
          if (this.onStart) this.onStart({ fallback: true });
        };

        this._fallbackAudio.onended = () => {
          this._setState('idle');
          if (this.onEnd) this.onEnd({ fallback: true });
          this._fallbackAudio = null;
        };

        this._fallbackAudio.onerror = (e) => {
          console.warn('[StreamTTS] 降级播放也失败了:', e);
          this._setState('error');
          if (this.onError) this.onError(new Error('音频播放失败'));
          this._fallbackAudio = null;
        };

        await this._fallbackAudio.play();
        return true;
      } catch (e) {
        console.error('[StreamTTS] 降级模式失败:', e);
        this._setState('error');
        if (this.onError) this.onError(e);
        return false;
      }
    }

    /**
     * 当流式播放中途失败时，用已收到的数据降级
     */
    _fallbackFromChunk(firstChunkBuffer) {
      // 如果第一个 chunk 解析失败，尝试用完整文件播放
      // 这里我们转为降级模式
      console.warn('[StreamTTS] WAV 解析失败，切换到降级模式');

      this.stop();

      // 重新用非流式方式请求
      this._speakFallback(this._currentText, {
        speaker: this.defaultSpeaker,
        emotion: this.defaultEmotion,
        speed: this.defaultSpeed,
        volume: this._volume,
      });
    }

    // ============================================================
    // 私有方法 - 状态管理
    // ============================================================

    _setState(newState) {
      if (this._state === newState) return;
      this._state = newState;
      // 可以在这里添加状态变化的回调（如果需要）
    }
  }

  // ============================================================
  // 导出
  // ============================================================

  // 同时挂载到 window 和 module.exports
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = StreamTTSPlayer;
  }

  if (typeof window !== 'undefined') {
    window.StreamTTSPlayer = StreamTTSPlayer;
  }

  // ============================================================
  // 使用示例
  // ============================================================
  /*
   * 基础用法：
   *
   *   const player = new StreamTTSPlayer({
   *     apiBase: '/api/voice/tts/stream',
   *     speaker: 'yunxi_default',
   *     emotion: 'warm',
   *     speed: 1.0,
   *     volume: 0.8,
   *     onStart: (info) => console.log('开始播放', info),
   *     onChunk: (info) => console.log('收到chunk', info.index, info.bytes + '字节'),
   *     onEnd: (info) => console.log('播放结束，总时长', info.duration + 's'),
   *     onError: (err) => console.error('播放错误', err),
   *   });
   *
   *   // 播放
   *   player.speak('你好，我是云汐！');
   *
   *   // 暂停
   *   player.pause();
   *
   *   // 恢复
   *   player.resume();
   *
   *   // 停止/打断
   *   player.stop();
   *   // 或
   *   player.interrupt();
   *
   *   // 调节音量
   *   player.volume = 0.5;
   *
   *   // 调节语速（影响下一次播放）
   *   player.speed = 1.2;
   *
   *   // 检查浏览器支持
   *   if (StreamTTSPlayer.isStreamSupported()) {
   *     console.log('支持流式播放');
   *   }
   *
   *   // 在 YunxiVoice 中集成：
   *   // 将 StreamTTSPlayer 作为 YunxiVoice 的后端 TTS 播放器
   *   // 替换 _speak_backend 方法中的 Audio 元素播放
   *
   * 与 YunxiVoice 集成示例：
   *
   *   // 在 YunxiVoice 的构造函数中添加：
   *   this.streamPlayer = new StreamTTSPlayer({
   *     apiBase: this.apiBase + '/tts/stream',
   *     onStart: () => { this.isSpeaking = true; if(this.onSpeakingStart) this.onSpeakingStart(); },
   *     onEnd: () => { this.isSpeaking = false; if(this.onSpeakingEnd) this.onSpeakingEnd(); },
   *     onError: (e) => { console.warn('流式TTS失败:', e); this._speak_browser(text, { speed, pitch }); },
   *   });
   *
   *   // 然后在 speak 方法中优先使用流式播放器
   *   async speak(text, options = {}) {
   *     this.stopSpeaking();
   *     // ...
   *     if (status.tts_available && StreamTTSPlayer.isStreamSupported()) {
   *       await this.streamPlayer.speak(text, {
   *         speaker: voiceType,
   *         speed: speed,
   *       });
   *     } else {
   *       // 降级
   *       await this._speak_backend(text, voiceType, speed, pitch);
   *     }
   *   }
   *
   *   // stopSpeaking 中添加：
   *   if (this.streamPlayer) this.streamPlayer.stop();
   *
   * SSE 服务端示例（Python FastAPI）：
   *
   *   from fastapi import FastAPI
   *   from fastapi.responses import StreamingResponse
   *   import json, base64
   *
   *   @app.get("/v1/tts/stream")
   *   async def tts_stream(text: str, speaker: str = "", emotion: str = "", speed: float = 1.0, format: str = "wav"):
   *       async def generate():
   *           # 发送开始事件
   *           yield f"event: tts_start\ndata: {json.dumps({'text': text})}\n\n"
   *
   *           # 逐块生成音频
   *           for i, chunk in enumerate(tts_engine.stream(text, speaker, speed)):
   *               # chunk 是 WAV 格式的字节数据
   *               b64_data = base64.b64encode(chunk).decode('utf-8')
   *               yield f"event: audio_chunk\ndata: {json.dumps({'chunk_index': i, 'audio_data': b64_data})}\n\n"
   *
   *           # 发送结束事件
   *           yield f"event: tts_end\ndata: {json.dumps({'chunk_count': i+1})}\n\n"
   *
   *       return StreamingResponse(generate(), media_type="text/event-stream")
   *
   * 注意事项：
   * 1. 第一个 audio_chunk 必须包含完整的 WAV 头（44字节 + 初始音频数据）
   * 2. 后续 chunk 只包含原始 PCM 数据（不带 WAV 头）
   * 3. 所有 chunk 必须使用相同的采样率、声道数、位深
   * 4. 建议每个 chunk 时长在 0.5-2 秒之间，平衡延迟和流畅度
   */

})(typeof window !== 'undefined' ? window : globalThis);
