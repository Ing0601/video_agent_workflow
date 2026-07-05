import os
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from ..logger.logging import logger
from ..utils.count_tokens import count_tokens

GENERIC_VIDEO_MESSAGE_ABSTRACT_SYSTEM_PROMPT = """你是一名专业助理，专门负责总结用户和Agent的对话。你的任务是将用户与视频剪辑处理Agent之间的交互历史转换为清晰、结构化的摘要，使视频剪辑Agent能够快速理解上下文并高效继续提供支持。

请严格按照下方 JSON 格式输出摘要：

{
  "user_intent": "用户的主要需求与意图",
  "key_issues": ["问题 1", "问题 2", "问题 3"],
  "video_editing_services": ["相关视频剪辑服务 1", "相关视频剪辑服务 2"],
  "video_editing_problems": [
    {
      "problem": "问题的详细描述",
      "solution": "已提供的解决方案",
      "status": "已解决 / 部分解决 / 未解决"
    }
  ],
  "user_messages": ["用户消息 1", "用户消息 2"],
  "key_responses":["关键回复 1", "关键回复 2"],
  "pending_tasks": ["待办事项 1", "待办事项 2"],
  "current_status": "当前处理状态",
  "next_steps": "建议的下一步行动"
}

要求：
1. **摘要控制在 3500 tokens 以内；**
2. 保持客观，并保留上下文连续性，准确反映对话内容；
3. 聚焦用户的核心需求与问题；
4. 记录视频剪辑处理Agent提供的所有解决方案及其结果；
5. 识别未解决的问题与需要跟进的事项；
6. 确保摘要全面、清晰、易于理解。
"""

GENERIC_VIDEO_MESSAGE_ABSTRACT_PROMPT = """请分析以下对话，并严格按照系统提示中指定的 JSON 格式生成结构化摘要：

对话历史：
{message_history}

请仔细分析对话内容，提取关键信息，并按要求的 JSON 格式输出摘要。"""


def _summarize_messages(messages_content: list) -> str:
    """
    调用 LLM 对消息内容进行摘要
    """
    try:
        from litellm import completion

        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        if not api_key:
            raise ValueError("缺少环境变量 OPENAI_API_KEY")
        if not base_url:
            raise ValueError("缺少环境变量 OPENAI_BASE_URL")

        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["OPENAI_BASE_URL"] = base_url

        content_parts = []
        for msg in messages_content:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            content_parts.append(f"{role}: {content}")

        combined_content = "\n".join(content_parts)

        response = completion(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": GENERIC_VIDEO_MESSAGE_ABSTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": GENERIC_VIDEO_MESSAGE_ABSTRACT_PROMPT.format(message_history=combined_content)},
            ],
        )

        summary = response.choices[0].message.content
        return summary if summary else ""

    except Exception as e:
        logger.error(f"LLM 摘要生成失败: {e}")
        raise e


class SessionStore:
    def __init__(self, db_url: str, **kwargs):
        """
        初始化会话存储服务
        """
        try:
            self.engine = create_engine(db_url, **kwargs)
            self.SessionLocal = sessionmaker(bind=self.engine)

            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                logger.info("MySQL连接成功")
        except Exception as e:
            logger.error(f"MySQL连接失败: {e}")
            raise e

    def check_threshold(self, user_id: str, session_id: str, threshold: int = 40) -> bool:
        """
        检查用户会话的累计token使用量是否超过阈值
        """
        try:
            with self.SessionLocal() as db_session:
                query_sql = text(
                    """
                    SELECT MAX(accumulated_usage) AS accumulated_usage
                    FROM messages
                    WHERE user_id = :user_id AND session_id = :session_id
                    """
                )
                result = db_session.execute(query_sql, {"user_id": user_id, "session_id": session_id})
                row = result.fetchone()
                accumulated_usage = row.accumulated_usage if row and row.accumulated_usage else 0
                return accumulated_usage > threshold
        except Exception as e:
            logger.error(f"检查用户会话的累计token使用量是否超过阈值失败: {e}")
            raise e

    def update_with_abstract(self, user_id: str, session_id: str) -> str:
        """
        对会话消息进行摘要并更新数据库
        """
        try:
            with self.SessionLocal() as db_session:
                query_sql = text(
                    """
                    SELECT role, content
                    FROM messages
                    WHERE user_id = :user_id AND session_id = :session_id
                    ORDER BY created_at ASC
                    """
                )
                result = db_session.execute(query_sql, {"user_id": user_id, "session_id": session_id})
                rows = result.fetchall()

                if not rows:
                    logger.info(f"[{user_id}] [{session_id}] 没有消息记录需要摘要")
                    return ""

                messages_content = [{"role": row.role, "content": row.content} for row in rows]
                summary = _summarize_messages(messages_content)

                delete_sql = text(
                    """
                    DELETE FROM messages
                    WHERE user_id = :user_id AND session_id = :session_id
                    """
                )
                db_session.execute(delete_sql, {"user_id": user_id, "session_id": session_id})

                abstract_event_id = f"abstract_{uuid.uuid4().hex[:16]}"
                insert_sql = text(
                    """
                    INSERT INTO messages
                    (event_id, user_id, session_id, role, content, created_at, token_usage, accumulated_usage)
                    VALUES (:event_id, :user_id, :session_id, :role, :content, NOW(), :token_usage, :accumulated_usage)
                    """
                )

                db_session.execute(
                    insert_sql,
                    {
                        "event_id": abstract_event_id,
                        "user_id": user_id,
                        "session_id": session_id,
                        "role": "assistant",
                        "content": "[abstract]" + summary,
                        "token_usage": count_tokens(summary),
                        "accumulated_usage": count_tokens(summary),
                    },
                )
                db_session.commit()

                logger.info(
                    f"[{user_id}] [{session_id}] 消息摘要更新成功，"
                    f"原始记录数: {len(rows)}, 摘要长度: {len(summary)}"
                )
                return summary

        except Exception as e:
            logger.error(f"[{user_id}] [{session_id}] 消息摘要更新失败: {e}")
            raise e

    def close(self):
        """
        关闭数据库连接
        """
        if hasattr(self, "engine"):
            self.engine.dispose()
            logger.info("MySQL connection closed")


class MySQLAbstractor(SessionStore):
    """Backward-compatible alias for the session store implementation."""

    pass
