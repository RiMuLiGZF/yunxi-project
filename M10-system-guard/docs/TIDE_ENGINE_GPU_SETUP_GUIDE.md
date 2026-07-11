# M10 潮汐引擎 - GPU 环境配置与人工操作指南

> 版本：v1.0
> 适用模块：M10-system-guard
> 用途：潮汐引擎 GPU 资源调度依赖 NVIDIA GPU 硬件环境，本文档指导人工完成 NVIDIA 驱动、CUDA、cuDNN 等基础环境安装配置。

---

## 一、为什么需要人工配置

潮汐引擎的核心能力是**实时感知 GPU 资源水位**并据此进行潮汐调度。这依赖以下硬件/软件基础：

| 依赖 | 作用 | 能否自动安装 |
|------|------|:---:|
| NVIDIA GPU 驱动 | 操作系统级 GPU 识别与控制 | ❌ 需手动下载安装 |
| NVIDIA SMI (nvidia-smi) | GPU 状态查询命令行工具 | ✅ 随驱动自带 |
| NVML (NVIDIA Management Library) | Python 访问 GPU 指标的接口 | ✅ pynvml / nvidia-ml-py 包 |
| CUDA Toolkit (可选) | GPU 计算开发环境（推理/训练用） | ❌ 需手动下载安装 |
| cuDNN (可选) | 深度神经网络加速库 | ❌ 需手动下载安装 |

**潮汐引擎自身只依赖 NVML 即可工作**（通过 `nvidia-smi` 获取显存/利用率数据）。如果你的系统已经能跑 `nvidia-smi`，那潮汐引擎就能直接用。CUDA 和 cuDNN 是给 M5/M7/M9 等模块实际跑 GPU 计算任务用的。

---

## 二、快速检查：你的 GPU 环境是否就绪

### 2.1 检查 NVIDIA 驱动

打开命令行（PowerShell 或 CMD），执行：

```powershell
nvidia-smi
```

如果输出类似下面的表格，说明驱动已安装：

```
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 536.67       Driver Version: 536.67       CUDA Version: 12.2     |
|-------------------------------+----------------------+----------------------+
| GPU  Name            TCC/WDDM | Bus-Id        Disp.A | Volatile Uncorr. ECC |
| Fan  Temp  Perf  Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |
|                               |                      |               MIG M. |
|===============================+======================+======================|
|   0  NVIDIA GeForce ...  WDDM  | 00000000:01:00.0  On |                  N/A |
| N/A   45C    P8     5W /  N/A |    512MiB /  6144MiB |      2%      Default |
+-------------------------------+----------------------+----------------------+
```

**关键信息解读：**
- `Driver Version: 536.67` → 驱动版本 ✅
- `CUDA Version: 12.2` → 驱动支持的最高 CUDA 版本
- `GPU 0` → GPU 编号（从 0 开始）
- `6144MiB` → 总显存
- `2%` → 当前 GPU 利用率

### 2.2 检查 Python NVML 包

```powershell
python -c "import pynvml; pynvml.nvmlInit(); print(f'GPU 数量: {pynvml.nvmlDeviceGetCount()}'); pynvml.nvmlShutdown()"
```

如果输出 `GPU 数量: X` 且 X ≥ 1，说明 NVML Python 绑定也可用。

### 2.3 检查 CUDA（可选）

```powershell
nvcc -V
```

如果输出版本信息，说明 CUDA Toolkit 已安装。

---

## 三、人工配置步骤

### 步骤 1：安装 NVIDIA GPU 驱动

> **适用场景**：`nvidia-smi` 命令找不到或报错

1. **确定你的 GPU 型号**
   - 方法一：设备管理器 → 显示适配器
   - 方法二：PowerShell 执行 `Get-WmiObject Win32_VideoController | Select-Object Name`

2. **下载对应驱动**
   - 访问 NVIDIA 官方驱动下载页：https://www.nvidia.com/Download/index.aspx
   - 选择你的 GPU 型号、操作系统、语言
   - 点击「搜索」→ 下载最新 Game Ready 驱动（或 Studio 驱动，开发环境推荐 Studio）

3. **安装驱动**
   - 双击下载的 `.exe` 文件
   - 选择「自定义安装」→ 勾选「执行清洁安装」（推荐，避免旧驱动残留）
   - 等待安装完成，重启电脑

