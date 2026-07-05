import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional
from pydantic import BaseModel, Field

# if TYPE_CHECKING:
#     from ..agent.base import BaseAgent

from .base import BaseTool
from ..prompt.task import TASK_TOOL_DESC_PROMPT
from ..logger import logger
from ..event.events import EventType, Event
from .types import ToolExeResult, ToolCallResult
import asyncio

class TaskExecution(BaseModel):   # 
    """Task execution model"""
    task_id: str
    description: str
    subagent_type: str
    status: str = Field("initializing", description="Enum: initializing, running, completed, error, cancelled")
    start_time: float = Field(time.time(), description="Start time of the task execution")
    end_time: float = Field(None, description="End time of the task execution")
    result: Any = Field(None, description="Result of the task execution")
    error: str = Field(None, description="Error message of the task execution")
    progress_events: Any = Field(None, description="Progress events of the task execution")
    sub_agent: Optional[Any] = Field(None, description="Sub agent of the task execution")

    def update_status(self, status: str, result: Any = None, error: str = None):
        """"更新任务状态"""
        self.status = status
        if result is not None:
            self.result = result
        if error:
            self.error = error
        if status in ["completed", "error", "cancelled"]:
            self.end_time = time.time()

    def get_duration(self) -> float:
        if self.end_time is not None:
            return self.end_time - self.start_time
        return time.time() - self.start_time


class Task(BaseTool):
    def __init__(self):
        super().__init__()
        self.name = "Task"
        self.description = TASK_TOOL_DESC_PROMPT
        self.parameters = {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "A short (3-5 word) description of the task",
                },
                "prompt": {
                    "type": "string",
                    "description": "The detailed task description for the agent to perform, including all necessary information, such as file paths, etc.",
                },
                "subagent_type": {
                    "type": "string",
                    "description": "The type of specialized agent to use for this task",
                },
            },
            "required": ["description", "prompt", "subagent_type"],
        }

        # 可用 subagent 类型
        self.available_agents = {
            "Analyzer": "Analyze the media content and provide a detailed analysis",
        }

        # 任务执行状态跟踪
        self.active_tasks = {}

    def _create_sub_agent(
        self,
        subagent_type: str,
        prompt: str,
        task_id: str,
        **context,
    ):
        """创建专业化sub agent"""
        # 通用参数
        agent_kwargs = {
            "prompt": prompt,
            "sub_invocation_id": task_id,
            **context,
        }
        # 根据agent type创建对应的sub agent
        if subagent_type == "Analyzer":
            from ..agent.analyzer import AnalyzerAgent
            return AnalyzerAgent(**agent_kwargs)
        else:
            raise ValueError(f"Unknown subagent type: {subagent_type}")
    
    async def _cleanup_task_later(self, task_id: str, delay: float = 300):
        """延迟清理任务记录（5分钟后）"""
        await asyncio.sleep(delay)
        if task_id in self.active_tasks:
            del self.active_tasks[task_id]

    async def execute(self, **kwargs) -> Dict[str, Any]:
        pass

    async def execute_streaming(
        self,
        description: str,
        prompt: str,
        subagent_type: str,
        user_id: str,
        session_id: str,
        invocation_id:str,
        introduction: str,
        task_id: str,
        function_id: str,
        function_name: str,
        session: Optional[Any] = None,
        session_service: Optional[Any] = None,
    ):
        """
        Execute task with streaming events
        """
        validation = self.validate_params(
            description=description,
            prompt=prompt,
            subagent_type=subagent_type,
            introduction=introduction,
        )

        if not validation["success"]:
            logger.error(f"Task validation failed: {validation['error']}")
            tool_result = ToolCallResult(
                tool_call_id=function_id,
                function_name=function_name,
                result=ToolExeResult(
                    success=False,
                    error=validation["error"],
                    result=validation["error"],
                ),
            )

            yield Event(
                type=EventType.TASK_ERROR,
                event_id=str(uuid.uuid4()),
                user_id=user_id,
                session_id=session_id,
                invocation_id=invocation_id,
                author=subagent_type,
                timestamp=time.time(),
                tool_result=tool_result,
            )
            return
        
        if subagent_type not in self.available_agents:
            logger.error(f"Invalid subagent type: {subagent_type}")
            tool_result = ToolCallResult(
                tool_call_id=function_id,
                function_name=function_name,
                result=ToolExeResult(
                    success=False,
                    error=f"Invalid subagent type: {subagent_type}",
                    result=f"Invalid subagent type: {subagent_type}",
                ),
            )
            yield Event(
                type=EventType.TASK_ERROR,
                event_id=str(uuid.uuid4()),
                user_id=user_id,
                session_id=session_id,
                invocation_id=invocation_id,
                author=subagent_type,
                timestamp=time.time(),
                tool_result=tool_result,
            )
            return
        
        # 创建任务ID和执行跟踪
        task_execuation = TaskExecution(task_id=task_id, description=description, subagent_type=subagent_type)
        self.active_tasks[task_id] = task_execuation
        try:
            yield Event(
                type=EventType.TASK_START,
                event_id=str(uuid.uuid4()),
                user_id=user_id,
                session_id=session_id,
                invocation_id=invocation_id,
                author=subagent_type,
                timestamp=time.time(),
                content=f"Task started: {description}",
            )

            task_execuation.update_status("running")

            # 创建sub agent, 传递会话上下文
            context = {}
            if user_id:
                context["user_id"] = user_id
            if session_id:
                context["session_id"] = session_id
            if invocation_id:
                context["invocation_id"] = invocation_id
            
            sub_agent = self._create_sub_agent(subagent_type, prompt, task_id, **context)
            task_execuation.sub_agent = sub_agent

            logger.info(f"[{session_id}][{invocation_id}]Created sub agent: {sub_agent.name}")

            # 追踪sub agent执行
            response_content = ""
            start_time = time.time()
            async for chunk in sub_agent.execute(
                session=session,
                session_service=session_service,
            ):
                # 处理流式响应
                if chunk.type == EventType.COMPLETE_RESPONSE:
                    response_content = chunk.content
                else:
                    chunk.invocation_id = task_id
                    yield chunk

            duration = time.time() - start_time

            logger.info(f"[{session_id}][{invocation_id}]Task {task_id} completed in {duration:.2f} seconds")

            tool_result = ToolCallResult(
                tool_call_id=function_id,
                function_name=function_name,
                result=ToolExeResult(
                    success=True,
                    result=response_content,
                ),
            )

            task_execuation.update_status("completed", response_content)

            yield Event(
                type=EventType.TASK_COMPLETE,
                event_id=str(uuid.uuid4()),
                user_id=user_id,
                session_id=session_id,
                invocation_id=invocation_id,
                author=subagent_type,
                timestamp=time.time(),
                tool_result=tool_result,
            )

        except Exception as e:
            logger.error(f"[{session_id}][{invocation_id}]Task {task_id} failed: {e}")
            task_execuation.update_status("error", error=str(e))
            tool_result = ToolCallResult(
                tool_call_id=function_id,
                function_name=function_name,
                result=ToolExeResult(
                success=False,
                    error=str(e),
                    result=str(e),
                ),
            )
            yield Event(
                type=EventType.TASK_ERROR,
                event_id=str(uuid.uuid4()),
                user_id=user_id,
                session_id=session_id,
                invocation_id=invocation_id,
                author=subagent_type,
                timestamp=time.time(),
                tool_result=tool_result,
            )

        finally:
            pass
            # if task_id in self.active_tasks:
            #     asyncio.create_task(self._cleanup_task_later(task_id))
