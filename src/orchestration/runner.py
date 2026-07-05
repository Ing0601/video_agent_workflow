import os
import json
import time
from litellm import acompletion
import litellm
from ..event.events import EventType
from ..logger import logger
from dotenv import load_dotenv
from ..tool.executor import executor
from ..tool.types import ToolCall, ToolCallResponse, ToolCallResult
from ..event.events import Event
import uuid
from typing import List
load_dotenv()

def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

def convert_choices_to_json(choices) -> str:
    """将Choice数组对象转换为JSON字符串"""
    try:
        # 处理单个Choice对象的情况（向后兼容）
        if not isinstance(choices, (list, tuple)):
            choices = [choices]

        # 转换每个Choice对象
        choices_data = []
        for choice in choices:
            if hasattr(choice, "model_dump"):
                choice_data = choice.model_dump(exclude_unset=True)
            elif hasattr(choice, "__dict__"):
                choice_data = {
                    k: v for k, v in choice.__dict__.items() if v is not None
                }
            else:
                choice_data = str(choice)
            choices_data.append(choice_data)

        return json.dumps(choices_data, ensure_ascii=False)
    except Exception:
        # 异常处理：尝试将每个元素转为基本格式
        try:
            fallback_data = []
            if not isinstance(choices, (list, tuple)):
                choices = [choices]
            for choice in choices:
                if hasattr(choice, "__dict__"):
                    fallback_data.append(choice.__dict__)
                else:
                    fallback_data.append(str(choice))
            return json.dumps(fallback_data, ensure_ascii=False)
        except Exception:
            return json.dumps([str(choices)], ensure_ascii=False)