4. **验证**
   ```powershell
   nvidia-smi
   ```

### 步骤 2：安装 CUDA Toolkit（可选，GPU 计算任务必需）

> **适用场景**：M5 向量搜索、M9 代码沙箱需要跑 GPU 推理/训练

1. **确定 CUDA 版本**
   - 运行 `nvidia-smi` 查看右上角 `CUDA Version`（这是你驱动支持的最高版本）
   - 安装的 CUDA 版本不能超过这个值
   - 推荐：CUDA 11.8 或 12.x（兼容性好）

2. **下载 CUDA Toolkit**
   - 访问：https://developer.nvidia.com/cuda-toolkit-archive
   - 选择版本 → Windows → x86_64 → 10/11 → exe (local)
   - 下载安装包（约 3GB）

3. **安装 CUDA**
   - 双击安装包
   - 选择「自定义」安装
   - 勾选以下组件（其他可以不装）：
     - ✅ CUDA → Development（开发库）
     - ✅ CUDA → Runtime（运行时）
     - ❌ Visual Studio Integration（不需要 VS 集成可以不装）
     - ❌ GeForce Experience（已有驱动就不用）
     - ❌ PhysX（可选）
   - 安装路径默认即可：`C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\vXX.X`

4. **配置环境变量**
   - 安装程序通常会自动配置，但建议手动确认：
   - 系统变量 `CUDA_PATH` 应指向 CUDA 安装目录
   - `Path` 中应包含：
     - `%CUDA_PATH%\bin`
     - `%CUDA_PATH%\libnvvp`

5. **验证**
   ```powershell
   nvcc -V
   # 应输出类似：Cuda compilation tools, release 11.8, V11.8.xx
   ```

### 步骤 3：安装 cuDNN（可选，深度学习加速）

> **适用场景**：需要运行深度学习模型推理（如本地 LLM、Embedding 模型等）

1. **下载 cuDNN**
   - 访问：https://developer.nvidia.com/cudnn
   - 需要注册 NVIDIA 开发者账号（免费）
   - 选择与你 CUDA 版本匹配的 cuDNN 版本
   - 下载 Windows 版本的 zip 包

2. **安装 cuDNN**
   - 解压下载的 zip 文件
   - 将以下文件复制到 CUDA 安装目录对应文件夹：
     - `bin/cudnn*.dll` → `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\vXX.X\bin\`
     - `include/cudnn*.h` → `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\vXX.X\include\`
     - `lib/x64/cudnn*.lib` → `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\vXX.X\lib\x64\`

3. **验证**
   ```powershell
   # 检查 cuDNN 版本（PyTorch 方式）
   python -c "import torch; print(torch.backends.cudnn.version())"
   # 或 TensorFlow 方式
   python -c "import tensorflow as tf; print(tf.config.list_physical_devices('GPU'))"
   ```

### 步骤 4：安装 Python GPU 计算库（可选）

根据需要安装以下库：

```powershell
# PyTorch（GPU 版）- 访问 pytorch.org 获取对应你 CUDA 版本的命令
# CUDA 11.8:
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# CUDA 12.1:
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 验证 PyTorch GPU
python -c "import torch; print(f'CUDA 可用: {torch.cuda.is_available()}'); print(f'GPU 数量: {torch.cuda.device_count()}')"

# TensorFlow（GPU 版）
pip install tensorflow[and-cuda]

# sentence-transformers（向量嵌入，M5 用）
pip install sentence-transformers
```

---

## 四、潮汐引擎验证步骤

完成 GPU 环境配置后，按以下步骤验证潮汐引擎能正常工作：

### 4.1 启动 M10 服务

```powershell
cd C:\Yunxi\workspace\yunxi-project\M10-system-guard
python server.py
```

### 4.2 查看潮汐状态

打开浏览器或用 curl 访问：

```powershell
# 查看潮汐状态
curl http://localhost:8020/api/v1/tide/status

