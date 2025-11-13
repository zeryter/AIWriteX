"""
输入验证模块 - 提供统一的输入验证功能
"""
import re
import os
from typing import Any, Optional, Union, List
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)


class InputValidator:
    """统一的输入验证器"""
    
    # 常见注入攻击模式
    SQL_INJECTION_PATTERNS = [
        r"(\b(union|select|insert|update|delete|drop|create|alter|exec|execute|script|declare|cast|convert)\b)",
        r"(\b(and|or|not|xor)\b.*\b(=|>|<|!)",
        r"(--|#|/\*|\*/)",
        r"(\bwaitfor\s+delay\b|\bdelay\s+'\d+')",
        r"(\bsp_\w+|xp_\w+)",
    ]
    
    # XSS攻击模式
    XSS_PATTERNS = [
        r"<script[^>]*>.*?</script>",
        r"javascript:",
        r"on\w+\s*=",
        r"<iframe[^>]*>",
        r"<object[^>]*>",
        r"<embed[^>]*>",
        r"<form[^>]*>",
        r"eval\s*\(",
        r"expression\s*\(",
        r"vbscript:",
        r"data:text/html",
    ]
    
    # 路径遍历模式
    PATH_TRAVERSAL_PATTERNS = [
        r"\.\./",
        r"\.\.\\",
        r"%2e%2e%2f",
        r"%252e%252e%252f",
        r"..%2f",
        r"%2e%2e/",
        r"%2e%2e\\",
    ]
    
    # 命令注入模式
    COMMAND_INJECTION_PATTERNS = [
        r"[;&|`]",
        r"\$\(",
        r"`[^`]*`",
        r"\|\|",
        r"&&",
        r"\n.*\n",
        r"\r.*\r",
    ]
    
    @staticmethod
    def validate_string(
        value: str,
        min_length: int = 0,
        max_length: int = 1000,
        allow_empty: bool = False,
        allowed_chars: Optional[str] = None,
        forbidden_patterns: Optional[List[str]] = None,
        required_patterns: Optional[List[str]] = None,
        field_name: str = "input"
    ) -> bool:
        """
        验证字符串输入
        
        Args:
            value: 要验证的字符串
            min_length: 最小长度
            max_length: 最大长度
            allow_empty: 是否允许空字符串
            allowed_chars: 允许的字符正则表达式
            forbidden_patterns: 禁止的模式列表
            required_patterns: 必需的模式列表
            field_name: 字段名称，用于错误消息
            
        Returns:
            bool: 验证是否通过
        """
        if not isinstance(value, str):
            logger.warning(f"{field_name}: 输入不是字符串类型")
            return False
            
        # 空字符串检查
        if not value.strip():
            if not allow_empty:
                logger.warning(f"{field_name}: 空字符串不被允许")
                return False
            return True
            
        # 长度检查
        if len(value) < min_length:
            logger.warning(f"{field_name}: 长度小于最小值 {min_length}")
            return False
            
        if len(value) > max_length:
            logger.warning(f"{field_name}: 长度超过最大值 {max_length}")
            return False
            
        # 字符检查
        if allowed_chars and not re.match(allowed_chars, value):
            logger.warning(f"{field_name}: 包含不允许的字符")
            return False
            
        # 禁止模式检查
        if forbidden_patterns:
            for pattern in forbidden_patterns:
                if re.search(pattern, value, re.IGNORECASE):
                    logger.warning(f"{field_name}: 检测到禁止模式 '{pattern}'")
                    return False
                    
        # 必需模式检查
        if required_patterns:
            for pattern in required_patterns:
                if not re.search(pattern, value):
                    logger.warning(f"{field_name}: 未找到必需模式 '{pattern}'")
                    return False
                    
        return True
    
    @staticmethod
    def sanitize_string(value: str, max_length: int = 1000) -> str:
        """
        清理字符串，移除潜在的危险字符
        
        Args:
            value: 要清理的字符串
            max_length: 最大长度
            
        Returns:
            str: 清理后的字符串
        """
        if not isinstance(value, str):
            return ""
            
        # 截断过长的字符串
        if len(value) > max_length:
            value = value[:max_length]
            
        # 移除控制字符
        value = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', value)
        
        # 移除潜在的HTML标签
        value = re.sub(r'<[^>]*>', '', value)
        
        # 移除JavaScript代码
        value = re.sub(r'javascript:', '', value, flags=re.IGNORECASE)
        
        # 移除事件处理器
        value = re.sub(r'on\w+\s*=', '', value, flags=re.IGNORECASE)
        
        # 标准化空白字符
        value = re.sub(r'\s+', ' ', value)
        
        return value.strip()
    
    @staticmethod
    def validate_path(path: str, allow_absolute: bool = False, allowed_extensions: Optional[List[str]] = None) -> bool:
        """
        验证文件路径
        
        Args:
            path: 文件路径
            allow_absolute: 是否允许绝对路径
            allowed_extensions: 允许的文件扩展名列表
            
        Returns:
            bool: 验证是否通过
        """
        if not isinstance(path, str):
            return False
            
        # 标准化路径
        normalized_path = os.path.normpath(path)
        
        # 检查路径遍历攻击
        if ".." in normalized_path:
            logger.warning(f"路径遍历攻击检测: {path}")
            return False
            
        # 检查绝对路径
        if os.path.isabs(normalized_path) and not allow_absolute:
            logger.warning(f"不允许绝对路径: {path}")
            return False
            
        # 检查禁止的字符
        forbidden_chars = ['<', '>', ':', '"', '|', '?', '*']
        if any(char in path for char in forbidden_chars):
            logger.warning(f"路径包含禁止字符: {path}")
            return False
            
        # 检查文件扩展名
        if allowed_extensions:
            ext = os.path.splitext(path)[1].lower()
            if ext not in [ext.lower() for ext in allowed_extensions]:
                logger.warning(f"不允许的文件扩展名: {ext}")
                return False
                
        return True
    
    @staticmethod
    def validate_url(url: str, allowed_schemes: Optional[List[str]] = None) -> bool:
        """
        验证URL
        
        Args:
            url: URL字符串
            allowed_schemes: 允许的协议列表
            
        Returns:
            bool: 验证是否通过
        """
        if not isinstance(url, str):
            return False
            
        try:
            parsed = urlparse(url)
            
            # 检查协议
            if not parsed.scheme:
                logger.warning(f"URL缺少协议: {url}")
                return False
                
            # 检查允许的协议
            if allowed_schemes and parsed.scheme not in allowed_schemes:
                logger.warning(f"不允许的协议 '{parsed.scheme}': {url}")
                return False
                
            # 检查主机名
            if not parsed.hostname:
                logger.warning(f"URL缺少主机名: {url}")
                return False
                
            # 检查IP地址
            if InputValidator._is_private_ip(parsed.hostname):
                logger.warning(f"不允许私有IP地址: {url}")
                return False
                
            # 检查端口
            if parsed.port:
                try:
                    port = int(parsed.port)
                    if not (1 <= port <= 65535):
                        logger.warning(f"无效端口: {port}")
                        return False
                except ValueError:
                    logger.warning(f"无效端口格式: {parsed.port}")
                    return False
                    
            return True
            
        except Exception as e:
            logger.warning(f"URL解析失败: {url}, 错误: {e}")
            return False
    
    @staticmethod
    def _is_private_ip(hostname: str) -> bool:
        """检查是否为私有IP地址"""
        import ipaddress
        
        try:
            # 尝试解析为IP地址
            ip = ipaddress.ip_address(hostname)
            
            # 检查私有IP范围
            return (
                ip.is_private or
                ip.is_loopback or
                ip.is_link_local or
                ip.is_multicast or
                ip.is_reserved
            )
        except ValueError:
            # 不是IP地址，可能是域名
            return False
    
    @staticmethod
    def validate_api_key(api_key: str, provider: str = "generic") -> bool:
        """
        验证API密钥格式
        
        Args:
            api_key: API密钥
            provider: 提供商名称
            
        Returns:
            bool: 验证是否通过
        """
        if not isinstance(api_key, str) or not api_key.strip():
            return False
            
        # 基本格式检查
        if len(api_key) < 10 or len(api_key) > 512:
            logger.warning(f"API密钥长度异常: {len(api_key)}")
            return False
            
        # 提供商特定的格式验证
        provider_patterns = {
            "openrouter": r"^sk-or-[a-zA-Z0-9-_]+$",
            "deepseek": r"^sk-[a-zA-Z0-9]{48}$",
            "openai": r"^sk-[a-zA-Z0-9]{48}$",
            "gemini": r"^AIza[0-9A-Za-z\-_]{35}$",
            "generic": r"^[a-zA-Z0-9-_]+$"
        }
        
        pattern = provider_patterns.get(provider.lower(), provider_patterns["generic"])
        
        if not re.match(pattern, api_key):
            logger.warning(f"API密钥格式不符合 {provider} 要求")
            return False
            
        return True
    
    @staticmethod
    def validate_content_safety(content: str, max_length: int = 10000) -> tuple[bool, str]:
        """
        验证内容安全性
        
        Args:
            content: 要验证的内容
            max_length: 最大长度
            
        Returns:
            tuple[bool, str]: (是否安全, 错误消息)
        """
        if not isinstance(content, str):
            return False, "内容必须是字符串"
            
        # 长度检查
        if len(content) > max_length:
            return False, f"内容长度超过限制 {max_length}"
            
        # SQL注入检查
        for pattern in InputValidator.SQL_INJECTION_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return False, "检测到SQL注入攻击模式"
                
        # XSS检查
        for pattern in InputValidator.XSS_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return False, "检测到XSS攻击模式"
                
        # 命令注入检查
        for pattern in InputValidator.COMMAND_INJECTION_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return False, "检测到命令注入攻击模式"
                
        # 路径遍历检查
        for pattern in InputValidator.PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                return False, "检测到路径遍历攻击模式"
                
        return True, ""
    
    @staticmethod
    def validate_integer(value: Any, min_value: Optional[int] = None, max_value: Optional[int] = None, field_name: str = "integer") -> bool:
        """
        验证整数输入
        
        Args:
            value: 要验证的值
            min_value: 最小值
            max_value: 最大值
            field_name: 字段名称
            
        Returns:
            bool: 验证是否通过
        """
        try:
            int_value = int(value)
            
            if min_value is not None and int_value < min_value:
                logger.warning(f"{field_name}: 值小于最小值 {min_value}")
                return False
                
            if max_value is not None and int_value > max_value:
                logger.warning(f"{field_name}: 值超过最大值 {max_value}")
                return False
                
            return True
            
        except (ValueError, TypeError):
            logger.warning(f"{field_name}: 无效的整数值 {value}")
            return False
    
    @staticmethod
    def validate_float(value: Any, min_value: Optional[float] = None, max_value: Optional[float] = None, field_name: str = "float") -> bool:
        """
        验证浮点数输入
        
        Args:
            value: 要验证的值
            min_value: 最小值
            max_value: 最大值
            field_name: 字段名称
            
        Returns:
            bool: 验证是否通过
        """
        try:
            float_value = float(value)
            
            if min_value is not None and float_value < min_value:
                logger.warning(f"{field_name}: 值小于最小值 {min_value}")
                return False
                
            if max_value is not None and float_value > max_value:
                logger.warning(f"{field_name}: 值超过最大值 {max_value}")
                return False
                
            return True
            
        except (ValueError, TypeError):
            logger.warning(f"{field_name}: 无效的浮点数值 {value}")
            return False


# 全局验证器实例
validator = InputValidator()