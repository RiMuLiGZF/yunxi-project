# CUDA 12.9 + TensorRT 升级指南

> 适用环境：RTX 5060 8GB / 驱动 592.19 (支持 CUDA 13.1) / 当前 CUDA 12.4 + cuDNN 9.2
> 目标版本：CUDA 12.9 + cuDNN 最新版 + TensorRT 10.x
> 预计耗时：30-60 分钟（取决于网络下载速度）

---

## 一、为什么推荐升级到 CUDA 12.9

### 1.1 当前环境分析

| 项目 | 当前值 | 上限 | 升级空间 |
|------|--------|------|---------|
| GPU | RTX 5060 8GB | - | - |
| 驱动版本 | 592.19 | - | ✅ 最新，无需升级 |
| 驱动支持 CUDA | - | 13.1 | 可升到 12.9 甚至 13.x |
| CUDA Toolkit | 12.4.131 | - | 可升 5 个小版本 |
| cuDNN | 9.2.0 | - | 可同步升级 |
| TensorRT | 未安装 | - | 新增安装 |

### 1.2 升级收益

**CUDA 12.4 → 12.9 的改进：**
- **性能优化**：CUDA 12.5+ 引入了新的编译器优化，推理速度提升 5-15%
- **RTX 50 系列优化**：12.6+ 对 Blackwell 架构有更好的支持（5060 属于 Ada/Blackwell 混合架构）
- **cuDNN 兼容性**：最新 cuDNN 9.x 需要 CUDA 12.6+ 才能发挥全部性能
- **FP8 支持**：12.8+ 增强了 FP8 精度推理支持（5060 支持 FP8）
- **bug 修复**：多个版本的稳定性和兼容性修复累积

**新增 TensorRT 的收益：**
- **推理加速**：模型推理速度提升 2-4 倍（相比原生 PyTorch）
- **显存优化**：INT8/FP16/FP8 量化 + 层融合，显存占用减少 30-50%
- **M5 向量搜索**：embedding 推理速度大幅提升
- **M9 代码沙箱**：本地模型推理延迟降低
- **生产级部署**：TensorRT 是 NVIDIA 官方推理引擎，工业界标准

### 1.3 版本选择建议

**推荐方案：CUDA 12.9 + cuDNN 9.x + TensorRT 10.x**

理由：
- CUDA 12.9 是 12.x 系列的较新版本，稳定性好
- 距离 CUDA 13 只有一步，但 13.x 太新，部分框架（PyTorch/TensorFlow）兼容性还在跟进
- 12.9 对 RTX 5060 的支持已经非常完善
- TensorRT 10.x 是最新大版本，性能和功能都有大提升

---

## 二、升级前准备

### 2.1 备份（重要！）

升级 CUDA 有风险，**强烈建议先做以下备份**：

```powershell
# 1. 记录当前 CUDA 版本
nvcc -V > C:\Yunxi\workspace\backup\cuda_before_upgrade.txt

# 2. 备份当前 CUDA 路径配置
echo $env:CUDA_PATH >> C:\Yunxi\workspace\backup\cuda_before_upgrade.txt
echo $env:PATH -split ';' | Select-String -Pattern "CUDA|NVIDIA" >> C:\Yunxi\workspace\backup\cuda_before_upgrade.txt
```

### 2.2 确认磁盘空间

CUDA 12.9 完整安装约需 **8-10GB** 磁盘空间：
- CUDA Toolkit：约 3.5GB
- cuDNN：约 1GB
- TensorRT：约 2GB
- 临时文件：约 2GB

```powershell
# 检查 C 盘剩余空间
Get-PSDrive C | Select-Object Free
```

确保 C 盘剩余 **20GB 以上**（留足缓冲）。

### 2.3 关闭相关程序

升级前关闭：
- 所有 Python 程序（包括正在运行的 M5/M7/M9/M10 服务）
- VS Code / PyCharm 等 IDE
- 任何可能占用 GPU 的程序（游戏、视频剪辑等）

