"""
安全密钥管理模块
提供API密钥的安全存储和管理功能
"""

import os
import logging
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet
import base64


class SecureKeyManager:
    """安全密钥管理器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._master_key = self._get_or_create_master_key()
        self._cipher = Fernet(self._master_key)
        
    def _get_or_create_master_key(self) -> bytes:
        """获取或创建主密钥"""
        master_key = os.getenv('MASTER_KEY')
        if master_key:
            # 从环境变量获取主密钥
            try:
                return base64.urlsafe_b64decode(master_key.encode())
            except Exception as e:
                self.logger.error(f"主密钥解码失败: {e}")
                raise ValueError("无效的主密钥格式")
        else:
            # 生成新的主密钥
            new_key = Fernet.generate_key()
            self.logger.warning("未找到主密钥，生成新的主密钥。请设置环境变量 MASTER_KEY="
                               f"{base64.urlsafe_b64encode(new_key).decode()}")
            return new_key
    
    def encrypt_api_key(self, api_key: str) -> str:
        """加密API密钥"""
        if not api_key:
            return ""
        try:
            encrypted = self._cipher.encrypt(api_key.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
        except Exception as e:
            self.logger.error(f"API密钥加密失败: {e}")
            raise
    
    def decrypt_api_key(self, encrypted_key: str) -> str:
        """解密API密钥"""
        if not encrypted_key:
            return ""
        try:
            encrypted_data = base64.urlsafe_b64decode(encrypted_key.encode())
            decrypted = self._cipher.decrypt(encrypted_data)
            return decrypted.decode()
        except Exception as e:
            self.logger.error(f"API密钥解密失败: {e}")
            raise
    
    def get_api_key(self, key_name: str) -> str:
        """从环境变量获取API密钥"""
        # 优先获取加密的环境变量
        encrypted_key = os.environ.get(f"{key_name}_ENCRYPTED")
        if encrypted_key:
            try:
                return self.decrypt_api_key(encrypted_key)
            except Exception as e:
                self.logger.error(f"解密API密钥失败 {key_name}: {e}")
                return ""
        
        # 其次获取明文环境变量（向后兼容）
        plain_key = os.environ.get(key_name)
        if plain_key:
            return plain_key
        
        return ""
    
    def validate_api_key_format(self, api_key: str, provider: str) -> bool:
        """验证API密钥格式"""
        if not api_key or not isinstance(api_key, str):
            return False
        
        # 根据不同提供商验证密钥格式
        validators = {
            'openrouter': lambda k: k.startswith('sk-or-') or len(k) >= 20,
            'deepseek': lambda k: k.startswith('sk-') and len(k) >= 20,
            'gemini': lambda k: len(k) >= 30,
            'xai': lambda k: k.startswith('xai-') and len(k) >= 20,
            'siliconflow': lambda k: len(k) >= 20,
            'ollama': lambda k: True,  # Ollama通常不需要API密钥
        }
        
        validator = validators.get(provider.lower())
        if validator:
            return validator(api_key)
        
        # 默认验证：非空且长度合理
        return len(api_key) >= 10
    
    def sanitize_api_key_for_display(self, api_key: str) -> str:
        """为显示目的清理API密钥"""
        if not api_key:
            return ""
        
        # 只显示前4个和后4个字符
        if len(api_key) <= 8:
            return "*" * len(api_key)
        
        return f"{api_key[:4]}...{api_key[-4:]}"
    
    def rotate_encryption_key(self) -> bool:
        """轮换加密密钥"""
        try:
            new_key = Fernet.generate_key()
            new_cipher = Fernet(new_key)
            
            # 这里可以添加重新加密现有密钥的逻辑
            # 需要保存旧密钥用于解密，然后用新密钥重新加密
            
            self._master_key = new_key
            self._cipher = new_cipher
            
            self.logger.info("加密密钥轮换成功")
            return True
        except Exception as e:
            self.logger.error(f"加密密钥轮换失败: {e}")
            return False


# 全局安全密钥管理器实例
_security_manager = None


def get_security_manager() -> SecureKeyManager:
    """获取全局安全密钥管理器实例"""
    global _security_manager
    if _security_manager is None:
        _security_manager = SecureKeyManager()
    return _security_manager


def load_api_keys_from_env() -> Dict[str, str]:
    """从环境变量加载所有API密钥"""
    manager = get_security_manager()
    api_keys = {}
    
    # 支持的API提供商列表
    providers = [
        'openrouter', 'deepseek', 'gemini', 'xai', 
        'siliconflow', 'ollama', 'openai'
    ]
    
    for provider in providers:
        api_key = manager.get_api_key_from_env(provider)
        if api_key:
            api_keys[provider] = api_key
    
    return api_keys


def validate_environment_variables() -> Dict[str, Any]:
    """验证环境变量配置"""
    manager = get_security_manager()
    results = {
        'valid_keys': [],
        'invalid_keys': [],
        'missing_keys': [],
        'warnings': []
    }
    
    # 检查主密钥
    master_key = os.getenv('MASTER_KEY')
    if not master_key:
        results['warnings'].append("未设置 MASTER_KEY，将使用临时生成的密钥")
    
    # 检查API密钥
    providers = ['openrouter', 'deepseek', 'gemini', 'xai', 'siliconflow']
    
    for provider in providers:
        encrypted_key = os.getenv(f'{provider.upper()}_API_KEY_ENCRYPTED')
        plain_key = os.getenv(f'{provider.upper()}_API_KEY')
        
        if encrypted_key:
            try:
                decrypted = manager.decrypt_api_key(encrypted_key)
                if manager.validate_api_key_format(decrypted, provider):
                    results['valid_keys'].append(provider)
                else:
                    results['invalid_keys'].append(f"{provider} (格式无效)")
            except Exception:
                results['invalid_keys'].append(f"{provider} (解密失败)")
        elif plain_key:
            if manager.validate_api_key_format(plain_key, provider):
                results['valid_keys'].append(provider)
                results['warnings'].append(f"{provider}_API_KEY 为明文存储，建议加密")
            else:
                results['invalid_keys'].append(f"{provider} (格式无效)")
        else:
            results['missing_keys'].append(provider)
    
    return results