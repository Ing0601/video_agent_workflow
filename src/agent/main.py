from .base import BaseAgent
from typing import Optional, List, Dict, Any
from ..logger import logger
from ..tool.registor import get_tool_schema
from ..session.mysql_service import MySQLSessionService
from ..event.events import EventType

class MainAgent(BaseAgent):
    """
    Main agent for handling user interactions and task delegation.

    This agent serves as the primary interface for user interactions
    and can delegate specialized tasks to sub-agents.
    """

    def __init__(
        self,
        prompt: str = "",
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        invocation_id: Optional[str] = None,
        model: str = "dashscope/qwen-max-latest",
        session_service=None,
        memory_service=None,
        session=None,
        user_message=None,
        parent_span_id: Optional[str] = None,
    ):
        """
        Initialize main agent.

        Args:
            prompt: The user prompt/message
            user_id: User identifier
            session_id: Session identifier
            invocation_id: Invocation identifier
            model: LLM model to use
            sub_invocation_id: Sub invocation identifier
            parent_span_id: Parent span ID for creating child spans
        """

        super().__init__(
            name="main_agent",
            tools=get_tool_schema("main_agent"),
            user_id=user_id,
            session_id=session_id,
            invocation_id=invocation_id,
            model=model,
            parent_span_id=parent_span_id,
        )

        self.prompt = prompt
        self.session_service = session_service
        self.memory_service = memory_service
        self.session = session
        self.user_message = user_message

    def build_messages(self, *args, **kwargs) -> List[Dict[str, str]]:
        """
        Build messages for main agent interaction.

        Returns:
            Messages list with system prompt and user query
        """

        messages = [
            {
                "role": "system",
                "content": self.prompt,
            }
        ]

        # 从数据库中获取用户会话的消息         # todo session_service
        if self.session_service is not None:
            db_messages =  self.session_service.get_messages(self.user_id, self.session_id)
            for msg in db_messages:
                messages.append({"role": msg["role"], "content": msg["content"]})

        # message_content = [
        #     {"type": "text", "text": user_preference_prompt},
        #     {"type": "text", "text": self.user_message},
        #     {
        #         "type": "text",
        #         "text": get_prompt_by_name(
        #             PROMPT_NAME_TODO_TOOL_REMINDER, TODO_TOOL_SYSTEM_REMINDER_PROMPT
        #         ),
        #     },
        # ]
        message_content = [
            {
                "type" : "text",
                "text" : self.user_message,
            },
        ]
        messages.append({"role": "user", "content": message_content})

        logger.info(
            f"[{self.session_id}] [{self.invocation_id}] Start streaming user message, message: {self.user_message}"
        )

        return messages

    async def handle_user_message(
        self
    ):
        """流式处理用户消息并生成回复

        return : 异步生成器用于流式响应;
        
        """
        if self.session_service is None:
            self.session_service = MySQLSessionService(db_url="mysql+pymysql://root:123456@localhost:3306/video_agent",)
            self.session = await self.session_service.get_session(user_id=self.user_id, session_id=self.session_id)
            if self.session is None:
                self.session = await self.session_service.create_session(user_id=self.user_id, session_id=self.session_id)

        response_generation = self.execute()

        async for chunk in response_generation:

            if chunk.type not in [EventType.RESPONSE_CHUNK, EventType.TOOL_CALL]:
                await self.session_service.append_event(self.session, chunk)

            yield chunk

            # print(" hello ")
        
        # print("hello")
        if self.session_service is not None:
            self.session_service.close()

    async def on_conversation_start(self) -> None:
        """
        Hook called before conversation starts.
        Must be implemented by subclasses.
        """
        pass

    async def on_conversation_end(self, result: Any, duration: float) -> None:
        """
        Hook called after conversation ends.
        Must be implemented by subclasses.

        Args:
            result: The final result from the conversation
            duration: Total duration of the conversation in seconds
        """
        pass    