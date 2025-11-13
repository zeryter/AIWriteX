# -*- coding: utf-8 -*-
"""
维度化创意引擎
实现基于多维度组合的创意生成机制
"""

import random
from typing import Dict, List, Any, Tuple
from ai_write_x.core.content_generation import ContentGenerationEngine
from ai_write_x.core.base_framework import (
    WorkflowConfig,
    AgentConfig,
    TaskConfig,
    WorkflowType,
    ContentType,
)


class DimensionalCreativeEngine:
    """
    维度化创意引擎
    支持基于多个维度的创意组合和生成
    """

    def __init__(self, config: Dict[str, Any]):
        """
        初始化维度化创意引擎

        Args:
            config: 维度化创意配置
        """
        self.config = config
        # 从配置中获取维度选项配置
        self.dimension_config = config.get("dimension_options", {})

    def get_available_dimensions(self, ignore_enabled_filter: bool = False) -> List[str]:
        """
        获取可用的维度分类列表

        Args:
            ignore_enabled_filter: 是否忽略enabled_dimensions过滤（用于自动选择模式）

        Returns:
            可用维度分类列表
        """
        # 获取所有可用维度
        all_dimensions = self.config.get("available_categories", [])

        if ignore_enabled_filter:
            # 自动选择模式：返回所有可用维度
            return all_dimensions
        else:
            # 手动选择模式：根据enabled_dimensions过滤
            enabled_dimensions = self.config.get("enabled_dimensions", {})
            available_dimensions = [
                dim for dim in all_dimensions if enabled_dimensions.get(dim, True)
            ]
            return available_dimensions

    def get_dimension_options(
        self, dimension: str, ignore_enabled_filter: bool = False
    ) -> List[Dict[str, Any]]:
        """
        获取指定维度的选项列表

        Args:
            dimension: 维度分类
            ignore_enabled_filter: 是否忽略enabled_dimensions过滤（用于自动选择模式）

        Returns:
            该维度的选项列表
        """
        if not ignore_enabled_filter:
            # 检查维度是否启用（仅在非自动选择模式下）
            enabled_dimensions = self.config.get("enabled_dimensions", {})
            if not enabled_dimensions.get(dimension, True):
                return []  # 如果维度未启用，返回空列表

        if dimension in self.dimension_config:
            options = self.dimension_config[dimension].get("preset_options", []).copy()
            # 检查是否有自定义选项
            custom_input = self.dimension_config[dimension].get("custom_input", "")
            if custom_input:
                # 添加自定义选项
                custom_option = {
                    "name": "custom",
                    "value": custom_input,
                    "weight": 1.0,
                    "description": "用户自定义",
                }
                options.append(custom_option)
            return options
        return []

    def select_dimensions(
        self, auto_selection: bool = True, max_dimensions: int = 5
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """
        选择维度组合

        Args:
            auto_selection: 是否自动选择
            max_dimensions: 最大维度数量

        Returns:
            选中的维度组合列表，每个元素为(维度分类, 选项)
        """
        selected_dimensions = []

        if auto_selection:
            # 自动选择维度：忽略enabled_dimensions限制
            available_categories = self.get_available_dimensions(ignore_enabled_filter=True)

            # 根据优先级选择维度
            priority_categories = self.config.get("priority_categories", [])

            # 收集候选维度组合
            candidate_dimensions = []

            # 首先从优先维度中选择
            for category in priority_categories:
                if category in available_categories:
                    options = self.get_dimension_options(category, ignore_enabled_filter=True)
                    if options:
                        for option in options:
                            candidate_dimensions.append((category, option))

            # 如果还需要更多维度，从其他可用维度中选择
            remaining_categories = [
                cat for cat in available_categories if cat not in priority_categories
            ]

            for category in remaining_categories:
                options = self.get_dimension_options(category, ignore_enabled_filter=True)
                if options:
                    for option in options:
                        candidate_dimensions.append((category, option))

            # 使用兼容性阈值过滤候选维度组合
            compatibility_threshold = self.config.get("compatibility_threshold", 0.6)

            # 随机选择维度组合并检查兼容性
            random.shuffle(candidate_dimensions)

            selected_count = 0
            for category, option in candidate_dimensions:
                # 创建临时维度组合来测试兼容性
                temp_dimensions = selected_dimensions + [(category, option)]
                compatibility_score = self.validate_dimension_compatibility(temp_dimensions)

                # 如果兼容性分数满足阈值要求，则添加到选中列表
                if compatibility_score >= compatibility_threshold:
                    selected_dimensions.append((category, option))
                    selected_count += 1
                    if selected_count >= max_dimensions:
                        break
        else:
            # 手动选择维度（从配置中获取用户选择的维度）：受enabled_dimensions限制
            selected_dims = self.config.get("selected_dimensions", [])
            compatibility_threshold = self.config.get("compatibility_threshold", 0.6)

            # 先收集所有手动选择的维度
            candidate_dimensions = []
            for dim_info in selected_dims:
                category = dim_info.get("category")
                option_name = dim_info.get("option")
                # 检查维度是否启用（手动选择模式下需要检查）
                enabled_dimensions = self.config.get("enabled_dimensions", {})
                if category and option_name and enabled_dimensions.get(category, True):
                    # 特殊处理自定义选项
                    if option_name == "custom":
                        # 获取自定义输入
                        dimension_config = self.dimension_config.get(category, {})
                        custom_input = dimension_config.get("custom_input", "")
                        if custom_input:
                            custom_option = {
                                "name": "custom",
                                "value": custom_input,
                                "weight": 1.0,
                                "description": "用户自定义",
                            }
                            candidate_dimensions.append((category, custom_option))
                    else:
                        options = self.get_dimension_options(category, ignore_enabled_filter=False)
                        for option in options:
                            if option.get("name") == option_name:
                                candidate_dimensions.append((category, option))
                                break

            # 按照兼容性阈值过滤维度组合
            # 逐个添加维度并检查兼容性
            for category, option in candidate_dimensions:
                # 创建临时维度组合来测试兼容性
                temp_dimensions = selected_dimensions + [(category, option)]
                compatibility_score = self.validate_dimension_compatibility(temp_dimensions)

                # 如果兼容性分数满足阈值要求，则添加到选中列表
                if compatibility_score > compatibility_threshold:
                    selected_dimensions.append((category, option))

        return selected_dimensions

    def generate_creative_prompt(
        self, base_content: str, selected_dimensions: List[Tuple[str, Dict[str, Any]]]
    ) -> str:
        """
        根据选中的维度生成创意提示

        Args:
            base_content: 基础内容
            selected_dimensions: 选中的维度组合

        Returns:
            创意提示文本
        """
        prompt_parts = []

        # 添加基础内容
        prompt_parts.append(f"基础内容：{base_content}")

        # 添加维度信息
        prompt_parts.append("\n创意维度要求：")
        for category, option in selected_dimensions:
            # 从配置中获取维度的显示名称
            category_name = self.dimension_config.get(category, {}).get("name", category)
            # 特殊处理自定义选项
            if option.get("name") == "custom":
                prompt_parts.append(f"- {category_name}：{option['value']} (用户自定义)")
            else:
                description = option["description"]
                prompt_parts.append(f"- {category_name}：{option['value']} ({description})")

        # 添加创意强度信息
        creative_intensity = self.config.get("creative_intensity", 1.0)
        intensity_desc = self._get_intensity_description(creative_intensity)
        prompt_parts.append(f"\n创意强度：{intensity_desc} ({creative_intensity})")

        # 添加其他配置信息
        if self.config.get("preserve_core_info"):
            prompt_parts.append("\n要求：在创意变换中保持文章核心信息不变")

        if self.config.get("allow_experimental"):
            prompt_parts.append("\n允许：使用实验性的维度组合")

        prompt_parts.append("\n请根据以上要求对基础内容进行创意变换，生成富有创意的文章。")

        return "\n".join(prompt_parts)

    def _get_intensity_description(self, intensity: float) -> str:
        """
        根据创意强度值获取描述

        Args:
            intensity: 创意强度值

        Returns:
            强度描述
        """
        if intensity < 0.8:
            return "保守"
        elif intensity < 1.0:
            return "适中"
        elif intensity < 1.2:
            return "激进"
        else:
            return "非常激进"

    def apply_dimensional_creative(self, content: str, title: str = "") -> str:
        """
        应用维度化创意到内容
        """

        if not self.config.get("enabled", False):
            return content

        # 选择维度组合
        auto_selection = self.config.get("auto_dimension_selection", True)
        max_dimensions = self.config.get("max_dimensions", 5)

        selected_dimensions = self.select_dimensions(auto_selection, max_dimensions)

        if not selected_dimensions:
            return content

        # 从title中提取topic
        clean_topic = title
        if "|" in clean_topic:
            clean_topic = clean_topic.split("|", 1)[1].strip()

        # 生成创意提示
        creative_prompt = self.generate_creative_prompt(content, selected_dimensions)

        # 创建维度化创意工作流
        workflow_config = self._create_dimensional_workflow_config(selected_dimensions)
        engine = ContentGenerationEngine(workflow_config)

        # 执行创意变换
        dimensions_list = []
        for category, option in selected_dimensions:
            dimensions_list.append({"category": category, "option": option})

        input_data = {
            "topic": clean_topic,
            "content": content,
            "creative_prompt": creative_prompt,
            "dimensions": dimensions_list,  # 使用转换后的格式
        }

        try:
            result = engine.execute_workflow(input_data)
            return result.content
        except Exception:
            return content

    def _create_dimensional_workflow_config(
        self, selected_dimensions: List[Tuple[str, Dict[str, Any]]]
    ) -> WorkflowConfig:
        """
        创建维度化创意工作流配置

        Args:
            selected_dimensions: 选中的维度组合

        Returns:
            工作流配置
        """
        # 构建维度描述
        dimension_descriptions = []
        for category, option in selected_dimensions:
            category_name = self.dimension_config.get(category, {}).get("name", category)
            if option.get("name") == "custom":
                dimension_descriptions.append(f"{category_name}: {option['value']} (用户自定义)")
            else:
                dimension_descriptions.append(
                    f"{category_name}: {option['value']} ({option['description']})"
                )

        dimensions_text = "\n".join([f"- {desc}" for desc in dimension_descriptions])

        # 创建智能体配置
        agents = [
            AgentConfig(
                role="维度化创意专家",
                name="dimensional_creative_agent",
                goal="根据指定的创意维度对内容进行创意变换",
                backstory=f"""你是一位擅长多维度创意变换的专家，能够根据不同的创意维度对内容进行深度改造。

当前应用的创意维度：
{dimensions_text}

你需要将这些维度的特点融合到内容中，创造出独特而富有创意的作品。
保持内容的核心信息不变，但要在表达方式、风格、视角等方面体现出这些维度的特色。""",
                tools=[],
            )
        ]

        # 创建任务配置
        creative_intensity = self.config.get("creative_intensity", 1.0)
        intensity_desc = self._get_intensity_description(creative_intensity)

        task_description = f"""对以下内容进行维度化创意变换：

原始内容：
{{content}}

创意要求：
{{creative_prompt}}

创意强度：{intensity_desc} ({creative_intensity})

请根据指定的创意维度对内容进行变换，确保：
1. 保持原内容的核心信息和主要观点
2. 融入各个维度的特色和风格
3. 创造出独特而富有创意的表达方式
4. 保持内容的逻辑性和可读性

输出格式：直接输出变换后的内容，不要包含任何解释或说明。"""

        tasks = [
            TaskConfig(
                name="dimensional_creative_transformation",
                description=task_description,
                agent_name="dimensional_creative_agent",
                expected_output="经过维度化创意变换的内容",
            )
        ]

        return WorkflowConfig(
            name="dimensional_creative_workflow",
            description="维度化创意变换工作流",
            workflow_type=WorkflowType.SEQUENTIAL,
            content_type=ContentType.ARTICLE,
            agents=agents,
            tasks=tasks,
        )

    def validate_dimension_compatibility(
        self, dimensions: List[Tuple[str, Dict[str, Any]]]
    ) -> float:
        """
        验证维度组合的兼容性

        Args:
            dimensions: 维度组合

        Returns:
            兼容性分数 (0-1)
        """
        if not dimensions:
            return 1.0

        # 检查是否有冲突的维度组合
        categories = [dim[0] for dim in dimensions]

        # 定义不兼容的维度组合对
        incompatible_pairs = [
            ("style", "format"),  # 文体风格和表达格式可能冲突
            ("time", "scene"),  # 时空背景和场景环境可能冲突
            ("personality", "tone"),  # 人格角色和语调语气可能冲突
            ("structure", "rhythm"),  # 文章结构和节奏韵律可能冲突
        ]

        conflicts = 0
        for cat1, cat2 in incompatible_pairs:
            if cat1 in categories and cat2 in categories:
                conflicts += 1

        # 检查维度数量是否过多
        max_dimensions = self.config.get("max_dimensions", 5)
        if len(dimensions) > max_dimensions:
            # 超出最大维度数量会降低兼容性
            excess_penalty = (len(dimensions) - max_dimensions) * 0.1
            conflicts += excess_penalty

        # 计算兼容性分数
        if conflicts == 0:
            return 1.0
        else:
            # 每个冲突降低0.3分，确保不兼容组合被过滤
            compatibility_score = max(0.0, 1.0 - conflicts * 0.3)
            return compatibility_score