---

## 三、CUDA 12.9 升级步骤

### 步骤 1：下载 CUDA 12.9

**下载地址**：https://developer.nvidia.com/cuda-toolkit-archive

操作步骤：
1. 打开上面的链接
2. 找到 **CUDA Toolkit 12.9.x**（选最新的 12.9.x，比如 12.9.2 或 12.9.1）
3. 选择：
   - Operating System: **Windows**
   - Architecture: **x86_64**
   - Version: **11**（或 **10**，根据你的系统）
   - Installer Type: **exe (local)**
4. 点击 Download 下载
   - 文件大小：约 3.5GB
   - 文件名类似：`cuda_12.9.2_5xx.xx_win11.exe`

> 💡 **提示**：下载速度慢的话，可以用迅雷等下载工具，或者找国内镜像源。

### 步骤 2：卸载旧版 CUDA（可选但推荐）

> **注意**：这一步是可选的。CUDA 支持多版本共存，但为了避免冲突，推荐先卸载 12.4。

**方案 A：保留 12.4，新增 12.9（多版本共存）**
- 直接跳到步骤 3 安装
- 安装完成后手动切换环境变量即可

**方案 B：卸载 12.4，全新安装 12.9（推荐）**
- 打开「设置」→「应用」→「已安装的应用」
- 搜索 "NVIDIA"，卸载以下项目（**只卸载 CUDA 相关的，不要卸载驱动！**）：
  - ✅ NVIDIA CUDA Toolkit 12.4
  - ✅ NVIDIA CUDA Samples 12.4
  - ✅ NVIDIA CUDA Visual Studio Integration 12.4（如果有）
  - ❌ **绝对不要卸载**：NVIDIA Graphics Driver（显卡驱动）
  - ❌ **绝对不要卸载**：NVIDIA PhysX（如果有）
  - ❌ **绝对不要卸载**：NVIDIA GeForce Experience

> ⚠️ **警告**：卸载时一定要看清楚名字，只卸载带 "CUDA Toolkit" 的项目！卸载错了驱动会导致黑屏！

### 步骤 3：安装 CUDA 12.9

1. 双击下载的安装包 `cuda_12.9.x_xxx.xx_win11.exe`
2. 选择临时解压目录（默认即可，安装完会自动删除）
3. 等解压完成，进入安装界面
4. 选择「**自定义**」安装（不要选精简）
5. 在组件选择中，按以下建议勾选：

   | 组件 | 建议 | 说明 |
   |------|------|------|
   | CUDA → Development | ✅ 必选 | CUDA 开发库和头文件 |
   | CUDA → Runtime | ✅ 必选 | CUDA 运行时库 |
   | CUDA → Visual Studio Integration | ❌ 可选 | 不需要 VS 集成可以不装 |
   | CUDA → Documentation | ❌ 可选 | 文档，占空间大 |
   | CUDA → Samples | ❌ 可选 | 示例代码，学习用 |
   | Other components → Display Driver | ❌ 不选 | 我们驱动已经是最新的了 |
   | Other components → GeForce Experience | ❌ 不选 | 不需要 |
   | Other components → PhysX | ❌ 可选 | 物理引擎，深度学习用不到 |

6. 选择安装位置（默认即可）：
   - 默认路径：`C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9`
7. 点击「下一步」开始安装
8. 等待安装完成（约 5-10 分钟）
9. 安装完成后点击「关闭」，**不需要重启**（驱动没动就不用重启）

### 步骤 4：验证 CUDA 12.9 安装

```powershell
# 检查 CUDA 版本
nvcc -V

# 预期输出应该显示 release 12.9
# 类似：Cuda compilation tools, release 12.9, V12.9.x

# 检查环境变量
echo $env:CUDA_PATH
# 应该指向 v12.9 目录

# 运行带宽测试（验证功能）
& "$env:CUDA_PATH\extras\demo_suite\bandwidthTest.exe"
# 最后一行应该显示 Result = PASS
```

