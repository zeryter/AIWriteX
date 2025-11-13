import time
from typing import Dict, Any
from crewai import Crew, Process, Task, Agent
from ai_write_x.core.base_framework import (
    BaseWorkflowFramework,
    WorkflowConfig,
    ContentResult,
    WorkflowType,
)
from ai_write_x.core.agent_factory import AgentFactory
from ai_write_x.core.monitoring import WorkflowMonitor
from ai_write_x.utils.content_parser import ContentParser
from ai_write_x.utils import utils


class ContentGenerationEngine(BaseWorkflowFramework):
    """纯内容生成引擎，与平台无关"""

    def __init__(self, config: WorkflowConfig):
        super().__init__(config)
        self.agent_factory = AgentFactory()
        # 添加监控器
        self.monitor = WorkflowMonitor.get_instance()

    def setup_agents(self) -> Dict[str, Agent]:
        """设置智能体"""
        agents = {}
        for agent_config in self.config.agents:
            agent = self.agent_factory.create_agent(agent_config)
            agents[agent_config.name] = agent
        return agents

    def setup_tasks(self) -> Dict[str, Task]:
        """设置任务"""
        tasks = {}
        for task_config in self.config.tasks:
            # 动态创建任务
            task = Task(
                description=task_config.description,
                expected_output=task_config.expected_output,
                agent=self.agents[task_config.agent_name],
            )

            # 设置上下文依赖
            if task_config.context:
                task.context = [tasks[ctx] for ctx in task_config.context if ctx in tasks]

            tasks[task_config.name] = task
        return tasks

    def execute_workflow(self, input_data: Dict[str, Any]) -> ContentResult:
        """执行工作流并记录监控数据"""
        start_time = time.time()
        success = False

        try:
            self.validate_config()
            # 分段计时：setup
            self.monitor.start_timer("setup")
            self.agents = self.setup_agents()
            self.tasks = self.setup_tasks()
            self.monitor.stop_timer("setup", self.config.name)

            # 根据工作流类型选择执行策略
            process_map = {
                WorkflowType.SEQUENTIAL: Process.sequential,
                WorkflowType.HIERARCHICAL: Process.hierarchical,
                WorkflowType.PARALLEL: Process.sequential,  # CrewAI暂不支持真正的并行
                WorkflowType.CUSTOM: Process.sequential,
            }

            process = process_map.get(self.config.workflow_type, Process.sequential)

            crew = Crew(
                agents=list(self.agents.values()),
                tasks=list(self.tasks.values()),
                process=process,
                verbose=True,
            )

            # 分段计时：kickoff
            self.monitor.start_timer("kickoff")
            result = crew.kickoff(inputs=input_data)
            self.monitor.stop_timer("kickoff", self.config.name)
            result = utils.remove_code_blocks(str(result))
            if input_data.get("parse_result", True):
                # 分段计时：parse
                self.monitor.start_timer("parse")
                parsed_result = self._parse_result(result, input_data)
                self.monitor.stop_timer("parse", self.config.name)
                if not parsed_result.title or parsed_result.title.lower() == "untitled":
                    parsed_result.title = input_data.get("title", None) or input_data.get(
                        "topic", "无标题"
                    )

            else:
                parsed_result = ContentResult(
                    title=input_data.get("title", None) or input_data.get("topic", "无标题"),
                    content=result,
                    summary="",
                    content_type=self.config.content_type,
                    content_format=input_data.get("content_format", "html"),
                    metadata={
                        "workflow_name": self.config.name,
                        "input_data": input_data,
                        "agent_count": len(self.agents),
                        "task_count": len(self.tasks),
                        "parsing_confidence": 1.0,
                    },
                )

            success = True
            return parsed_result
        except Exception as e:
            self.monitor.log_error(self.config.name, str(e), input_data)
            raise
        finally:
            # 记录执行指标
            duration = time.time() - start_time
            self.monitor.track_execution(self.config.name, duration, success)

    def _parse_result(self, raw_result: str, input_data: Dict[str, Any]) -> ContentResult:
        parser = ContentParser()
        parsed_content = parser.parse(raw_result)

        return ContentResult(
            title=parsed_content.title,
            content=parsed_content.content,
            summary=parsed_content.summary or self._generate_summary(parsed_content.content),
            content_format=parsed_content.metadata.get("content_type", "markdown"),
            content_type=self.config.content_type,
            metadata={
                "workflow_name": self.config.name,
                "input_data": input_data,
                "agent_count": len(self.agents),
                "task_count": len(self.tasks),
                "parsing_confidence": parsed_content.confidence,
            },
        )

    def _generate_summary(self, content: str) -> str:
        """生成内容摘要"""
        if not content:
            return ""

        # 取前200字符作为摘要
        summary = content[:200] + "..." if len(content) > 200 else content
        return summary
