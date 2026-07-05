"""
Base agent class for both main agents and sub agents.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Any, Optional
import time
import json
import uuid

from ..logger import logger
from ..event.events import EventType
from ..orchestration.runner import runner
from ..tool.executor import executor
from ..event.events import Event
from ..utils.count_tokens import count_tokens

def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

class BaseAgent(ABC):
    """Base class for both main agents and sub agents"""

    def __init__(
        self,
        name: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        invocation_id: Optional[str] = None,
        model: str = "dashscope/qwen-max-latest",
        parent_span_id: Optional[str] = None,
    ):
        """
        Initialize base agent with common parameters.

        Args:
            name: Name of the agent
            tools: List of tool schemas available to this agent
            user_id: User identifier for the session
            session_id: Session identifier
            invocation_id: Invocation ID of current chat
            model: LLM model to use
            parent_span_id: Parent span ID for creating child spans
        """
        self.name = name
        self.tools = tools or []
        self.user_id = user_id
        self.session_id = session_id
        self.invocation_id = invocation_id
        self.model = model
        self.parent_span_id = parent_span_id
        self.executor = executor(user_id=user_id, session_id=session_id, invocation_id=invocation_id, author=name)
        self.runner = runner(user_id=user_id, session_id=session_id, invocation_id=invocation_id, tools=self.tools, model=model, author=name, executor=self.executor)
        

    def basic_info(self):
        return f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S %A')} UTC\n"

    @abstractmethod
    def build_messages(self, *args, **kwargs) -> List[Dict[str, str]]:
        """
        Build the messages array for LLM completion.
        Must be implemented by subclasses.
        """
        pass

    @abstractmethod
    async def on_conversation_start(self) -> None:
        """
        Hook called before conversation starts.
        Must be implemented by subclasses.
        """
        pass

    @abstractmethod
    async def on_conversation_end(self, result: Any, duration: float) -> None:
        """
        Hook called after conversation ends.
        Must be implemented by subclasses.

        Args:
            result: The final result from the conversation
            duration: Total duration of the conversation in seconds
        """
        pass

    async def execute(
        self,
        *args,
        thinking="None",
        safety="None",
        session=None,
        session_service=None,
        parent_span_id=None,
        **kwargs,
    ):
        """
        Main execution method that orchestrates the conversation flow with streaming.

        Args:
            thinking: Enable thinking mode ('enabled' or None), defaults to 'enabled'
            safety: Enable safety mode ('enabled' or None), defaults to 'enabled'
            session: Session object for database storage
            session_service: Session service for database operations
            parent_span_id: Parent span ID for tracing

        This method:
        1. Builds the messages from subclass implementation
        2. Calls conversation start hook
        3. Runs the recursive LLM completion with streaming
        4. Calls conversation end hook
        5. Yields streaming response chunks
        """
        start_time = time.time()

        try:
            # Build messages from subclass implementation
            messages = self.build_messages(*args, **kwargs)

            # Call conversation start hook
            await self.on_conversation_start()

            logger.info(
                f"[{self.session_id}] [{self.invocation_id}] Starting agent: {self.name} execution..."
            )
            logger.info(
                f"[{self.session_id}] [{self.invocation_id}] Agent: {self.name} available tools: {[t.get('function', {}).get('name', 'Unknown') for t in self.tools]}"
            )

            # Filter user messages and process content
            user_messages = [msg for msg in messages if msg.get("role") == "user"]

            if user_messages:
                # Take the last user message if multiple exist, otherwise the only one
                target_message = user_messages[-1]
                content = target_message.get("content", "")

                # Process content based on its type
                if isinstance(content, str):
                    # If content is string, return as single message array
                    processed_message = {"content": content, "role": "user"}
                elif isinstance(content, list) and content:
                    # If content is list, keep only the first item
                    processed_message = {"role": "user", "content": [content[0]]}
                else:
                    # Default case for empty or invalid content
                    processed_message = {"content": "", "role": "user"}

                filtered_messages = [processed_message]
            else:
                filtered_messages = []
            
            yield Event(
                type=EventType.USER_MESSAGE,
                event_id=str(uuid.uuid4()),
                user_id=self.user_id,
                session_id=self.session_id,
                invocation_id=self.invocation_id,
                author=self.name,
                timestamp=time.time(),
                content=json.dumps(
                    filtered_messages[0]["content"],
                    ensure_ascii=False,
                ),
                usage=count_tokens(str(filtered_messages[0]["content"])),
            )


            async for chunk in self.runner.run(messages):
                yield chunk

                if _get(chunk, "type", "") == EventType.COMPLETE_RESPONSE:
                    result = _get(chunk, "content", "")

            # Calculate duration and call end hook
            duration = time.time() - start_time
            result = None
            await self.on_conversation_end(result, duration)

        except Exception as e:
            # Ensure end hook is called even on error
            logger.warning(
                f"[{self.session_id}] [{self.invocation_id}] Agent {self.name} Execution failed: {e}"
            )
            duration = time.time() - start_time
            await self.on_conversation_end(None, duration)
            raise
