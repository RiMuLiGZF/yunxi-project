# CosyVoice 集成语音系统 - 部署指南

## 概述

云汐语音系统现已集成 CosyVoice 2.0/3.0，提供**高质量、富情感、可定制**的语音合成能力。

**核心特性：**
- 🎙️ **零样本语音克隆** - 3秒音频复刻任意音色，打造云汐专属声音
- 🎭 **情感韵律控制** - 支持12种情感+6种场景+语速/语调/音量细粒度调节
- 🌐 **多语言多方言** - 9种语言+18种中文方言，跨语言音色克隆
- ⚡ **流式推理** - 首包延迟低至150ms，实时交互体验
- 🎨 **5套内置音色预设** - 温柔/活泼/沉稳/专业/共情，覆盖全场景

---

## 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│                        前端 / M4 场景引擎                      │
│                   voice.js (播放 + ASR + 唤醒)                 │
└─────────────────────────────┬────────────────────────────────┘
                              │ HTTP API
┌─────────────────────────────▼────────────────────────────────┐
│                   M8 控制塔 - 语音网关层                        │
│  ┌──────────────┐  ┌────────────────┐  ┌─────────────────┐  │
│  │ /api/voice   │  │ /api/voice/    │  │ 韵律控制器       │  │
│  │ (TTS/ASR/VAD)│  │ presets (音色) │  │ ProsodyCtrl     │  │
│  └──────┬───────┘  └────────┬───────┘  └────────┬────────┘  │
└─────────┼───────────────────┼────────────────────┼───────────┘
          │                   │                    │
          ▼                   ▼                    ▼
┌──────────────────────────────────────────────────────────────┐
│                    shared/ 共享引擎层                           │
│  ┌──────────────┐  ┌────────────────┐  ┌─────────────────┐  │
│  │ voice_engine │  │ voice_preset   │  │ prosody_        │  │
│  │ (TTS统一入口) │  │ _manager       │  │ controller      │  │
│  └──────┬───────┘  └────────┬───────┘  └────────┬────────┘  │
└─────────┼───────────────────┼────────────────────┼───────────┘
          │                   │                    │
          └───────────────────┬────────────────────┘
                              │ HTTP
                ┌─────────────▼─────────────┐
                │   CosyVoice 服务 (独立进程)  │
                │   cosyvoice_service.py     │
                │   - 零样本克隆             │
                │   - 指令控制               │
                │   - 跨语言合成             │
                │   - 流式推理               │
                └───────────────────────────┘
                              │ GPU (RTX 5060 8GB)
                ┌─────────────▼─────────────┐
                │   CosyVoice 2.0/3.0 模型   │
                │   (500M 参数)              │
                └───────────────────────────┘
```

---

## 快速开始

### 前置要求

- **GPU**: NVIDIA GPU，显存 ≥ 6GB（推荐 8GB+）
- **CUDA**: 11.8 或更高版本
- **Python**: 3.10
- **磁盘空间**: ≥ 10GB（模型权重 ~2GB + 依赖 ~5GB）

### 步骤一：部署 CosyVoice 服务

#### 方式 A：WSL2 + Ubuntu（推荐）

```bash
# 1. 安装 WSL2 Ubuntu
wsl --install -d Ubuntu-22.04

# 2. 在 WSL2 中安装 Miniconda
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh

# 3. 创建环境
conda create -n cosyvoice python=3.10 -y
conda activate cosyvoice

# 4. 安装 PyTorch (CUDA 12.1)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 5. 克隆 CosyVoice 仓库
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git
cd CosyVoice
git submodule update --init --recursive

# 6. 安装依赖
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# 7. 下载模型 (使用 ModelScope，国内速度快)
pip install modelscope
python -c "
from modelscope import snapshot_download
snapshot_download('iic/CosyVoice2-0.5B', local_dir='./models/CosyVoice2-0.5B')
snapshot_download('iic/CosyVoice-ttsfrd', local_dir='./pretrained_models/CosyVoice-ttsfrd')
"

# 8. 复制云汐的服务文件
cp /mnt/c/云汐/工作台/yunxi-project/shared/cosyvoice_service.py .

