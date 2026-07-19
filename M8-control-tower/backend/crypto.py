"""
M8 管理工作台 - 算力调度加密工具模块
基于 Fernet（AES-128-CBC + HMAC）对称加密，用于 API Key 等敏感信息的加密存储
"""

import os
import base64
import logging
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from .config import data_dir

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 主密钥管理
# ═══════════════════════════════════════════════════════

# 密钥文件路径（存放在 data 目录，不受版本控制）
_MASTER_KEY_FILE = data_dir / "compute_master.key"

# 全局 Fernet 实例（懒加载）
_fernet: Optional[Fernet] = None


def _generate_master_key() -> bytes:
    """生成新的主密钥"""
    return Fernet.generate_key()


def _load_master_key() -> bytes:
    """
    加载主密钥
    优先级：环境变量 COMPUTE_MASTER_KEY > 本地密钥文件 > 自动生成
    """
    # 1. 从环境变量读取
    env_key = os.getenv("COMPUTE_MASTER_KEY", "").strip()
    if env_key:
        try:
            # 验证密钥格式是否有效
            Fernet(env_key.encode("utf-8"))
            return env_key.encode("utf-8")
        except Exception:
            # 环境变量中的密钥无效，降级使用文件密钥
            pass

    # 2. 从本地密钥文件读取
    if _MASTER_KEY_FILE.exists():
        try:
            key_data = _MASTER_KEY_FILE.read_bytes().strip()
            if key_data:
                Fernet(key_data)  # 验证有效性
                return key_data
        except Exception:
            # 文件损坏，重新生成
            pass

    # 3. 自动生成并存入文件
    new_key = _generate_master_key()
    try:
        # 确保目录存在
        _MASTER_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 写入密钥文件（仅当前用户可读权限在 Windows 下通过文件属性设置）
        _MASTER_KEY_FILE.write_bytes(new_key)
        # 标记为隐藏文件（Windows）
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(_MASTER_KEY_FILE), 2)  # FILE_ATTRIBUTE_HIDDEN
        except Exception as e:
            # 非 Windows 平台或设置失败不影响加密功能
            logger.debug("设置密钥文件隐藏属性失败: %s", e)
    except Exception as e:
        # 写入失败也不影响运行，密钥在内存中使用
        logger.warning("写入主密钥文件失败: %s", e)

    return new_key


def _get_fernet() -> Fernet:
    """获取 Fernet 实例（单例懒加载）"""
    global _fernet
    if _fernet is None:
        key = _load_master_key()
        _fernet = Fernet(key)
    return _fernet


# ═══════════════════════════════════════════════════════
# 加密/解密函数
# ═══════════════════════════════════════════════════════

def encrypt(data: str) -> str:
    """
    加密字符串数据
    
    Args:
        data: 待加密的明文字符串
        
    Returns:
        加密后的 Base64 编码字符串
    """
    if not data:
        return ""
    try:
        fernet = _get_fernet()
        encrypted = fernet.encrypt(data.encode("utf-8"))
        return encrypted.decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"加密失败: {e}")


def decrypt(encrypted_data: str) -> str:
    """
    解密字符串数据
    
    Args:
        encrypted_data: 加密后的 Base64 编码字符串
        
    Returns:
        解密后的明文字符串
    """
    if not encrypted_data:
        return ""
    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(encrypted_data.encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        raise ValueError("解密失败：密钥不匹配或数据已损坏")
    except Exception as e:
        raise RuntimeError(f"解密失败: {e}")


def mask_api_key(api_key: str, show_prefix: int = 6, show_suffix: int = 4) -> str:
    """
    生成 API Key 的掩码显示版本
    
    Args:
        api_key: 原始 API Key
        show_prefix: 显示前 N 个字符
        show_suffix: 显示后 N 个字符
        
    Returns:
        掩码后的字符串，如 "sk-****abcd"
    """
    if not api_key:
        return ""
    
    key_len = len(api_key)
    
    if key_len <= show_prefix + show_suffix:
        # 密钥太短，全部掩码
        return "*" * key_len
    
    prefix = api_key[:show_prefix]
    suffix = api_key[-show_suffix:]
    mask_len = key_len - show_prefix - show_suffix
    
    # 掩码部分用固定 4 个星号更美观
    return f"{prefix}****{suffix}"


# ═══════════════════════════════════════════════════════
# 密钥轮换支持
# ═══════════════════════════════════════════════════════

def rotate_master_key(new_key: Optional[str] = None) -> str:
    """
    轮换主密钥
    
    Args:
        new_key: 可选的新密钥（Fernet 格式），不提供则自动生成
        
    Returns:
        新的主密钥（Base64 编码字符串）
    """
    global _fernet
    
    old_fernet = _get_fernet()
    
    # 生成或验证新密钥
    if new_key:
        try:
            new_fernet = Fernet(new_key.encode("utf-8"))
            new_key_bytes = new_key.encode("utf-8")
        except Exception:
            raise ValueError("新密钥格式无效，必须是有效的 Fernet 密钥")
    else:
        new_key_bytes = _generate_master_key()
        new_fernet = Fernet(new_key_bytes)
    
    # 保存新密钥到文件
    try:
        _MASTER_KEY_FILE.write_bytes(new_key_bytes)
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(_MASTER_KEY_FILE), 2)
        except Exception as e:
            # 非 Windows 平台或设置失败不影响加密功能
            logger.debug("设置密钥文件隐藏属性失败: %s", e)
    except Exception as e:
        raise RuntimeError(f"保存新密钥失败: {e}")
    
    # 更新全局实例
    _fernet = new_fernet
    
    return new_key_bytes.decode("utf-8")


def re_encrypt_data(encrypted_data: str, old_fernet: Optional[Fernet] = None) -> str:
    """
    使用当前主密钥重新加密数据（用于密钥轮换后的数据迁移）
    
    Args:
        encrypted_data: 旧密钥加密的数据
        old_fernet: 旧的 Fernet 实例，为 None 则尝试用当前密钥解密
        
    Returns:
        用新密钥加密的数据
    """
    if old_fernet is None:
        # 如果没有提供旧密钥，先尝试用当前密钥解密
        try:
            plaintext = decrypt(encrypted_data)
            return encrypt(plaintext)
        except ValueError:
            raise ValueError("无法解密数据，请提供旧密钥")
    else:
        try:
            plaintext = old_fernet.decrypt(encrypted_data.encode("utf-8")).decode("utf-8")
            return encrypt(plaintext)
        except InvalidToken:
            raise ValueError("旧密钥无法解密数据")


def get_key_info() -> dict:
    """
    获取当前密钥信息（不泄露密钥本身）
    
    Returns:
        密钥信息字典
    """
    key = _load_master_key()
    # 只返回密钥的指纹信息
    import hashlib
    fingerprint = hashlib.sha256(key).hexdigest()[:16]
    
    return {
        "source": "environment" if os.getenv("COMPUTE_MASTER_KEY") else "file",
        "fingerprint": fingerprint,
        "key_file": str(_MASTER_KEY_FILE) if not os.getenv("COMPUTE_MASTER_KEY") else None,
        "algorithm": "AES-128-CBC + HMAC-SHA256 (Fernet)",
    }