> 💡 如果 `nvcc -V` 还是显示 12.4，说明环境变量没更新。需要手动改 PATH，把 v12.9 的路径放到 v12.4 前面，或者重启终端。

---

## 四、cuDNN 升级步骤

### 步骤 1：下载 cuDNN

**下载地址**：https://developer.nvidia.com/cudnn

1. 打开链接，需要登录 NVIDIA 开发者账号（没有就注册一个，免费的）
2. 选择最新的 **cuDNN 9.x** 版本（对应 CUDA 12.x）
3. 下载 **Windows x86_64** 版本的 zip 包
   - 文件名类似：`cudnn-windows-x86_64-9.x.x.x_cuda12-archive.zip`
   - 文件大小：约 600-800MB

> 💡 国内用户可以在网上搜索 "cuDNN 国内镜像" 找更快的下载源。

### 步骤 2：安装 cuDNN

cuDNN 的安装就是把文件复制到 CUDA 目录里：

1. 解压下载的 zip 文件
2. 解压后会看到三个文件夹：`bin`、`include`、`lib`
3. 把这三个文件夹里的文件，**分别复制**到 CUDA 12.9 对应的目录：

```powershell
# 假设解压到了 C:\Downloads\cudnn-windows-x86_64-9.x.x.x_cuda12-archive
# CUDA 安装在 C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9

# bin 目录（dll 文件）
Copy-Item "C:\Downloads\cudnn-*\bin\*.dll" "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin\"

# include 目录（头文件）
Copy-Item "C:\Downloads\cudnn-*\include\*.h" "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\include\"

# lib\x64 目录（lib 文件）
Copy-Item "C:\Downloads\cudnn-*\lib\x64\*.lib" "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\lib\x64\"
```

> 💡 或者直接手动拖进去也行，效果一样。

### 步骤 3：验证 cuDNN

```powershell
# 检查 cuDNN dll 是否存在
Test-Path "$env:CUDA_PATH\bin\cudnn64_*.dll"

# 用 Python 验证（如果装了 PyTorch）
python -c "import torch; print(f'cuDNN 版本: {torch.backends.cudnn.version()}'); print(f'cuDNN 可用: {torch.backends.cudnn.is_available()}')"
```

---

## 五、TensorRT 安装步骤

### 步骤 1：下载 TensorRT

**下载地址**：https://developer.nvidia.com/tensorrt-getting-started

1. 打开链接，找到 Download 区域
2. 选择 **TensorRT 10.x**（最新的稳定版，比如 10.5 或 10.3）
3. 选择对应 CUDA 12.x 的 Windows 版本
4. 下载 **Zip Package** 格式
   - 文件名类似：`TensorRT-10.x.x.x.Windows10.x86_64.cuda-12.x.cudnn9.x.zip`
   - 文件大小：约 2GB

> 💡 TensorRT 版本必须和 CUDA、cuDNN 版本对应，下载时看清楚说明。

### 步骤 2：解压 TensorRT

选择一个固定的安装位置，推荐：

```
C:\Program Files\NVIDIA GPU Computing Toolkit\TensorRT-10.x.x.x
```

解压步骤：
1. 把 zip 包解压到上面的路径
2. 解压后目录结构应该是：
   ```
   TensorRT-10.x.x.x/
   ├── bin/          (dll 文件)
   ├── include/      (头文件)
   ├── lib/          (lib 文件)
   ├── python/       (Python wheel 包)
   ├── samples/      (示例代码)
   └── doc/          (文档)
   ```

### 步骤 3：配置环境变量

把 TensorRT 的 bin 目录加入系统 PATH：

