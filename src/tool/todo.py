import json
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import threading
from ..tool.types import ToolExeResult

from ..prompt.todo import (
    TODO_TOOL_DESC_PROMPT,
    TODO_TOOL_RESPONSE_PROMPT,
    TODO_TOOL_SYSTEM_REMINDER_ONLY_ONE_PROMPT,
)
from .base import BaseTool
from ..logger import logger


class Todo(BaseModel):
    id: str
    content: str
    status: str
    priority: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        return cls(
            id=data["id"],
            content=data["content"],
            status=data["status"],
            priority=data.get("priority", "medium"),
        )

class TodoSession(BaseModel):
    """Todo session model"""
    invocation_id: str
    todos: Dict[str, Todo] = Field(default_factory=dict, description="The todos of the session")
    last_updated: float = Field(default_factory=lambda: __import__("time").time())

    def update_timestamp(self):
        self.last_updated = __import__("time").time()


class TodoMemoryService:

    def __init__(self):
        self._sessions : Dict[str, TodoSession] = {}
        self._lock = threading.RLock()
    
    def get_session(self, invocation_id: str) -> TodoSession:
        """获取或创建会话"""
        with self._lock:
            if invocation_id not in self._sessions:
                self._sessions[invocation_id] = TodoSession(invocation_id=invocation_id)
            return self._sessions[invocation_id]
    
    def save_todos(self, invocation_id: str, todos: List[Todo]):
        """保存todos到指定会话"""
        with self._lock:
            session = self.get_session(invocation_id=invocation_id)

            # 清空
            session.todos.clear()

            # 增加新的todos
            for todo in todos:
                session.todos[todo.id] = todo
            
            session.update_timestamp()
        
    def update_todos_incrementally(self, invocation_id: str, new_todos: List[Todo]):
        """增量更新todos"""
        with self._lock:
            session = self.get_session(invocation_id=invocation_id)

            updated_count = 0
            added_count = 0

            # 处理每个新的todo
            for new_todo in new_todos:
                if new_todo.id in session.todos:
                    # 更新
                    session.todos[new_todo.id] = new_todo
                    updated_count += 1
                else:
                    # 新增
                    session.todos[new_todo.id] = new_todo
                    added_count += 1
            
            session.update_timestamp()

            # 返回更新统计和完整列表
            all_todos = list(session.todos.values())
            return {
                "updated": updated_count,
                "added": added_count,
                "total": len(all_todos),
                "todos": all_todos,
            }
    
    def load_todos(self, invocation_id: str) -> List[Todo]:
        """从指定会话中加载todos"""
        with self._lock:
            session = self.get_session(invocation_id)
            return list(session.todos.values())
    
    def update_todo(self, invocation_id: str, todo: Todo) -> None:
        """更新单个todo"""
        with self._lock:
            session = self.get_session(invocation_id=invocation_id)
            if todo.id in session.todos:
                session.todos[todo.id] = todo
                session.update_timestamp()
                return True
            else:
                return False

# 全局todo内存服务实例
_todo_memory_service: Optional[TodoMemoryService] = None
_service_lock = threading.RLock()

def get_todo_memory_service() -> TodoMemoryService:
    """获取全局唯一的todo内存服务实例"""
    global _todo_memory_service

    if _todo_memory_service is None:
        with _service_lock:
            if _todo_memory_service is None:
                _todo_memory_service = TodoMemoryService()
    
    return _todo_memory_service

def reset_todo_memory_service() -> None:
    """重置todo内存服务实例"""
    global _todo_memory_service
    with _service_lock:
        _todo_memory_service = None



