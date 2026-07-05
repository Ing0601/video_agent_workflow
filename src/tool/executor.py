import json
import asyncio
from typing import List, Tuple, Dict, Any
from ..event.events import EventType
from ..tool.types import ToolCall
from .registor import TOOLS
from ..tool.types import ToolCallResult, ToolExeResult
from ..event.events import Event
import time
import uuid

class executor():
    def __init__(self,user_id:str,session_id:str,invocation_id:str,author:str):
        self.user_id = user_id
        self.session_id = session_id
        self.invocation_id = invocation_id
        self.author = author
    
    async def execute_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        if tool_name not in TOOLS:
            return ToolExeResult(
                success=False,
                error=f"Unknown tool: {tool_name}",
                result=f"Unknown tool: {tool_name}",
            )

        tool = TOOLS[tool_name]
        result = await tool.execute(**kwargs)
        return result
    
    async def execute_single_tool_streaming(
        self,
        tool_call: ToolCall,
    ):
        """
        Execute single tool call streaming
        """
        function_id = tool_call.id
        function_name = tool_call.function.name
        function_arguments = json.loads(tool_call.function.arguments)

        try:
            if function_name == "Task":
                task_tool = TOOLS["Task"]
                task_arguments = {
                    "description": function_arguments["description"],
                    "prompt": function_arguments["prompt"],
                    "subagent_type": function_arguments["subagent_type"],
                    "user_id": self.user_id,
                    "session_id": self.session_id,
                    "invocation_id": self.invocation_id,
                    "introduction": function_arguments["introduction"],
                    "task_id": function_id,
                    "function_id": function_id,
                    "function_name": function_name,
                }
                async for task_event in task_tool.execute_streaming(**task_arguments):
                    if task_event.type in [EventType.TASK_START, EventType.TASK_COMPLETE, EventType.TASK_ERROR]:
                        yield task_event
                pass
            else:
                result = None 

                result = await self.execute_tool(function_name, **function_arguments)  # todo: execute_tool

                toolcall_result = ToolCallResult(
                    tool_call_id=function_id,
                    function_name=function_name,
                    result=result,
                )

                yield Event(
                    type=EventType.TOOL_RESPONSE,
                    event_id=str(uuid.uuid4()),
                    user_id=self.user_id,
                    session_id=self.session_id,
                    invocation_id=self.invocation_id,
                    author=self.author,
                    timestamp=time.time(),
                    tool_result=toolcall_result,
                )
        except Exception as e:
            toolcall_result = ToolCallResult(
                tool_call_id=function_id,
                function_name=function_name,
                result=ToolExeResult(
                    success=False,
                    error=str(e),
                    result=str(e),
                ),
            )
            yield Event(
                type=EventType.ERROR,
                event_id=str(uuid.uuid4()),
                user_id=self.user_id,
                session_id=self.session_id,
                invocation_id=self.invocation_id,
                author=self.author,
                timestamp=time.time(),
                tool_result=toolcall_result,
                error=str(e),
            )
            return


    async def merge_tool_calls_run(
        self,
        tool_runs: List[Tuple[str, object]],
    ):
        """
        Merge tool calls run
        """
        if not tool_runs:
            return

        # tool call generators
        generators = [tool_run[1]for tool_run in tool_runs]

        tasks = [asyncio.create_task(generator.__anext__()) for generator in generators]
        pending_tasks = set(tasks)

        while pending_tasks:
            done, pending_tasks = await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)

            for task in done:
                try:
                    event = task.result()
                    yield event

                    # 继续处理下一步
                    for i, original_task in enumerate(tasks):
                        if task == original_task:
                            new_task = asyncio.create_task(generators[i].__anext__())
                            tasks[i] = new_task
                            pending_tasks.add(new_task)
                            break

                except StopAsyncIteration:
                    # 该生成器已经完成
                    continue
                except Exception as e:
                    # 该生成器发生异常
                    toolcall_result = ToolCallResult(
                        tool_call_id="",
                        function_name="",
                        result=ToolExeResult(
                            success=False,
                            error=str(e),
                            result=str(e),
                        ),
                    )
                    yield Event(
                        type=EventType.ERROR,
                        event_id=str(uuid.uuid4()),
                        user_id=self.user_id,
                        session_id=self.session_id,
                        invocation_id=self.invocation_id,
                        author=self.author,
                        timestamp=time.time(),
                        tool_result=toolcall_result,
                        error=str(e),
                    )
                    continue

    async def handle_tool_call_streaming(
        self,
        response,
    ):
        """
        Handle tool call streaming
        """
        if not hasattr(response, "choices") or not response.choices: 
            return 
        
        choice = response.choices[0]
        if not hasattr(choice.message, "tool_calls") or not choice.message.tool_calls:
            return
        
        tool_runs = []
        for tool_call in choice.message.tool_calls:
            tool_call_id = getattr(tool_call, "id", f"tool_{len(tool_runs)}")
            # produce single tool call streaming generator
            generator = self.execute_single_tool_streaming(tool_call)
            tool_runs.append((tool_call_id, generator))
        
        # merge tool calls run
        async for event in self.merge_tool_calls_run(tool_runs):
            if isinstance(event, dict) and "tool_call_id" not in event:
                event["tool_call_id"] = "unknown"
            yield event
    