```powershell
# 1. 临时添加（当前终端有效）
$env:PATH = "C:\Program Files\NVIDIA GPU Computing Toolkit\TensorRT-10.x.x.x\bin;" + $env:PATH

# 2. 永久添加（需要管理员权限）
[Environment]::SetEnvironmentVariable(
    "PATH",
    "C:\Program Files\NVIDIA GPU Computing Toolkit\TensorRT-10.x.x.x\bin;" + [Environment]::GetEnvironmentVariable("PATH", "Machine"),
    "Machine"
)
```

**或者手动操作**：
1. 按 Win + R，输入 `sysdm.cpl`，回车
2. 「高级」→「环境变量」
3. 系统变量 → 找到 Path → 编辑
4. 新建 → 粘贴 TensorRT 的 bin 路径
5. 一路确定保存

### 步骤 4：安装 Python 绑定

TensorRT 提供了 Python 包，方便在 Python 里调用：

```powershell
# 进入 TensorRT 的 python 目录
cd "C:\Program Files\NVIDIA GPU Computing Toolkit\TensorRT-10.x.x.x\python"

# 查看有哪些 wheel 文件
dir *.whl

# 安装对应 Python 3.10 的版本
# 文件名类似：tensorrt-10.x.x.x-cp310-none-win_amd64.whl
pip install tensorrt-10.x.x.x-cp310-none-win_amd64.whl

# 也安装一下 tensorrt_dispatch 和 onnx_graphsurgeon
pip install tensorrt_dispatch-*.whl
pip install onnx_graphsurgeon-*.whl
```

### 步骤 5：验证 TensorRT

```powershell
# 1. 检查 dll 是否能找到
where trtexec.exe
# 应该能找到 TensorRT bin 目录下的 trtexec.exe

# 2. Python 验证
python -c "import tensorrt as trt; print(f'TensorRT 版本: {trt.__version__}')"

# 3. 运行 trtexec 自带测试（可选，比较慢）
trtexec --help
# 不报错就是安装成功了
```

---

## 六、PyTorch GPU 版重装/升级

升级 CUDA 后，PyTorch 也需要装对应版本的 GPU 版。

### 步骤 1：卸载旧版 PyTorch

```powershell
pip uninstall torch torchvision torchaudio -y
```

### 步骤 2：安装 CUDA 12.x 版 PyTorch

```powershell
# CUDA 12.1 版（兼容性最好，也能在 12.9 上运行）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 或者 CUDA 12.4 版（如果有的话）
# 去 pytorch.org 查最新的安装命令
```

> 💡 PyTorch 的 cu121 版本可以在 CUDA 12.1-12.9 上都运行，因为是向前兼容的。

### 步骤 3：验证 PyTorch GPU

```powershell
python -c "
import torch
print(f'PyTorch 版本: {torch.__version__}')
print(f'CUDA 可用: {torch.cuda.is_available()}')
print(f'GPU 数量: {torch.cuda.device_count()}')
if torch.cuda.is_available():
    print(f'GPU 名称: {torch.cuda.get_device_name(0)}')
    print(f'显存总量: {torch.cuda.get_device_properties(0).total_mem / 1024**3:.1f} GB')
    # 简单测试
    x = torch.randn(1000, 1000).cuda()
    y = torch.randn(1000, 1000).cuda()
    z = x @ y
    print(f'GPU 矩阵乘法测试通过，结果形状: {z.shape}')
"
```

预期输出：
```
PyTorch 版本: 2.x.x+cu121
CUDA 可用: True
GPU 数量: 1
GPU 名称: NVIDIA GeForce RTX 5060 ...
显存总量: 8.0 GB
GPU 矩阵乘法测试通过，结果形状: torch.Size([1000, 1000])
```

---

## 七、完整验证清单

全部安装完成后，按以下清单逐项验证：