# 9. 启动服务
export COSYVOICE_MODEL_DIR=./models/CosyVoice2-0.5B
export COSYVOICE_DEVICE=cuda
export COSYVOICE_PORT=50000
python cosyvoice_service.py
```

#### 方式 B：Docker（最简单）

```bash
# 待官方 Docker 镜像完善后使用
# docker run -d --gpus all -p 50000:50000 \
#   -v ./models:/models \
#   -e COSYVOICE_MODEL_DIR=/models/CosyVoice2-0.5B \
#   cosyvoice:latest
```

### 步骤二：配置云汐系统

设置环境变量（或在 M8 控制塔配置面板中设置）：

```bash
# 启用 CosyVoice
export USE_COSYVOICE=true
export COSYVOICE_API_URL=http://localhost:50000
export COSYVOICE_SPEAKER_ID=yunxi_warm
export COSYVOICE_EMOTION=warm
export COSYVOICE_METHOD=instruct
```

或通过 API 动态配置：

```bash
# 更新语音配置
curl -X PUT http://localhost:8000/api/voice/config \
  -H "Content-Type: application/json" \
  -d '{
    "use_cosyvoice": true,
    "cosyvoice_api_url": "http://localhost:50000",
    "cosyvoice_speaker_id": "yunxi_warm",
    "cosyvoice_emotion": "warm",
    "cosyvoice_method": "instruct"
  }'
```

### 步骤三：设置云汐专属音色

#### 方式 A：上传参考音频

1. 准备一段 3-10 秒的清晰语音（WAV 格式最佳）
2. 通过 API 上传并创建自定义音色：

```bash
curl -X POST http://localhost:8000/api/voice/presets/presets \
  -F "name=我的云汐" \
  -F "description=温柔的女声，像知心姐姐一样" \
  -F "style=warm" \
  -F "reference_text=希望你以后能够做的比我还好呦。" \
  -F "audio_file=@my_voice.wav"
```

3. 激活该音色：

```bash
curl -X PUT http://localhost:8000/api/voice/presets/presets/{preset_id}/activate
```

4. 注册到 CosyVoice 服务：

```bash
curl -X POST http://localhost:8000/api/voice/presets/cosyvoice/register
```

#### 方式 B：使用内置预设（需配置参考音频）

内置 5 套音色预设，为每套预设上传参考音频即可激活：

| 预设ID | 名称 | 适用场景 |
|--------|------|---------|
| yunxi_warm | 温柔云汐 | 日常陪伴、情感支持 |
| yunxi_playful | 活泼云汐 | 轻松聊天、娱乐互动 |
| yunxi_calm | 沉稳云汐 | 工作讨论、学习辅导 |
| yunxi_professional | 专业云汐 | 代码讲解、技术文档 |
| yunxi_empathetic | 共情云汐 | 心理疏导、深度倾听 |

---

## API 参考

### TTS 语音合成

```http
POST /api/voice/tts/synthesize
Content-Type: application/json

{
  "text": "你好，我是云汐，很高兴认识你！",
  "emotion": "warm",           // 情感：warm/happy/sad/calm/excited...
  "scene": "emotion_companion", // 场景：work_dev/study_plan/...
  "voice_preset": "yunxi_warm", // 音色预设ID
  "speed": 1.0,                // 语速倍率
  "pitch": 1.0,                // 音调倍率
  "instruction": "用温柔的语气说" // 自定义指令（优先）
}
```

### 音色管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/voice/presets/presets` | GET | 列出所有音色预设 |
| `/api/voice/presets/presets/{id}` | GET | 获取指定音色详情 |
| `/api/voice/presets/presets` | POST | 创建自定义音色 |
| `/api/voice/presets/presets/{id}` | DELETE | 删除音色 |
| `/api/voice/presets/presets/{id}/activate` | PUT | 激活音色 |
| `/api/voice/presets/presets/{id}/audio` | POST | 上传参考音频 |
| `/api/voice/presets/active` | GET | 获取当前激活音色 |
| `/api/voice/presets/for-scene/{scene}` | GET | 获取场景推荐音色 |
| `/api/voice/presets/cosyvoice/status` | GET | CosyVoice 服务状态 |
| `/api/voice/presets/cosyvoice/register` | POST | 注册音色到 CosyVoice |

### 情感类型

| 情感 | 说明 | 适用场景 |
|------|------|---------|
| warm | 温暖温柔 | 日常对话、问候 |
| happy | 开心愉悦 | 好消息、庆祝 |
| sad | 忧伤难过 | 安慰、共情 |
| calm | 平静沉稳 | 工作、学习 |
| excited | 兴奋激动 | 鼓励、惊喜 |
| gentle | 轻柔温和 | 睡前、放松 |
| serious | 严肃认真 | 重要事项 |
| playful | 俏皮活泼 | 娱乐、游戏 |
| thoughtful | 若有所思 | 深度思考 |
| encouraging | 鼓励支持 | 加油打气 |
| empathetic | 共情理解 | 心理支持 |