class runner():
    def __init__(self, 
        user_id:str,
        session_id:str,
        invocation_id:str,
        author="main_agent",
        tools=None, 
        model="dashscope/qwen-max-latest", 
        thinking=None, 
        safety=None, 
        session=None, 
        session_service=None, 
        executor:executor=None
    ):
        self.user_id = user_id
        self.session_id = session_id
        self.invocation_id = invocation_id
        self.tools = tools
        self.model = model
        self.thinking = thinking
        self.safety = safety
        self.session = session
        self.session_service = session_service
        self.author = author  
        self.api_base_url = os.getenv("DASHSCOPE_BASE_URL") 
        self.executor = executor
        self.messages = None
    
    async def run(self, messages):
        self.messages = messages
        try:
            completion_params = {
                "model": self.model,
                "messages": self.messages,
                "api_base": self.api_base_url,
                "temperature": 0.1,
                "parallel_tool_calls": False,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if self.tools:
                completion_params["tools"] = self.tools

            # litellm._turn_on_debug()  # 调试时开启，上线时注释掉

            response = await acompletion(**completion_params)

            full_content = ""
            tool_calls_dict = {}  # Accumulate tool calls by index
            completion_tokens = 0
            final_finish_reason = None


            async for chunk in response:
                # print("chunck: ", json.dumps(chunk.model_dump(), indent=2, ensure_ascii=False))
                choices = _get(chunk, "choices", [])
                if not choices:
                    continue
                
                chunk_id = _get(chunk, "id", str(uuid.uuid4()))
                choice0 = choices[0]
                delta = _get(choice0, "delta", None)
                delta_tool_calls = getattr(delta, "tool_calls", None)
                finish_reason = _get(choice0, "finish_reason", None)

                usage = _get(chunk, "usage", None)
                if usage:
                    completion_tokens = usage.completion_tokens

                content = _get(delta, "content", None) if delta is not None else None
                if content:
                    full_content += content
                    yield Event(
                        type=EventType.RESPONSE_CHUNK,
                        event_id=chunk_id,
                        user_id=self.user_id,
                        session_id=self.session_id,
                        invocation_id=self.invocation_id,
                        author=self.author,
                        timestamp=time.time(),
                        content=convert_choices_to_json(choices),
                        model=self.model,
                    )
                
                # Handle tool calls (they accumulate across chunks)   
                if delta_tool_calls:
                    # emit the tool call event when tool call are detected
                    yield Event(
                        type=EventType.TOOL_CALL,
                        event_id=chunk_id,
                        user_id=self.user_id,
                        session_id=self.session_id,
                        invocation_id=self.invocation_id,
                        author=self.author,
                        timestamp=time.time(),
                        content=convert_choices_to_json(choices),
                        model=self.model,
                    )
                    for tool_call in delta_tool_calls:
                        index = getattr(tool_call, "index", 0)
                        if index not in tool_calls_dict:
                            tool_calls_dict[index] = {
                                "id": getattr(tool_call, "id", ""),
                                "type": getattr(
                                    tool_call, "type", "function"
                                ),
                                "function": {
                                    "name": "",
                                    "arguments": "",
                                },
                            }

                        if hasattr(tool_call, "id") and tool_call.id:
                            tool_calls_dict[index]["id"] = tool_call.id

                        if (
                            hasattr(tool_call, "function")
                            and tool_call.function
                        ):
                            if (
                                hasattr(tool_call.function, "name")
                                and tool_call.function.name
                            ):
                                tool_calls_dict[index]["function"][
                                    "name"
                                ] += tool_call.function.name
                            if (
                                hasattr(tool_call.function, "arguments")
                                and tool_call.function.arguments
                            ):
                                tool_calls_dict[index]["function"][
                                    "arguments"
                                ] += tool_call.function.arguments

                if finish_reason:
                    final_finish_reason = finish_reason
                    # break

            ## handle tool calls
            tool_calls = None
            if tool_calls_dict:
                tool_calls = []
                for index in sorted(tool_calls_dict.keys()):
                    tool_call_data = tool_calls_dict[index]
                    tool_calls.append(
                        ToolCall(
                            id=tool_call_data["id"],
                            type=tool_call_data["type"],
                            name=tool_call_data["function"]["name"],
                            arguments=tool_call_data["function"]["arguments"],
                        )
                    )

            # Emit complete event
            complete_event = Event(
                type=EventType.COMPLETE_RESPONSE if final_finish_reason == "stop" else EventType.COMPLETE_CHOICE,
                event_id=chunk_id,
                user_id=self.user_id,
                session_id=self.session_id,
                invocation_id=self.invocation_id,
                author=self.author,
                timestamp=time.time(),
                content=full_content,
                tool_calls=[tc.to_dict() for tc in tool_calls] if tool_calls else None,
                finish_reason=final_finish_reason,
                usage=completion_tokens,
                model=self.model,
            )
            yield complete_event

            if not tool_calls:
                return

            ## call tools

            # inform that the tool calls are starting
            msg = "🛠️ Tool Call Starting:"
            for tool_call in tool_calls:
                msg += f"\n- Tool Call ID: {tool_call.id} \n- Tool Call Function Name: {tool_call.function.name} \n- Tool Call Function Arguments: {json.dumps(tool_call.function.arguments, indent=2, ensure_ascii=False)}\n"
            logger.info(msg)

            # Create a resposne object for tool handling compatibility
            tool_response = ToolCallResponse(content=full_content, tool_calls=tool_calls)

            # Execuate tool calls and collect results
            tool_results: List[ToolCallResult] = []

            async for tool_event in self.executor.handle_tool_call_streaming(tool_response):
                yield tool_event

                # original_tool_call_ids = [tc.id for tc in tool_calls]
                # event_tool_call_id = tool_event.tool_result.tool_call_id

                if (tool_event.type in [EventType.TOOL_RESPONSE, EventType.TASK_COMPLETE, EventType.TASK_ERROR]
                and tool_event.tool_result.tool_call_id in [tc.id for tc in tool_calls]):
                    tool_results.append(tool_event.tool_result)

            assistant_message = {"role": "assistant", "content": full_content}
            if tool_calls:
                api_tool_calls = []
                for tc in tool_calls:
                    api_tool_calls.append(
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                    )
            assistant_message["tool_calls"] = api_tool_calls
            self.messages.append(assistant_message)
            # print("="*100)
            # print("assistant_message: ", json.dumps(assistant_message, indent=2, ensure_ascii=False))
            # print("="*100)

            if tool_results:
                for tool_result in tool_results:
                    tool_message = {
                        "role": "tool",
                        "tool_call_id": tool_result.tool_call_id,
                        "function_name": tool_result.function_name,
                        "content": tool_result.result.model_dump_json(indent=2, ensure_ascii=False),
                    }
                    self.messages.append(tool_message)

            # print("*"*100)
            # print("messages: ", json.dumps(self.messages, indent=2, ensure_ascii=False))
            # print("*"*100)
            print("")
            async for chunk in self.run(self.messages):
                    yield chunk

        except Exception as e:
            logger.error(f"[{self.user_id}][{self.session_id}][{self.invocation_id}]Runner error: {e}")
            yield Event(
                type=EventType.ERROR,
                event_id=chunk_id if "chunk_id" in locals() and chunk_id else str(uuid.uuid4()),
                user_id=self.user_id,
                session_id=self.session_id,
                invocation_id=self.invocation_id,
                author=self.author,
                timestamp=time.time(),
                model=self.model,
                error=f"{type(e).__name__}: {e}",
            )