- [ ] `nvidia-smi` 正常显示 GPU 信息
- [ ] `nvcc -V` 显示 CUDA 12.9
- [ ] `where cudnn64_*.dll` 能找到 cuDNN
- [ ] `where trtexec.exe` 能找到 TensorRT
- [ ] `python -c "import torch; print(torch.cuda.is_available())"` 输出 True
- [ ] `python -c "import tensorrt as trt; print(trt.__version__)"` 输出版本号
- [ ] `python -c "import torch; print(torch.backends.cudnn.is_available())"` 输出 True
- [ ] M10 潮汐引擎能检测到 GPU
- [ ] M5 向量搜索能正常使用 GPU 加速（如果已配置模型）

---

## 八、常见问题

### Q1: 安装完 CUDA 12.9 后 nvcc 还是显示 12.4

**原因**：环境变量 PATH 里 12.4 的路径在 12.9 前面。

**解决**：
1. 编辑系统环境变量 PATH
2. 把 `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9\bin` 上移到 v12.4 前面
3. 或者直接删掉 v12.4 的相关路径
4. 重启终端后再试

### Q2: TensorRT 导入报错 "找不到 nvinfer.dll"

**原因**：TensorRT 的 bin 目录没加到 PATH。

**解决**：
1. 确认 TensorRT bin 目录在 PATH 里
2. 重启终端/IDE 让环境变量生效
3. 或者把 TensorRT bin 里的 dll 全部复制到 CUDA 的 bin 目录里（粗暴但有效）

### Q3: PyTorch 说 CUDA 可用但 cuDNN 不可用

**原因**：cuDNN 版本和 PyTorch 不匹配，或者 cuDNN 没装好。

**解决**：
1. 确认 cuDNN 文件都复制到了正确的 CUDA 目录
2. 确认 cuDNN 版本和 CUDA 版本匹配
3. 可以试试重新复制一遍 cuDNN 文件

### Q4: 升级后 Python 程序报错

**原因**：某些依赖包是基于旧版 CUDA 编译的。

**解决**：
```powershell
# 重新安装依赖
pip uninstall torch torchvision torchaudio -y
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 如果有 sentence-transformers 等也需要重装
pip uninstall sentence-transformers transformers -y
pip install sentence-transformers transformers
```

### Q5: 想回退到 CUDA 12.4 怎么办

**回退步骤**：
1. 卸载 CUDA 12.9（和安装时一样，在「已安装的应用」里卸载）
2. 如果之前卸载了 12.4，需要重新安装 12.4
3. 安装包可以在 CUDA archive 里找到
4. 环境变量会自动切换回 12.4（如果还留着的话）

---

## 九、升级后的性能测试

升级完成后，可以跑一个简单的性能对比测试：

```powershell
python -c "
import torch
import time

# 测试设备
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f'使用设备: {device}')

# 矩阵乘法性能测试
size = 4096
x = torch.randn(size, size, device=device)
y = torch.randn(size, size, device=device)

# 预热
for _ in range(5):
    _ = x @ y
torch.cuda.synchronize()

# 正式测试
start = time.time()
for _ in range(100):
    z = x @ y
torch.cuda.synchronize()
elapsed = time.time() - start

print(f'{size}x{size} 矩阵乘法 x100 次: {elapsed:.3f} 秒')
print(f'单次平均: {elapsed/100*1000:.2f} ms')
print(f'计算性能: {2 * size**3 / (elapsed/100) / 1e12:.2f} TFLOPS')
"
```

把结果记下来，以后优化了可以对比。

---

## 十、后续计划

升级完成 CUDA + TensorRT 后，接下来可以做的优化：

1. **M5 向量搜索接入 TensorRT**：把 embedding 模型转成 TensorRT engine，推理速度提升 2-3 倍
2. **M9 代码沙箱本地模型加速**：如果有本地 LLM，用 TensorRT 部署
3. **潮汐引擎 GPU 指标精细化**：增加 TensorRT engine 缓存命中率等指标
4. **模型量化**：用 TensorRT 的 INT8/FP8 量化，进一步加速和省显存

这些都属于后续的优化工作，先把基础环境搭好。

---

**祝升级顺利！** 🚀
