from .base import BaseAgent
from typing import Optional, List, Dict, Any
from ..logger import logger
from ..tool.registor import get_tool_schema
from ..prompt.task import ANALYZER_AGENT_SYSTEM_PROMPT

class AnalyzerAgent(BaseAgent):
    """
    Main agent for handling user interactions and task delegation.

    This agent serves as the primary interface for user interactions
    and can delegate specialized tasks to sub-agents.
    """

    def __init__(
        self,
        prompt: str = "",
        introduction: str = "",
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        invocation_id: Optional[str] = None,
        sub_invocation_id: Optional[str] = None,
        model: str = "dashscope/qwen-max-latest",
        session_service=None,
        memory_service=None,
        session=None,
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
        """

        super().__init__(
            name="analyzer_agent",
            tools=get_tool_schema("analyzer_agent"),
            user_id=user_id,
            session_id=session_id,
            invocation_id=invocation_id,
            model=model,
        )

        self.prompt = prompt
        self.session_service = session_service
        self.memory_service = memory_service
        self.session = session
        self.user_id = user_id
        self.session_id = session_id
        self.invocation_id = invocation_id
        self.sub_invocation_id = sub_invocation_id

    def build_messages(self, *args, **kwargs) -> List[Dict[str, str]]:
        """
        Build messages for main agent interaction.

        Returns:
            Messages list with system prompt and user query
        """

        messages = [
            {
                "role": "system",
                "content": ANALYZER_AGENT_SYSTEM_PROMPT,
            }
        ]

        message_content = [
            {
                "type" : "text",
                "text" : self.prompt,
            },
        ]
        messages.append({"role": "user", "content": message_content})

        logger.info(
            f"[{self.session_id}] [{self.invocation_id}] Start streaming user message, message: {self.prompt}"
        )

        return messages
        """流式处理用户消息并生成回复

        return : 异步生成器用于流式响应;
        
        """

        # response_generation = self.execute()

        # async for chunk in response_generation:

        #     # print("chunk: ", chunk)

        #     yield chunk

        #     # print(" hello ")
        
        # # print("hello")

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