"""
安全的文件操作模块 - 提供安全的文件读写功能，防止目录遍历攻击
"""
import os
import shutil
import hashlib
from pathlib import Path
from typing import Optional, List, Union
import logging

from ai_write_x.utils.input_validator import InputValidator

logger = logging.getLogger(__name__)


class SecureFileManager:
    """安全的文件管理器，防止目录遍历和其他文件系统攻击"""
    
    def __init__(self, base_directory: Union[str, Path]):
        """
        初始化安全文件管理器
        
        Args:
            base_directory: 基础目录路径，所有文件操作都将限制在此目录内
        """
        self.base_directory = Path(base_directory).resolve()
        self.validator = InputValidator()
        
        # 确保基础目录存在
        self.base_directory.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"安全文件管理器初始化，基础目录: {self.base_directory}")
    
    def _resolve_safe_path(self, relative_path: str, must_exist: bool = False) -> Optional[Path]:
        """
        解析安全的文件路径，防止目录遍历攻击
        
        Args:
            relative_path: 相对路径
            must_exist: 是否必须存在
            
        Returns:
            Optional[Path]: 安全的绝对路径，如果路径不安全则返回None
        """
        try:
            # 清理路径
            clean_path = self.validator.sanitize_string(relative_path, max_length=500)
            
            # 验证路径
            if not self.validator.validate_path(clean_path, allow_absolute=False):
                logger.warning(f"路径验证失败: {relative_path}")
                return None
            
            # 解析相对路径
            resolved_path = (self.base_directory / clean_path).resolve()
            
            # 确保解析后的路径在基础目录内
            try:
                resolved_path.relative_to(self.base_directory)
            except ValueError:
                logger.warning(f"路径遍历攻击检测: {relative_path} -> {resolved_path}")
                return None
            
            # 检查文件是否存在（如果需要）
            if must_exist and not resolved_path.exists():
                logger.warning(f"文件不存在: {resolved_path}")
                return None
                
            return resolved_path
            
        except Exception as e:
            logger.error(f"路径解析失败: {relative_path}, 错误: {e}")
            return None
    
    def read_file(self, relative_path: str, encoding: str = 'utf-8', max_size: int = 10*1024*1024) -> Optional[str]:
        """
        安全地读取文件内容
        
        Args:
            relative_path: 相对路径
            encoding: 文件编码
            max_size: 最大文件大小（字节）
            
        Returns:
            Optional[str]: 文件内容，如果失败则返回None
        """
        safe_path = self._resolve_safe_path(relative_path, must_exist=True)
        if not safe_path:
            return None
        
        try:
            # 检查文件大小
            file_size = safe_path.stat().st_size
            if file_size > max_size:
                logger.warning(f"文件过大: {safe_path} ({file_size} bytes)")
                return None
            
            # 读取文件内容
            with safe_path.open('r', encoding=encoding) as f:
                content = f.read()
                
            logger.info(f"成功读取文件: {safe_path}")
            return content
            
        except (UnicodeDecodeError, PermissionError, OSError) as e:
            logger.error(f"文件读取失败: {safe_path}, 错误: {e}")
            return None
    
    def write_file(self, relative_path: str, content: str, encoding: str = 'utf-8') -> bool:
        """
        安全地写入文件内容
        
        Args:
            relative_path: 相对路径
            content: 文件内容
            encoding: 文件编码
            
        Returns:
            bool: 写入是否成功
        """
        safe_path = self._resolve_safe_path(relative_path)
        if not safe_path:
            return False
        
        try:
            # 确保父目录存在
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 验证内容安全性
            is_safe, error_msg = self.validator.validate_content_safety(content, max_length=50*1024*1024)
            if not is_safe:
                logger.warning(f"文件内容不安全: {error_msg}")
                return False
            
            # 写入文件
            with safe_path.open('w', encoding=encoding) as f:
                f.write(content)
                
            logger.info(f"成功写入文件: {safe_path}")
            return True
            
        except (PermissionError, OSError) as e:
            logger.error(f"文件写入失败: {safe_path}, 错误: {e}")
            return False
    
    def delete_file(self, relative_path: str) -> bool:
        """
        安全地删除文件
        
        Args:
            relative_path: 相对路径
            
        Returns:
            bool: 删除是否成功
        """
        safe_path = self._resolve_safe_path(relative_path, must_exist=True)
        if not safe_path:
            return False
        
        try:
            # 确保是文件而不是目录
            if safe_path.is_file():
                safe_path.unlink()
                logger.info(f"成功删除文件: {safe_path}")
                return True
            else:
                logger.warning(f"路径不是文件: {safe_path}")
                return False
                
        except (PermissionError, OSError) as e:
            logger.error(f"文件删除失败: {safe_path}, 错误: {e}")
            return False
    
    def list_files(self, relative_dir: str = "", pattern: str = "*") -> List[str]:
        """
        安全地列出文件
        
        Args:
            relative_dir: 相对目录
            pattern: 文件模式
            
        Returns:
            List[str]: 相对路径列表
        """
        safe_path = self._resolve_safe_path(relative_dir)
        if not safe_path:
            return []
        
        try:
            # 确保是目录
            if not safe_path.is_dir():
                logger.warning(f"路径不是目录: {safe_path}")
                return []
            
            # 列出文件
            files = []
            for file_path in safe_path.glob(pattern):
                if file_path.is_file():
                    try:
                        # 转换为相对路径
                        relative_file_path = file_path.relative_to(self.base_directory)
                        files.append(str(relative_file_path))
                    except ValueError:
                        # 不应该发生，因为已经通过 _resolve_safe_path 验证
                        continue
            
            logger.info(f"成功列出目录: {safe_path}, 找到 {len(files)} 个文件")
            return files
            
        except (PermissionError, OSError) as e:
            logger.error(f"列出文件失败: {safe_path}, 错误: {e}")
            return []
    
    def create_directory(self, relative_path: str) -> bool:
        """
        安全地创建目录
        
        Args:
            relative_path: 相对路径
            
        Returns:
            bool: 创建是否成功
        """
        safe_path = self._resolve_safe_path(relative_path)
        if not safe_path:
            return False
        
        try:
            safe_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"成功创建目录: {safe_path}")
            return True
            
        except (PermissionError, OSError) as e:
            logger.error(f"目录创建失败: {safe_path}, 错误: {e}")
            return False
    
    def get_file_hash(self, relative_path: str) -> Optional[str]:
        """
        获取文件哈希值
        
        Args:
            relative_path: 相对路径
            
        Returns:
            Optional[str]: 文件哈希值，如果失败则返回None
        """
        safe_path = self._resolve_safe_path(relative_path, must_exist=True)
        if not safe_path:
            return None
        
        try:
            # 计算文件哈希
            hasher = hashlib.sha256()
            with safe_path.open('rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            
            file_hash = hasher.hexdigest()
            logger.info(f"成功计算文件哈希: {safe_path}")
            return file_hash
            
        except (PermissionError, OSError) as e:
            logger.error(f"文件哈希计算失败: {safe_path}, 错误: {e}")
            return None
    
    def copy_file(self, source_relative_path: str, dest_relative_path: str) -> bool:
        """
        安全地复制文件
        
        Args:
            source_relative_path: 源相对路径
            dest_relative_path: 目标相对路径
            
        Returns:
            bool: 复制是否成功
        """
        source_path = self._resolve_safe_path(source_relative_path, must_exist=True)
        if not source_path:
            return False
        
        dest_path = self._resolve_safe_path(dest_relative_path)
        if not dest_path:
            return False
        
        try:
            # 确保目标目录存在
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 复制文件
            shutil.copy2(source_path, dest_path)
            logger.info(f"成功复制文件: {source_path} -> {dest_path}")
            return True
            
        except (PermissionError, OSError) as e:
            logger.error(f"文件复制失败: {source_path} -> {dest_path}, 错误: {e}")
            return False
    
    def get_file_size(self, relative_path: str) -> Optional[int]:
        """
        获取文件大小
        
        Args:
            relative_path: 相对路径
            
        Returns:
            Optional[int]: 文件大小（字节），如果失败则返回None
        """
        safe_path = self._resolve_safe_path(relative_path, must_exist=True)
        if not safe_path:
            return None
        
        try:
            return safe_path.stat().st_size
        except (PermissionError, OSError) as e:
            logger.error(f"获取文件大小失败: {safe_path}, 错误: {e}")
            return None
    
    def is_safe_path(self, relative_path: str) -> bool:
        """
        检查路径是否安全
        
        Args:
            relative_path: 相对路径
            
        Returns:
            bool: 路径是否安全
        """
        return self._resolve_safe_path(relative_path) is not None


# 预定义的目录管理器实例
class DirectoryManagers:
    """预定义的安全目录管理器"""
    
    _instances = {}
    
    @classmethod
    def get_article_manager(cls) -> SecureFileManager:
        """获取文章目录管理器"""
        if 'article' not in cls._instances:
from ai_write_x.utils.path_manager import PathManager
            article_dir = PathManager.get_article_dir()
            cls._instances['article'] = SecureFileManager(article_dir)
        return cls._instances['article']
    
    @classmethod
    def get_template_manager(cls) -> SecureFileManager:
        """获取模板目录管理器"""
        if 'template' not in cls._instances:
from ai_write_x.utils.path_manager import PathManager
            template_dir = PathManager.get_template_dir()
            cls._instances['template'] = SecureFileManager(template_dir)
        return cls._instances['template']
    
    @classmethod
    def get_image_manager(cls) -> SecureFileManager:
        """获取图片目录管理器"""
        if 'image' not in cls._instances:
from ai_write_x.utils.path_manager import PathManager
            image_dir = PathManager.get_image_dir()
            cls._instances['image'] = SecureFileManager(image_dir)
        return cls._instances['image']
    
    @classmethod
    def get_temp_manager(cls) -> SecureFileManager:
        """获取临时目录管理器"""
        if 'temp' not in cls._instances:
from ai_write_x.utils.path_manager import PathManager
            temp_dir = PathManager.get_temp_dir()
            cls._instances['temp'] = SecureFileManager(temp_dir)
        return cls._instances['temp']
    
    @classmethod
    def get_log_manager(cls) -> SecureFileManager:
        """获取日志目录管理器"""
        if 'log' not in cls._instances:
from ai_write_x.utils.path_manager import PathManager
            log_dir = PathManager.get_log_dir()
            cls._instances['log'] = SecureFileManager(log_dir)
        return cls._instances['log']