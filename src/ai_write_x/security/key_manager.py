"""
增强的API密钥管理器
提供环境变量管理、加密存储、密钥轮换等高级功能
"""

import os
import json
import logging
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
import base64
import hashlib
from pathlib import Path


class SecureKeyManager:
    """增强的安全密钥管理器"""
    
    def __init__(self, config_dir: Optional[str] = None):
        self.logger = logging.getLogger(__name__)
        self.config_dir = Path(config_dir) if config_dir else Path.home() / '.aiwritex'
        self.config_dir.mkdir(exist_ok=True)
        
        # 初始化加密管理器
        self.encryption_manager = EncryptionManager(self.config_dir)
        self._master_key = self.encryption_manager.get_or_create_master_key()
        self._cipher = Fernet(self._master_key)
        
        # 密钥存储文件
        self.keys_file = self.config_dir / 'encrypted_keys.json'
        self.key_metadata_file = self.config_dir / 'key_metadata.json'
        
        # 加载已存储的密钥
        self._encrypted_keys: Dict[str, str] = {}
        self._key_metadata: Dict[str, Dict[str, Any]] = {}
        self._load_stored_keys()
        
        # API密钥环境变量映射
        self.provider_env_map = {
            'openrouter': 'OPENROUTER_API_KEY',
            'deepseek': 'DEEPSEEK_API_KEY', 
            'grok': 'XAI_API_KEY',
            'gemini': 'GEMINI_API_KEY',
            'ollama': 'OLLAMA_API_KEY',
            'siliconflow': 'SILICONFLOW_API_KEY',
            'openai': 'OPENAI_API_KEY',
            'ali_image': 'ALI_IMAGE_API_KEY'
        }
        
        self.logger.info("安全密钥管理器初始化完成")
    
    def _load_stored_keys(self):
        """加载本地存储的加密密钥"""
        try:
            if self.keys_file.exists():
                with open(self.keys_file, 'r') as f:
                    self._encrypted_keys = json.load(f)
                    
            if self.key_metadata_file.exists():
                with open(self.key_metadata_file, 'r') as f:
                    self._key_metadata = json.load(f)
                    
        except Exception as e:
            self.logger.error(f"加载存储密钥失败: {e}")
            self._encrypted_keys = {}
            self._key_metadata = {}
    
    def _save_stored_keys(self):
        """保存密钥到本地存储"""
        try:
            with open(self.keys_file, 'w') as f:
                json.dump(self._encrypted_keys, f, indent=2)
                
            with open(self.key_metadata_file, 'w') as f:
                json.dump(self._key_metadata, f, indent=2)
                
        except Exception as e:
            self.logger.error(f"保存密钥失败: {e}")
            raise
    
    def encrypt_api_key(self, api_key: str, key_name: str) -> str:
        """加密API密钥并存储"""
        if not api_key or not key_name:
            raise ValueError("API密钥和密钥名称不能为空")
            
        try:
            # 加密密钥
            encrypted = self._cipher.encrypt(api_key.encode())
            encrypted_b64 = base64.urlsafe_b64encode(encrypted).decode()
            
            # 存储加密密钥
            self._encrypted_keys[key_name] = encrypted_b64
            
            # 记录元数据
            self._key_metadata[key_name] = {
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'length': len(api_key),
                'hash': hashlib.sha256(api_key.encode()).hexdigest()[:16],
                'provider': self._get_provider_from_key_name(key_name)
            }
            
            # 保存到文件
            self._save_stored_keys()
            
            self.logger.info(f"API密钥已加密存储: {key_name}")
            return encrypted_b64
            
        except Exception as e:
            self.logger.error(f"API密钥加密失败 {key_name}: {e}")
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
    
    def get_api_key(self, key_name: str, use_cache: bool = True) -> str:
        """获取API密钥（优先从环境变量，其次从本地存储）"""
        try:
            # 1. 优先从环境变量获取加密版本
            encrypted_env = os.environ.get(f"{key_name}_ENCRYPTED")
            if encrypted_env:
                return self.decrypt_api_key(encrypted_env)
            
            # 2. 从环境变量获取明文版本
            plain_env = os.environ.get(key_name)
            if plain_env:
                self.logger.warning(f"{key_name} 以明文形式存储在环境变量中，建议加密")
                return plain_env
            
            # 3. 从本地存储获取
            if use_cache and key_name in self._encrypted_keys:
                encrypted_key = self._encrypted_keys[key_name]
                api_key = self.decrypt_api_key(encrypted_key)
                
                # 验证密钥格式
                provider = self._get_provider_from_key_name(key_name)
                if self.validate_api_key_format(api_key, provider):
                    return api_key
                else:
                    self.logger.warning(f"存储的密钥 {key_name} 格式无效")
            
            return ""
            
        except Exception as e:
            self.logger.error(f"获取API密钥失败 {key_name}: {e}")
            return ""
    
    def store_api_key(self, key_name: str, api_key: str, encrypt: bool = True) -> bool:
        """存储API密钥到安全存储"""
        try:
            if encrypt:
                self.encrypt_api_key(api_key, key_name)
            else:
                # 明文存储（不推荐）
                self._encrypted_keys[key_name] = api_key
                self._key_metadata[key_name] = {
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat(),
                    'length': len(api_key),
                    'hash': hashlib.sha256(api_key.encode()).hexdigest()[:16],
                    'provider': self._get_provider_from_key_name(key_name),
                    'encrypted': False
                }
                self._save_stored_keys()
            
            self.logger.info(f"API密钥已存储: {key_name}")
            return True
            
        except Exception as e:
            self.logger.error(f"存储API密钥失败 {key_name}: {e}")
            return False
    
    def remove_api_key(self, key_name: str) -> bool:
        """删除存储的API密钥"""
        try:
            if key_name in self._encrypted_keys:
                del self._encrypted_keys[key_name]
                
            if key_name in self._key_metadata:
                del self._key_metadata[key_name]
                
            self._save_stored_keys()
            self.logger.info(f"API密钥已删除: {key_name}")
            return True
            
        except Exception as e:
            self.logger.error(f"删除API密钥失败 {key_name}: {e}")
            return False
    
    def list_stored_keys(self) -> List[Dict[str, Any]]:
        """列出所有存储的密钥信息（不包含实际密钥）"""
        key_info_list = []
        
        for key_name, metadata in self._key_metadata.items():
            info = {
                'name': key_name,
                'provider': metadata.get('provider', 'unknown'),
                'created_at': metadata.get('created_at'),
                'updated_at': metadata.get('updated_at'),
                'length': metadata.get('length', 0),
                'encrypted': metadata.get('encrypted', True),
                'hash': metadata.get('hash', '')[0:8] + '...'
            }
            key_info_list.append(info)
        
        return key_info_list
    
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
            'openai': lambda k: k.startswith('sk-') and len(k) >= 20,
            'ali_image': lambda k: len(k) >= 10  # 阿里云图像API
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
            # 解密所有现有密钥
            decrypted_keys = {}
            for key_name, encrypted_key in self._encrypted_keys.items():
                if isinstance(encrypted_key, str) and len(encrypted_key) > 0:
                    decrypted_keys[key_name] = self.decrypt_api_key(encrypted_key)
            
            # 生成新的加密密钥
            new_key = Fernet.generate_key()
            new_cipher = Fernet(new_key)
            
            # 重新加密所有密钥
            new_encrypted_keys = {}
            for key_name, decrypted_key in decrypted_keys.items():
                encrypted = new_cipher.encrypt(decrypted_key.encode())
                encrypted_b64 = base64.urlsafe_b64encode(encrypted).decode()
                new_encrypted_keys[key_name] = encrypted_b64
            
            # 更新密钥和加密器
            self._master_key = new_key
            self._cipher = new_cipher
            self._encrypted_keys = new_encrypted_keys
            
            # 保存新的加密密钥
            self.encryption_manager.save_master_key(new_key)
            self._save_stored_keys()
            
            self.logger.info("加密密钥轮换成功")
            return True
            
        except Exception as e:
            self.logger.error(f"加密密钥轮换失败: {e}")
            return False
    
    def _get_provider_from_key_name(self, key_name: str) -> str:
        """从密钥名称推断提供商"""
        key_lower = key_name.lower()
        
        if 'openrouter' in key_lower:
            return 'openrouter'
        elif 'deepseek' in key_lower:
            return 'deepseek'
        elif 'gemini' in key_lower:
            return 'gemini'
        elif 'xai' in key_lower or 'grok' in key_lower:
            return 'xai'
        elif 'siliconflow' in key_lower:
            return 'siliconflow'
        elif 'ollama' in key_lower:
            return 'ollama'
        elif 'openai' in key_lower:
            return 'openai'
        elif 'ali' in key_lower:
            return 'ali_image'
        else:
            return 'unknown'
    
    def validate_all_stored_keys(self) -> Dict[str, Any]:
        """验证所有存储的密钥"""
        results = {
            'valid_keys': [],
            'invalid_keys': [],
            'expired_keys': [],
            'total_keys': len(self._encrypted_keys)
        }
        
        for key_name, encrypted_key in self._encrypted_keys.items():
            try:
                # 解密密钥
                api_key = self.decrypt_api_key(encrypted_key)
                
                # 获取提供商
                provider = self._get_provider_from_key_name(key_name)
                
                # 验证格式
                if self.validate_api_key_format(api_key, provider):
                    results['valid_keys'].append({
                        'name': key_name,
                        'provider': provider,
                        'length': len(api_key)
                    })
                else:
                    results['invalid_keys'].append({
                        'name': key_name,
                        'provider': provider,
                        'reason': 'invalid_format'
                    })
                    
            except Exception as e:
                results['invalid_keys'].append({
                    'name': key_name,
                    'reason': f'decryption_error: {str(e)}'
                })
        
        return results


