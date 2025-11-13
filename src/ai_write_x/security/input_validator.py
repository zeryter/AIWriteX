"""
增强的输入验证器
提供全面的输入验证、数据清理和恶意内容检测
"""

import re
import logging
import html
import json
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse
import hashlib
from pathlib import Path


class InputValidator:
    """增强的输入验证器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # 预定义的正则表达式模式
        self.patterns = {
            'email': r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$',
            'url': r'^https?://[\w\-._~:/?#\[\]@!$&\()*+,;=]+$',
            'api_key': r'^(sk-|xai-)?[a-zA-Z0-9_-]{20,}$',
            'alphanumeric': r'^[a-zA-Z0-9]+$',
            'filename': r'^[a-zA-Z0-9_\-\.]+$',
            'path': r'^[a-zA-Z0-9_\-/\\\.]+$',
            'json': r'^\s*\{.*\}\s*$|^\s*\[.*\]\s*$',
            'sql_injection': r'(union|select|insert|update|delete|drop|create|alter|exec|script|javascript:)',  # 需要大小写不敏感匹配
            'xss_attack': r'<script.*?>.*?</script>|javascript:|onerror=|onload=|onclick=',
            'command_injection': r'(;|\|\||&&|`|\$\(|\$\{|<\(|>\(|\n|\r)',
            'path_traversal': r'(\.\./|\.\.\\\\|%2e%2e%2f|%2e%2e%5c)',
        }
        
        # 长度限制
        self.length_limits = {
            'api_key': (10, 512),
            'model_name': (1, 100),
            'prompt': (1, 10000),
            'filename': (1, 255),
            'path': (1, 500),
            'url': (10, 2000),
            'email': (5, 254),
            'json': (2, 100000),
        }
        
        # 危险字符映射
        self.dangerous_chars = {
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#x27;',
            '&': '&amp;',
            '(': '&#40;',
            ')': '&#41;',
            '#': '&#35;',
            '%': '&#37;',
        }
        
        self.logger.info("输入验证器初始化完成")
    
    def validate_string(self, value: str, pattern_name: str = None, min_length: int = None, 
                       max_length: int = None, allow_empty: bool = False) -> bool:
        """验证字符串输入"""
        try:
            # 空值检查
            if not value:
                return allow_empty
            
            if not isinstance(value, str):
                self.logger.warning(f"非字符串输入: {type(value)}")
                return False
            
            # 长度检查
            if min_length is not None and len(value) < min_length:
                self.logger.warning(f"字符串太短: {len(value)} < {min_length}")
                return False
                
            if max_length is not None and len(value) > max_length:
                self.logger.warning(f"字符串太长: {len(value)} > {max_length}")
                return False
            
            # 模式检查
            if pattern_name and pattern_name in self.patterns:
                pattern = self.patterns[pattern_name]
                
                # 特殊处理SQL注入检测（大小写不敏感）
                if pattern_name == 'sql_injection':
                    if re.search(pattern, value, re.IGNORECASE):
                        self.logger.warning(f"检测到SQL注入模式: {value[:50]}...")
                        return False
                else:
                    if not re.match(pattern, value):
                        self.logger.warning(f"模式验证失败 {pattern_name}: {value[:50]}...")
                        return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"字符串验证失败: {e}")
            return False
    
    def sanitize_string(self, value: str, escape_html: bool = True, 
                       max_length: int = None) -> str:
        """清理和转义字符串"""
        try:
            if not isinstance(value, str):
                value = str(value)
            
            # 长度限制
            if max_length and len(value) > max_length:
                value = value[:max_length]
            
            # HTML转义
            if escape_html:
                value = html.escape(value)
            
            # 移除控制字符
            value = ''.join(char for char in value if ord(char) >= 32 or char in '\t\n\r')
            
            # 标准化空白字符
            value = ' '.join(value.split())
            
            return value.strip()
            
        except Exception as e:
            self.logger.error(f"字符串清理失败: {e}")
            return ""
    
    def validate_api_key(self, api_key: str, provider: str = "generic") -> bool:
        """验证API密钥格式"""
        try:
            if not self.validate_string(api_key, min_length=10, max_length=512):
                return False
            
            # 提供商特定的验证规则
            provider_validators = {
                'openrouter': lambda k: k.startswith('sk-or-') or len(k) >= 20,
                'deepseek': lambda k: k.startswith('sk-') and len(k) >= 20,
                'gemini': lambda k: len(k) >= 30,
                'xai': lambda k: k.startswith('xai-') and len(k) >= 20,
                'siliconflow': lambda k: len(k) >= 20,
                'ollama': lambda k: True,  # Ollama通常不需要API密钥
                'openai': lambda k: k.startswith('sk-') and len(k) >= 20,
                'ali_image': lambda k: len(k) >= 10,
            }
            
            validator = provider_validators.get(provider.lower())
            if validator:
                if not validator(api_key):
                    self.logger.warning(f"API密钥格式不符合 {provider} 要求")
                    return False
            
            # 检查是否包含危险字符
            dangerous_patterns = [
                r'<script.*?>.*?</script>',
                r'javascript:',
                r'on\w+\s*=',
                r'[<>"\']',
            ]
            
            for pattern in dangerous_patterns:
                if re.search(pattern, api_key, re.IGNORECASE):
                    self.logger.warning(f"API密钥包含危险字符: {pattern}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"API密钥验证失败: {e}")
            return False
    
    def validate_model_name(self, model_name: str) -> bool:
        """验证模型名称"""
        try:
            if not self.validate_string(model_name, min_length=1, max_length=100):
                return False
            
            # 允许的字符：字母、数字、连字符、下划线、点
            if not re.match(r'^[a-zA-Z0-9._-]+$', model_name):
                self.logger.warning(f"模型名称包含非法字符: {model_name}")
                return False
            
            # 检查危险关键词
            dangerous_keywords = [
                '../', '..\\', 'javascript:', 'vbscript:',
                '<script', '</script>', 'onerror', 'onload',
                'eval(', 'exec(', 'system(', 'shell_exec'
            ]
            
            for keyword in dangerous_keywords:
                if keyword.lower() in model_name.lower():
                    self.logger.warning(f"模型名称包含危险关键词: {keyword}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"模型名称验证失败: {e}")
            return False
    
    def validate_prompt(self, prompt: str, max_length: int = 10000) -> bool:
        """验证提示词内容"""
        try:
            if not self.validate_string(prompt, min_length=1, max_length=max_length):
                return False
            
            # 检查SQL注入
            if self._detect_sql_injection(prompt):
                self.logger.warning("检测到SQL注入攻击")
                return False
            
            # 检查XSS攻击
            if self._detect_xss_attack(prompt):
                self.logger.warning("检测到XSS攻击")
                return False
            
            # 检查命令注入
            if self._detect_command_injection(prompt):
                self.logger.warning("检测到命令注入攻击")
                return False
            
            # 检查路径遍历
            if self._detect_path_traversal(prompt):
                self.logger.warning("检测到路径遍历攻击")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"提示词验证失败: {e}")
            return False
    
    def validate_json(self, json_str: str, max_size: int = 100000) -> bool:
        """验证JSON字符串"""
        try:
            if not self.validate_string(json_str, min_length=2, max_length=max_size):
                return False
            
            # 基本JSON格式检查
            if not re.match(r'^\s*[\{\[].*[\}\]]\s*$', json_str):
                self.logger.warning("JSON格式基本检查失败")
                return False
            
            # 尝试解析JSON
            parsed = json.loads(json_str)
            
            # 递归验证JSON内容
            return self._validate_json_content(parsed)
            
        except json.JSONDecodeError as e:
            self.logger.warning(f"JSON解析失败: {e}")
            return False
        except Exception as e:
            self.logger.error(f"JSON验证失败: {e}")
            return False
    
    def validate_url(self, url: str, allowed_schemes: List[str] = None) -> bool:
        """验证URL格式和安全性"""
        try:
            if not self.validate_string(url, min_length=10, max_length=2000):
                return False
            
            # 基本URL格式检查
            if not re.match(r'^https?://[\w\-._~:/?#\[\]@!$&\()*+,;=]+$', url):
                self.logger.warning(f"URL格式无效: {url[:50]}...")
                return False
            
            # 解析URL
            parsed = urlparse(url)
            
            # 检查协议
            if allowed_schemes and parsed.scheme not in allowed_schemes:
                self.logger.warning(f"不允许的URL协议: {parsed.scheme}")
                return False
            
            # 检查主机名
            if not parsed.hostname:
                self.logger.warning("URL缺少主机名")
                return False
            
            # 检查危险字符
            dangerous_chars = ['<', '>', '"', "'", '(', ')', '{', '}', '`']
            for char in dangerous_chars:
                if char in url:
                    self.logger.warning(f"URL包含危险字符: {char}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"URL验证失败: {e}")
            return False
    
    def validate_filename(self, filename: str, allowed_extensions: List[str] = None) -> bool:
        """验证文件名安全性"""
        try:
            if not self.validate_string(filename, min_length=1, max_length=255):
                return False
            
            # 基本文件名格式
            if not re.match(r'^[a-zA-Z0-9_\-\.]+$', filename):
                self.logger.warning(f"文件名包含非法字符: {filename}")
                return False
            
            # 检查路径遍历
            if '../' in filename or '..\\' in filename:
                self.logger.warning("文件名包含路径遍历攻击")
                return False
            
            # 检查扩展名
            if allowed_extensions:
                if '.' not in filename:
                    self.logger.warning("文件名缺少扩展名")
                    return False
                
                ext = filename.split('.')[-1].lower()
                if ext not in [e.lower() for e in allowed_extensions]:
                    self.logger.warning(f"不允许的文件扩展名: {ext}")
                    return False
            
            # 检查危险文件名
            dangerous_names = [
                'con', 'prn', 'aux', 'nul',
                'com1', 'com2', 'com3', 'com4',
                'lpt1', 'lpt2', 'lpt3', 'lpt4'
            ]
            
            name_without_ext = filename.split('.')[0].lower()
            if name_without_ext in dangerous_names:
                self.logger.warning(f"危险文件名: {filename}")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"文件名验证失败: {e}")
            return False
    
    def _detect_sql_injection(self, text: str) -> bool:
        """检测SQL注入攻击"""
        try:
            sql_patterns = [
                r'\bunion\b.*\bselect\b',
                r'\bselect\b.*\bfrom\b',
                r'\binsert\b.*\binto\b',
                r'\bupdate\b.*\bset\b',
                r'\bdelete\b.*\bfrom\b',
                r'\bdrop\b.*\btable\b',
                r'\bexec\s*\(',
                r'\bscript\b',
                r'javascript:',
                r'--\s*$',
                r'/\*.*\*/',
            ]
            
            for pattern in sql_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return True
            
            return False
            
        except Exception:
            return False
    
    def _detect_xss_attack(self, text: str) -> bool:
        """检测XSS攻击"""
        try:
            xss_patterns = [
                r'<script.*?>.*?</script>',
                r'javascript:',
                r'vbscript:',
                r'on\w+\s*=',
                r'<iframe.*?>',  
                r'<object.*?>',
                r'<embed.*?>',
                r'<form.*?>',
                r'eval\s*\(',
                r'expression\s*\(',
            ]
            
            for pattern in xss_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return True
            
            return False
            
        except Exception:
            return False
    
    def _detect_command_injection(self, text: str) -> bool:
        """检测命令注入攻击"""
        try:
            command_patterns = [
                r';\s*\w+',
                r'\|\|',
                r'&&',
                r'`.*`',
                r'\$\(.*?\)',
                r'\$\{.*?\}',
                r'<\(.*\)',
                r'>\(.*\)',
                r'\n.*\w+',
                r'\r.*\w+',
            ]
            
            for pattern in command_patterns:
                if re.search(pattern, text):
                    return True
            
            return False
            
        except Exception:
            return False
    
    def _detect_path_traversal(self, text: str) -> bool:
        """检测路径遍历攻击"""
        try:
            path_patterns = [
                r'\.\./',
                r'\.\.\\\\',
                r'%2e%2e%2f',
                r'%2e%2e%5c',
                r'\.\.\%2f',
                r'\.\.\%5c',
            ]
            
            for pattern in path_patterns:
                if re.search(pattern, text):
                    return True
            
            return False
            
        except Exception:
            return False
    
    def _validate_json_content(self, obj: Any, depth: int = 0) -> bool:
        """递归验证JSON内容"""
        try:
            if depth > 10:  # 防止递归过深
                return False
            
            if isinstance(obj, dict):
                for key, value in obj.items():
                    # 验证键名
                    if not self.validate_string(key, min_length=1, max_length=100):
                        return False
                    
                    # 递归验证值
                    if not self._validate_json_content(value, depth + 1):
                        return False
                        
            elif isinstance(obj, list):
                for item in obj:
                    if not self._validate_json_content(item, depth + 1):
                        return False
                        
            elif isinstance(obj, str):
                # 检查字符串内容
                if self._detect_sql_injection(obj) or self._detect_xss_attack(obj):
                    return False
                    
            return True
            
        except Exception:
            return False
    
    def create_safe_filename(self, text: str, max_length: int = 100) -> str:
        """从文本创建安全的文件名"""
        try:
            # 基本清理
            safe_text = re.sub(r'[^\w\s-]', '', text)
            safe_text = re.sub(r'[-\s]+', '-', safe_text)
            safe_text = safe_text.strip('-')
            
            # 长度限制
            if len(safe_text) > max_length:
                safe_text = safe_text[:max_length]
            
            # 确保不为空
            if not safe_text:
                safe_text = 'untitled'
            
            return safe_text.lower()
            
        except Exception as e:
            self.logger.error(f"创建安全文件名失败: {e}")
            return 'untitled'
    
    def get_validation_summary(self) -> Dict[str, Any]:
        """获取验证器状态摘要"""
        return {
            'patterns_loaded': len(self.patterns),
            'length_limits_defined': len(self.length_limits),
            'dangerous_chars_mapped': len(self.dangerous_chars),
            'timestamp': datetime.now().isoformat()
        }