class TodoWrite(BaseTool):
    def __init__(self):
        super().__init__()
        self.name = "TodoWrite"
        self.description = TODO_TOOL_DESC_PROMPT  # todo
        self.parameters = {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string", "minLength": 1},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                            "id": {"type": "string"},
                            "priority": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                                "default": "medium",
                            },
                        },
                        "required": ["content", "status", "id"],
                    },
                    "description": "The updated todo list",
                }
            },
            "required": ["todos"],
        }
        self.todo_memory_service = get_todo_memory_service()
        self._current_todos: List[Todo] = []

    def _load_todos_from_memory(self, invocation_id: str) -> List[Todo]:
        """从内存中加载todos"""
        try:
            return self.todo_memory_service.load_todos(invocation_id)
        except Exception as e:
            # 如果加载失败，返回空列表
            return []

    def _save_todos_to_memory(self, invocation_id: str, todos: List[Todo]):
        """将todos保存到内存"""
        try:
            self.todo_memory_service.save_todos(invocation_id, todos)
        except Exception as e:
            # 保存失败时记录错误但不中断执行
            pass

    def _validate_todo_data(self, todos: List[Dict[str, Any]]) -> Optional[str]:
        """验证to do数据"""
        seen_ids = set()
        for todo in todos:
            # 检查必需字段
            if "content" not in todo or "status" not in todo or "id" not in todo:
                return "Each todo must have content, status, and id fields"

            # 检查ID是否重复
            if todo["id"] in seen_ids:
                return f"Duplicate todo ID: {todo['id']}"
            seen_ids.add(todo["id"])

            # 检查状态值
            if todo["status"] not in ["pending", "in_progress", "completed"]:
                return f"Invalid status: {todo['status']}. Must be pending, in_progress, or completed"

            # 检查优先级值（如果提供了的话）
            if "priority" in todo and todo["priority"] not in ["low", "medium", "high"]:
                return f"Invalid priority: {todo['priority']}. Must be low, medium, or high"

        return None

    async def execute(
        self,
        todos: List[Dict[str, Any]],
        introduction: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """同步执行接口，内部调用异步版本"""
        import asyncio

        # 检查是否已经在事件循环中运行
        try:
            loop = asyncio.get_running_loop()
            # 如果在事件循环中，直接await执行
            return await self.execute_async(todos, **kwargs)
        except RuntimeError:
            # 不在事件循环中，创建新的并运行
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.execute_async(todos, **kwargs))
            finally:
                loop.close()

    async def execute_async(
        self,
        todos: List[Dict[str, Any]],
        introduction: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """异步执行to do更新"""
        session_id = kwargs.get("session_id", "")
        invocation_id = kwargs.get("invocation_id", "")

        validation = self.validate_params(todos=todos, introduction=introduction)
        if not validation["success"]:
            logger.error(
                f"[{session_id}] [{invocation_id}] Tool {self.name} Parameter validation failed"
            )
            return validation

        try:
            # 验证to do数据
            error_msg = self._validate_todo_data(todos)
            if error_msg:
                logger.error(
                    f"[{session_id}] [{invocation_id}] Tool {self.name} Parameter validation failed {error_msg}"
                )
                return {"success": False, "error": error_msg}

            # 补充默认priority
            for todo in todos:
                if "priority" not in todo:
                    todo["priority"] = "medium"

            # 转换新的todos
            new_todos = [Todo.from_dict(todo) for todo in todos]

            # 使用增量更新方法
            update_result = self.todo_memory_service.update_todos_incrementally(
                invocation_id, new_todos
            )

            # 更新当前状态为完整的to do列表
            self._current_todos = update_result["todos"]

            # 检测是否只剩一个 in_progress to do
            todos = update_result["todos"]
            in_progress_count = sum(1 for todo in todos if todo.status == "in_progress")
            total_pending_and_in_progress = sum(
                1 for todo in todos if todo.status in ["pending", "in_progress"]
            )

            # 获取基础的响应提示
            base_response = TODO_TOOL_RESPONSE_PROMPT

            # 如果只剩一个 in_progress to do，添加特殊提示
            if in_progress_count == 1 and total_pending_and_in_progress == 1:
                final_response = (
                    base_response + "\n\n" + TODO_TOOL_SYSTEM_REMINDER_ONLY_ONE_PROMPT
                )
            else:
                final_response = base_response

            return ToolExeResult(
                success=True,
                result=final_response,
            )

        except Exception as e:
            logger.error(
                f"[{session_id}] [{invocation_id}] Tool {self.name} Execution failed: {e}"
            )
            return ToolExeResult(
                success=False,
                error=f"Error updating todos: {str(e)}",
                result=f"Error updating todos: {str(e)}",
            )
            
    def get_current_todos(self, invocation_id: Optional[str] = None) -> List[Todo]:
        """获取当前的to do列表"""
        if invocation_id:
            return self.todo_memory_service.load_todos(invocation_id)
        return self._current_todos.copy()

    def get_todos_by_status(
        self, status: str, invocation_id: Optional[str] = None
    ) -> List[Todo]:
        """根据状态获取todos"""
        if invocation_id:
            return self.todo_memory_service.get_todos_by_status(invocation_id, status)
        return [todo for todo in self._current_todos if todo.status == status]

    def get_todos_by_priority(
        self, priority: str, invocation_id: Optional[str] = None
    ) -> List[Todo]:
        """根据优先级获取todos"""
        if invocation_id:
            return self.todo_memory_service.get_todos_by_priority(
                invocation_id, priority
            )
        return [todo for todo in self._current_todos if todo.priority == priority]

    def get_todo_summary(self, invocation_id: Optional[str] = None) -> Dict[str, Any]:
        """获取to do摘要统计"""
        if invocation_id:
            return self.todo_memory_service.get_todo_stats(invocation_id)

        total = len(self._current_todos)
        pending = len([t for t in self._current_todos if t.status == "pending"])
        in_progress = len([t for t in self._current_todos if t.status == "in_progress"])
        completed = len([t for t in self._current_todos if t.status == "completed"])

        high_priority = len([t for t in self._current_todos if t.priority == "high"])
        medium_priority = len(
            [t for t in self._current_todos if t.priority == "medium"]
        )
        low_priority = len([t for t in self._current_todos if t.priority == "low"])

        return {
            "total": total,
            "by_status": {
                "pending": pending,
                "in_progress": in_progress,
                "completed": completed,
            },
            "by_priority": {
                "high": high_priority,
                "medium": medium_priority,
                "low": low_priority,
            },
            "completion_rate": completed / total if total > 0 else 0,
        }