# 查看 GPU 设备信息
curl http://localhost:8020/api/v1/gpu/devices
```

### 4.3 测试任务提交

```powershell
# 提交一个 GPU 任务
curl -X POST http://localhost:8020/api/v1/tide/missions `
  -H "Content-Type: application/json" `
  -d '{
    "name": "测试推理任务",
    "priority": "normal",
    "mission_type": "inference",
    "estimated_gpu_memory_mb": 1024,
    "estimated_duration_sec": 30,
    "caller_module": "M5",
    "tide_preemptible": true
  }'
```

### 4.4 测试潮汐阶段切换

```powershell
# 手动设置为涨潮（调试用）
curl -X POST http://localhost:8020/api/v1/tide/debug/set-phase `
  -H "Content-Type: application/json" `
  -d '{"phase": "flood"}'

# 查看任务列表（涨潮时 BATCH 任务也能运行）
curl http://localhost:8020/api/v1/tide/missions
```

---

## 五、常见问题排查

### Q1: `nvidia-smi` 提示找不到命令

**原因**：驱动未安装，或 `nvidia-smi.exe` 不在 PATH 中。

**解决**：
1. 确认已安装 NVIDIA 驱动
2. 手动到 `C:\Windows\System32\nvidia-smi.exe` 查找
3. 如果有但不在 PATH，将 `C:\Windows\System32` 加入 PATH（通常默认就在）

### Q2: Python `pynvml` 报错 `NVML_ERROR_LIBRARY_NOT_FOUND`

**原因**：系统找不到 NVML 动态库。

**解决**：
1. 确认 NVIDIA 驱动已安装（`nvidia-smi` 能用）
2. 尝试安装新包：`pip install nvidia-ml-py`（替代旧的 `pynvml`）
3. 检查 `C:\Windows\System32\nvml.dll` 是否存在

### Q3: 潮汐引擎检测不到 GPU，显示 0 个设备

**原因**：NVML 初始化失败。

**排查步骤**：
```powershell
python -c "import pynvml; pynvml.nvmlInit(); print(pynvml.nvmlDeviceGetCount())"
```
- 如果报错 → 驱动/NVML 问题，按 Q1/Q2 排查
- 如果输出 0 → 没有 NVIDIA GPU 或驱动异常
- 如果输出 ≥ 1 → 潮汐引擎应该能检测到，检查 M10 日志

### Q4: GPU 显存显示不正确

**原因**：可能是 WSL、虚拟机、或 TCC/WDDM 模式问题。

**解决**：
- Windows 桌面环境下 GPU 通常是 WDDM 模式，显示的显存会扣掉桌面占用
- 这是正常现象，潮汐引擎会用实际可用显存进行调度
- 如需最大显存可用，考虑关闭桌面特效、减少显示器数量

### Q5: 多 GPU 环境下任务分配不均

**原因**：默认策略是选剩余显存最多的 GPU（负载均衡）。

**解决**：
- 这是预期行为，潮汐编排器会自动做负载均衡
- 如需绑定特定 GPU，提交任务时指定 `preferred_gpu_id` 参数

---

## 六、推荐硬件配置

| 级别 | GPU 型号示例 | 显存 | 适用场景 |
|------|-------------|------|---------|
| 入门级 | GTX 1660 / RTX 3050 | 6-8GB | 潮汐引擎演示、轻量推理 |
| 进阶级 | RTX 3060 / RTX 4060 | 8-12GB | 向量搜索、小规模模型推理 |
| 专业级 | RTX 3090 / RTX 4090 | 24GB | 大模型推理、模型训练 |
| 服务器级 | A100 / H100 | 40-80GB | 企业级大模型训练与推理 |

---

## 七、配置完成检查清单

- [ ] `nvidia-smi` 命令能正常输出 GPU 信息
- [ ] Python `pynvml` 能检测到 GPU 数量
- [ ] M10 服务能正常启动
- [ ] `GET /api/v1/tide/status` 返回正常数据
- [ ] `GET /api/v1/gpu/devices` 返回 GPU 列表
- [ ] 能提交 GPU 任务并看到状态变化
- [ ] （可选）`nvcc -V` 输出 CUDA 版本
- [ ] （可选）PyTorch/TensorFlow 能检测到 GPU

完成以上所有步骤后，潮汐引擎即可正常工作。如果遇到问题，先参考「常见问题排查」部分，仍无法解决时记录错误日志提交技术支持。