class EncryptionManager:
    """加密管理器"""
    
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.master_key_file = config_dir / 'master_key.enc'
        self.logger = logging.getLogger(__name__)
    
    def get_or_create_master_key(self) -> bytes:
        """获取或创建主密钥"""
        try:
            # 优先从环境变量获取
            master_key_env = os.getenv('MASTER_KEY')
            if master_key_env:
                try:
                    return base64.urlsafe_b64decode(master_key_env.encode())
                except Exception as e:
                    self.logger.error(f"环境变量主密钥解码失败: {e}")
            
            # 从文件获取
            if self.master_key_file.exists():
                with open(self.master_key_file, 'rb') as f:
                    return f.read()
            
            # 生成新的主密钥
            new_key = Fernet.generate_key()
            self.save_master_key(new_key)
            
            self.logger.warning("生成新的主密钥，请妥善保管")
            return new_key
            
        except Exception as e:
            self.logger.error(f"主密钥管理失败: {e}")
            # 生成临时密钥
            return Fernet.generate_key()
    
    def save_master_key(self, key: bytes):
        """保存主密钥到文件"""
        try:
            with open(self.master_key_file, 'wb') as f:
                f.write(key)
            
            # 设置文件权限为仅所有者可读写
            os.chmod(self.master_key_file, 0o600)
            
        except Exception as e:
            self.logger.error(f"保存主密钥失败: {e}")
            raise