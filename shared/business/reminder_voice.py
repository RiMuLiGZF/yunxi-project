"""
提醒语音播报集成
将情景感知引擎的提醒与TTS语音服务对接，实现提醒到点自动语音播报
"""

import os
import asyncio
import threading
from typing import Optional, Dict, Any
from pathlib import Path

from .context_aware import get_context_engine, Reminder


class ReminderVoiceNotifier:
    """提醒语音播报器 - 单例模式"""

    _instance = Optional["ReminderVoiceNotifier"]

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, tts_base_url: Optional[str] = None):
        if self._initialized:
            return
        self._initialized = True

        # TTS服务地址
        self._tts_base_url = tts_base_url or os.environ.get(
            "TTS_BASE_URL", "http://localhost:8006"
        )

        # 播报队列（避免多个提醒同时播报）
        self._播报_queue = []
        self._is_playing = False
        self._lock = threading.RLock()

        # 播报线程
        self._stop_event = threading.Event()
        self._player_thread: Optional[threading.Thread] = None

        # 默认播报配置
        self._default_config = {
            "voice": "default",
            "speed": 1.0,
            "emotion": "neutral",
            "volume": 1.0,
        }

    def start(self):
        """启动语音播报器"""
        # 注册提醒回调
        context_engine = get_context_engine()
        context_engine.add_reminder_callback(self._on_reminder_triggered)

        # 启动播报线程
        self._player_thread = threading.Thread(
            target=self._play_loop, daemon=True, name="reminder-voice-player"
        )
        self._player_thread.start()

        print("[ReminderVoiceNotifier] 提醒语音播报器已启动")

    def stop(self):
        """停止语音播报器"""
        self._stop_event.set()
        if self._player_thread:
            self._player_thread.join(timeout=5)
        print("[ReminderVoiceNotifier] 提醒语音播报器已停止")

    def _on_reminder_triggered(self, reminder: Reminder):
        """提醒触发回调（同步，快速入队返回）"""
        try:
            # 检查提醒是否配置了语音播报
            notify_methods = reminder.notify_methods or []
            if "voice" not in notify_methods and "all" not in notify_methods:
                return  # 没有配置语音播报，跳过

            # 构建播报文本
            speak_text = self._build_announcement_text(reminder)

            # 获取播报配置
            config = self._get_voice_config(reminder)

            # 加入播报队列
            with self._lock:
                self._播报_queue.append({
                    "text": speak_text,
                    "reminder_id": reminder.id,
                    "title": reminder.title,
                    "config": config,
                })

            print(f"[ReminderVoiceNotifier] 提醒已加入播报队列: {reminder.title}")
        except Exception as e:
            print(f"[ReminderVoiceNotifier] 处理提醒回调异常: {e}")

    def _build_announcement_text(self, reminder: Reminder) -> str:
        """构建提醒播报文本"""
        priority_text = ""
        if reminder.priority == "high":
            priority_text = "重要提醒，"
        elif reminder.priority == "urgent":
            priority_text = "紧急提醒，请注意，"

        title_text = f"{reminder.title}"

        desc_text = ""
        if reminder.description:
            # 描述过长时截断
            desc = reminder.description
            if len(desc) > 50:
                desc = desc[:50] + "..."
            desc_text = f"，{desc}"

        # 构建完整播报语
        full_text = f"{priority_text}{title_text}{desc_text}"

        return full_text

    def _get_voice_config(self, reminder: Reminder) -> Dict[str, Any]:
        """获取提醒的语音配置"""
        config = self._default_config.copy()

        # 从metadata中读取语音配置
        if reminder.metadata and "voice_config" in reminder.metadata:
            voice_config = reminder.metadata["voice_config"]
            config.update(voice_config)

        # 根据优先级调整语速和情感
        if reminder.priority == "high":
            config["speed"] = config.get("speed", 1.0) * 1.1
            config["emotion"] = "serious"
        elif reminder.priority == "urgent":
            config["speed"] = config.get("speed", 1.0) * 1.2
            config["emotion"] = "urgent"

        return config

    def _play_loop(self):
        """播报循环（后台线程）"""
        import time

        while not self._stop_event.is_set():
            item = None
            with self._lock:
                if self._播报_queue and not self._is_playing:
                    item = self._播报_queue.pop(0)
                    self._is_playing = True

            if item:
                try:
                    self._play_announcement(item)
                except Exception as e:
                    print(f"[ReminderVoiceNotifier] 播报异常: {e}")
                finally:
                    with self._lock:
                        self._is_playing = False
            else:
                # 没有待播报项，等待
                time.sleep(1)

    def _play_announcement(self, item: Dict[str, Any]):
        """播放单条提醒

        优先使用TTS服务生成语音，失败则用系统默认提示音
        """
        text = item["text"]
        config = item["config"]

        try:
            # 尝试调用TTS服务生成并播放
            self._play_via_tts(text, config)
        except Exception as e:
            print(f"[ReminderVoiceNotifier] TTS播报失败: {e}，尝试系统蜂鸣")
            # 降级：系统蜂鸣提示
            self._play_system_beep(item.get("priority", "normal"))

    def _play_via_tts(self, text: str, config: Dict[str, Any]):
        """通过TTS服务播放语音"""
        import httpx

        # 调用TTS合成接口
        url = f"{self._tts_base_url}/api/voice/tts/synthesize"
        payload = {
            "text": text,
            "voice": config.get("voice", "default"),
            "speed": config.get("speed", 1.0),
            "emotion": config.get("emotion", "neutral"),
            "format": "wav",
        }

        try:
            import httpx
            resp = httpx.post(url, json=payload, timeout=30.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    audio_url = data.get("data", {}).get("audio_url", "")
                    if audio_url:
                        # 播放音频文件
                        self._play_audio_file(audio_url)
                        return
        except Exception:
            pass

        # 备用：直接播放音频文件路径
        audio_path = config.get("audio_path")
        if audio_path and Path(audio_path).exists():
            self._play_audio_file(audio_path)
            return

        raise Exception("TTS服务不可用")

    def _play_audio_file(self, audio_path: str):
        """播放音频文件（平台自适应）"""
        import sys
        import subprocess

        if sys.platform == "win32":
            # Windows: 使用 winsound 或 System.Media
            try:
                import winsound
                if audio_path.startswith("http"):
                    # URL音频，先下载再播放
                    self._play_url_audio_windows(audio_path)
                else:
                    winsound.PlaySound(audio_path, winsound.SND_FILENAME)
            except ImportError:
                # 降级：简单蜂鸣
                self._play_system_beep("normal")
        elif sys.platform == "darwin":
            # macOS: afplay
            subprocess.run(["afplay", audio_path], check=False, timeout=30)
        else:
            # Linux: aplay / paplay
            try:
                subprocess.run(["paplay", audio_path], check=False, timeout=30)
            except Exception:
                subprocess.run(["aplay", audio_path], check=False, timeout=30)

    def _play_url_audio_windows(self, url: str):
        """Windows下播放URL音频"""
        import tempfile
        import httpx
        import winsound

        try:
            resp = httpx.get(url, timeout=30.0)
            if resp.status_code == 200:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(resp.content)
                    temp_path = f.name

                winsound.PlaySound(temp_path, winsound.SND_FILENAME)

                # 清理临时文件
                import os
                os.unlink(temp_path)
        except Exception:
            self._play_system_beep("normal")

    def _play_system_beep(self, priority: str):
        """系统蜂鸣提示（降级方案）"""
        import sys

        if sys.platform == "win32":
            try:
                import winsound
                if priority == "urgent":
                    # 急促的连续蜂鸣
                    for _ in range(3):
                        winsound.Beep(1000, 200)
                elif priority == "high":
                    winsound.Beep(800, 500)
                else:
                    winsound.Beep(600, 300)
            except Exception:
                pass
        else:
            # 终端响铃
            print("\a")


# 全局单例获取函数
_voice_notifier = None


def get_reminder_voice_notifier() -> ReminderVoiceNotifier:
    """获取提醒语音播报器单例"""
    global _voice_notifier
    if _voice_notifier is None:
        _voice_notifier = ReminderVoiceNotifier()
    return _voice_notifier