### 方言支持

| 方言 | 指令关键词 |
|------|-----------|
| 四川话 | `dialect: sichuan` |
| 东北话 | `dialect: dongbei` |
| 陕西话 | `dialect: shaanxi` |
| 广东话 | `dialect: cantonese` |
| 闽南话 | `dialect: minnan` |
| 上海话 | `dialect: shanghai` |
| 天津话 | `dialect: tianjin` |

---

## 韵律控制原理

### 计算链路

```
五维人格参数
    ↓
基础韵律（语速/音调/音量）
    ↓
场景偏移（work_dev/emotion_companion...）
    ↓
模式微调（CODING/DESIGN/MENTAL...）
    ↓
情感强化（happy/sad/excited...）
    ↓
用户偏好（语速/音量/方言）
    ↓
参数钳位（确保在合理范围）
    ↓
CosyVoice 指令 / SSML
```

### 人格 → 韵律映射

| 人格维度 | 影响 |
|---------|------|
| 温暖度↑ | 音调↑、音量↓、更柔和 |
| 理性度↑ | 语速↓、音调稳、停顿↑ |
| 幽默度↑ | 语速变化↑、语调起伏↑ |
| 共情感↑ | 语速↓、停顿↑、更轻柔 |
| 可靠度↑ | 语速稳、音调↓、音量适中 |

---

## 性能指标

| 指标 | CosyVoice 2.0 | CosyVoice 3.0 |
|------|:---:|:---:|
| 模型参数 | 500M | 500M |
| 显存需求 | ~6-8GB | ~6-8GB |
| RTF (RTX 3090) | 0.25-0.30 | 0.20-0.25 |
| 流式首包延迟 | 200-300ms | 150-200ms |
| 说话人相似度 | 75.7% | 78.0% |
| 支持语言 | 6-7种 | 9种+18方言 |
| 指令控制 | ✅ | ✅ (增强) |

> **RTF (Real-Time Factor)**: 实时因子，< 1 表示比实时快。
> 例如 RTF=0.3 表示生成 1 秒音频需要 0.3 秒。

---

## 故障排查

### CosyVoice 服务无法启动

1. **检查 CUDA 是否可用**
   ```bash
   python -c "import torch; print(torch.cuda.is_available())"
   ```

2. **检查模型文件是否完整**
   ```bash
   ls -lh models/CosyVoice2-0.5B/
   ```

3. **查看详细错误日志**
   - 确保所有依赖正确安装
   - 检查 `third_party/Matcha-TTS` 是否正确 clone

### 语音合成失败，自动降级到 edge-tts

1. 检查 CosyVoice 服务是否运行：
   ```bash
   curl http://localhost:50000/health
   ```

2. 检查参考音频是否配置：
   ```bash
   curl http://localhost:8000/api/voice/presets/active
   ```

3. 查看 M8 控制塔日志，定位具体错误

### 音色克隆效果不好

1. **参考音频质量**：确保 3-10 秒、清晰无噪音、完整语句
2. **参考文本准确性**：与音频内容完全一致效果最佳
3. **尝试不同预设**：不同风格的参考音频适合不同场景
4. **使用 CosyVoice 3.0**：v3 的相似度更高

---

## 文件清单

| 文件 | 位置 | 说明 |
|------|------|------|
| `cosyvoice_client.py` | `shared/` | CosyVoice HTTP 客户端 |
| `cosyvoice_service.py` | `shared/` | CosyVoice FastAPI 服务端 |
| `prosody_controller.py` | `shared/` | 韵律控制器（人格→语音映射） |
| `voice_preset_manager.py` | `shared/` | 音色预设管理器 |
| `voice_engine.py` | `shared/` | TTS 统一入口（已更新） |
| `voice.py` | `M8-control-tower/backend/routers/` | 语音路由（已更新） |
| `voice_presets.py` | `M8-control-tower/backend/routers/` | 音色管理路由（新增） |
| `main.py` | `M8-control-tower/backend/` | 主入口（已更新） |

---

## 下一步

- [ ] 前端 voice.js 增加情感和音色选择 UI
- [ ] M4 appearance 模块集成语音形象配置
- [ ] M1 Voice Agent 人格润色 → 韵律控制联动
- [ ] 流式 TTS 支持（边生成边播放）
- [ ] 多音色场景自动切换
