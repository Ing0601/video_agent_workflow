# from .base_session import BaseSessionService
from ..logger.logging import logger
from .base_session import BaseSessionService
from ..session.types import Session
from ..event.events import Event, EventType
from .base_session import SessionList
from typing import Optional, Dict, Any, List
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
import time
import json

class MySQLSessionService(BaseSessionService):
    """
    MySQL session service class
    """

    def __init__(self, db_url: str, **kwargs):
        """
        初始化MySQL会话服务
        """
        try:
            self.engine = create_engine(db_url, **kwargs)
            self.SessionLocal = sessionmaker(bind=self.engine)

            # 测试连接
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                logger.info("MySQL连接成功")
        except Exception as e:
            logger.error(f"MySQL连接失败: {e}")
            raise e

    async def create_session(
        self,
        *,
        user_id: str,
        session_id: Optional[str] = None,
        state: Optional[Dict[str, Any]] = None,
    ) -> Session:
        """
        create a new session                          # todo: 创建会话时，需要检查用户是否存在
        """
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        if state is None:
            state = {}
        
        current_time = time.time()
        
        def _create_session_sync():
            try:
                with self.SessionLocal() as db_session:
                    # 插入会话记录
                    insert_sql = text(
                        """
                        INSERT INTO sessions
                        (session_id, user_id, session_state, created_at, updated_at)
                        VALUES (:session_id, :user_id, :session_state, FROM_UNIXTIME(:current_time), FROM_UNIXTIME(:current_time))
                        """
                    )

                    db_session.execute(
                        insert_sql,
                        {
                            "session_id": session_id,
                            "user_id": user_id,
                            "session_state": json.dumps(state, ensure_ascii=False),
                            "current_time": current_time,
                        }
                    )
                    db_session.commit()
                    return True
            except SQLAlchemyError as e:
                logger.error(f"[{user_id}][{session_id}]创建会话失败: {e}")
                raise e


        # 在线程池中执行数据库操作，避免阻塞事件循环
        try:
            import asyncio

            await asyncio.to_thread(_create_session_sync)

            # 创建并返回Session对象
            session = Session(
                session_id=session_id,
                user_id=user_id,
                state=state,
                last_updated_time=current_time,
            )
            
            logger.info(f"[{user_id}][{session_id}]创建会话成功")
            return session
        except Exception as e:
            logger.error(f"[{user_id}][{session_id}]创建会话失败: {e}")
            raise e

    async def get_session(
        self,
        *,
        user_id: str,
        session_id: str,
        config: Optional[Any] = None,
    ) -> Optional[Session]:
        """获取会话"""
        try:
            with self.SessionLocal() as db_session:
                # 获取会话基本信息
                # session_sql = text(
                #     """
                #     SELECT session_id, user_id, session_state, FROM_UNIXTIME(updated_at) as last_update_time
                #     FROM sessions
                #     WHERE user_id = :user_id AND session_id = :session_id
                #     """
                # )
                session_sql = text(
                    """
                    SELECT session_id, user_id, session_state, UNIX_TIMESTAMP(updated_at) AS last_update_time
                    FROM sessions
                    WHERE user_id = :user_id AND session_id = :session_id
                    """
                )

                session_result = db_session.execute(
                    session_sql,
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                    },
                ).fetchone()

                if not session_result:
                    return None
                
                # 解析会话状态
                try:
                    state = json.loads(session_result.session_state)
                except (json.JSONDecodeError, TypeError) as e:
                    state = {}
                
                # 构造event查询条件
                event_conditions = ["session_id = :session_id"]
                event_params = {"session_id": session_id}

                event_sql = f"""
                SELECT event_type, event_id, UNIX_TIMESTAMP(timestamp) as timestamp, invocation_id, author, content,
                       tool_calls, tool_result, finish_reason, model, error
                FROM events
                WHERE {' AND '.join(event_conditions)}
                ORDER BY timestamp DESC
                """
                
                if config and config.num_recent_events:
                    event_sql += f" LIMIT {config.num_recent_events}"
                
                event_results = db_session.execute(
                    text(event_sql),
                    event_params,
                ).fetchall()

                events = []
                for event_row in event_results:
                    # 解析 JSON 字段
                    try:
                        tool_calls = json.loads(event_row.tool_calls) if event_row.tool_calls else None
                    except (json.JSONDecodeError, TypeError):
                        tool_calls = None

                    try:
                        tool_result = json.loads(event_row.tool_result) if event_row.tool_result else None
                    except (json.JSONDecodeError, TypeError):
                        tool_result = None

                    # 创建Event对象
                    event = Event(
                        type=event_row.event_type,
                        event_id=event_row.event_id,
                        user_id=user_id,
                        session_id=session_id,
                        invocation_id=event_row.invocation_id or "",
                        author=event_row.author or "main_agent",
                        timestamp=float(event_row.timestamp),
                        content=event_row.content,
                        tool_calls=tool_calls,
                        tool_result=tool_result,
                        finish_reason=event_row.finish_reason,
                        model=event_row.model,
                        error=event_row.error,
                    )

                    # todo
                    # 不是所有的event都添加到events中，而是只保留user和main_agent的最终回复;

                    events.append(event)
                
                # 创建Session对象
                session = Session(
                    session_id=session_id,
                    user_id=user_id,
                    events=events,
                    state=state,
                    last_updated_time=float(session_result.last_update_time),
                )

                logger.info(f"[{user_id}][{session_id}]获取会话成功, event count: {len(events)}")

                return session

        except SQLAlchemyError as e:
            logger.error(f"[{user_id}][{session_id}]获取会话失败: {e}")
            raise e
        except Exception as e:
            logger.error(f"[{user_id}][{session_id}]获取会话失败: {e}")
            raise e

    async def list_sessions(self, *, user_id: str) -> SessionList:
        """列出用户的会话"""
        try:
            with self.SessionLocal() as db_session:
                list_sql = text(
                    """
                    SELECT session_id, user_id, session_state, UNIX_TIMESTAMP(updated_at) AS last_update_time
                    FROM sessions
                    WHERE user_id = :user_id
                    ORDER BY updated_at DESC
                    """
                )

                results = db_session.execute(
                    list_sql, 
                    {"user_id": user_id}
                ).fetchall()

                sessions = []
                for row in results:
                    try:
                        state = json.loads(row.session_state)
                    except (json.JSONDecodeError, TypeError) as e:
                        state = {}

                    session = Session(
                        session_id=row.session_id,
                        user_id=row.user_id,
                        state=state,
                        last_updated_time=float(row.last_update_time),
                    )
                    sessions.append(session)
                
                logger.debug(f"[{user_id}] Sessions Listed successfully: {len(sessions)} sessions")

                return SessionList(sessions=sessions)
                
        except SQLAlchemyError as e:
            logger.error(f"[{user_id}] Sessions listing failed: {e}")
            raise ValueError(f"[{user_id}] Sessions listing failed: {e}")

    async def delete_session(self, *, user_id: str, session_id: str) -> None:
        """删除会话"""
        try:
            with self.SessionLocal() as db_session:
                # 删除会话相关的所有事件
                delete_events_sql = text(
                    """
                    DELETE FROM events
                    WHERE session_id = :session_id AND user_id = :user_id
                    """
                )

                events_result = db_session.execute(
                    delete_events_sql,
                    {"session_id": session_id, "user_id": user_id}
                )
                db_session.execute(delete_events_sql, {"session_id": session_id})

                delete_session_sql = text(
                    """
                    DELETE FROM sessions
                    WHERE user_id = :user_id AND session_id = :session_id
                    """
                )
                session_result =db_session.execute(delete_session_sql, {"user_id": user_id, "session_id": session_id})

                db_session.commit()

                if session_result.rowcount == 0:
                    raise ValueError(f"[{user_id}][{session_id}]会话不存在")

                logger.info(f"[{user_id}][{session_id}]会话删除成功, 删除事件: {events_result.rowcount}")

        except SQLAlchemyError as e:
            logger.error(f"[{user_id}][{session_id}]删除会话失败: {e}")
            raise ValueError(f"[{user_id}][{session_id}]删除会话失败: {e}")
        except Exception as e:
            logger.error(f"[{user_id}][{session_id}]删除会话失败: {e}")
            raise ValueError(f"[{user_id}][{session_id}]删除会话失败: {e}")

    async def append_event(self, session: Session, event: Event) -> Event:
        """向会话添加事件"""
        try:
            current_time = time.time()

            with self.SessionLocal() as db_session:
                # 检查会话是否存在且未过期
                check_sql = text(
                    """
                    SELECT UNIX_TIMESTAMP(updated_at) as last_update_time
                    FROM sessions 
                    WHERE session_id = :session_id AND user_id = :user_id
                """
                )

                session_result = db_session.execute(
                    check_sql,
                    {
                        "session_id": session.session_id,
                        "user_id": session.user_id,
                    },
                ).fetchone()

                if not session_result:
                    raise ValueError(f"会话不存在: {session.session_id}")

                # 检查会话是否过期（简单的并发控制）
                if (
                    session_result.last_update_time > session.last_updated_time + 1
                ):  # 允许1秒误差
                    raise ValueError(f"会话已过期，请重新获取: {session.session_id}")

                # 插入事件记录
                # 解析 Event 对象中的 JSON 字段
                event_dict = event.model_dump()
                tool_calls_json = json.dumps(event_dict.get("tool_calls"), ensure_ascii=False) if event_dict.get("tool_calls") else None
                tool_result_json = json.dumps(event_dict.get("tool_result"), ensure_ascii=False) if event_dict.get("tool_result") else None

                event_sql = text(
                    """
                    INSERT INTO events (
                        event_type, event_id, session_id, user_id, timestamp,
                        invocation_id, author, content, tool_calls, tool_result,
                        finish_reason, model, error
                    ) VALUES (
                        :p_type, :event_id, :session_id, :user_id, FROM_UNIXTIME(:timestamp),
                        :invocation_id, :author, :content, :tool_calls, :tool_result,
                        :finish_reason, :model, :error
                    )
                    """
                )

                db_session.execute(event_sql, {
                    "p_type": event.type,
                    "event_id": event.event_id,
                    "session_id": event.session_id,
                    "user_id": event.user_id,
                    "timestamp": event.timestamp,
                    "invocation_id": event.invocation_id,
                    "author": event.author,
                    "content": event.content,
                    "tool_calls": tool_calls_json,
                    "tool_result": tool_result_json,
                    "finish_reason": event.finish_reason,
                    "model": event.model,
                    "error": event.error,
                })

                # 更新时间戳
                update_time_sql = text(
                    """
                    UPDATE sessions 
                    SET updated_at = FROM_UNIXTIME(:current_time)
                    WHERE session_id = :session_id
                """
                )

                db_session.execute(
                    update_time_sql,
                    {"current_time": current_time, "session_id": session.session_id},
                )

                db_session.commit()

                # 更新内存中的会话对象
                session.events.append(event)
                session.last_updated_time = current_time

                logger.debug(
                    f"[{session.user_id}] [{session.session_id}] Event added successfully: {event.event_id} to session"
                )

                # 更新消息表, 只保留 user_message 和 complete_response 类型的事件
                if event.type in [EventType.USER_MESSAGE, EventType.COMPLETE_RESPONSE]:
                    await self.append_message(session, event)

                return event

        except SQLAlchemyError as e:
            logger.error(
                f"[{session.user_id}] [{session.session_id}] Event addition failed: {e}"
            )
            raise ValueError(f"添加事件失败: {e}") from e
    
    async def append_message(self, session: Session, event: Event):
        """向会话添加消息

        根据 event 的 type 过滤 user_message 和 complete_response，
        将相应内容存到 messages 表中
        """


        try:
            # 只处理 user_message 和 complete_response 类型的事件
            if event.type == EventType.USER_MESSAGE:
                role = "user"
            elif event.type == EventType.COMPLETE_RESPONSE:
                role = "assistant"
            else:
                # 忽略其他类型的事件
                return

            with self.SessionLocal() as db_session:

                # 首先查询特定user_id和session_id的累计token使用量，得到其最新的累计token使用量
                # 然后加上event.usage，得到新的累计token使用量
                query_accumulated_sql = text(
                    """
                    SELECT COALESCE(MAX(accumulated_usage), 0) AS accumulated_usage
                    FROM messages
                    WHERE user_id = :user_id AND session_id = :session_id
                """
                )
                result = db_session.execute(
                    query_accumulated_sql,
                    {"user_id": event.user_id, "session_id": event.session_id}
                )
                row = result.fetchone()
                accumulated_usage = (row.accumulated_usage if row else 0) + event.usage

                # 插入消息记录
                insert_sql = text(
                    """
                    INSERT INTO messages
                    (event_id, user_id, session_id, role, content, created_at, token_usage, accumulated_usage)
                    VALUES (:event_id, :user_id, :session_id, :role, :content, FROM_UNIXTIME(:timestamp), :token_usage, :accumulated_usage)
                    ON DUPLICATE KEY UPDATE
                        content = VALUES(content),
                        created_at = VALUES(created_at)
                    """
                )

                db_session.execute(
                    insert_sql,
                    {
                        "event_id": event.event_id,
                        "user_id": event.user_id,
                        "session_id": event.session_id,
                        "role": role,
                        "content": event.content,
                        "timestamp": event.timestamp,
                        "token_usage": event.usage,
                        "accumulated_usage": accumulated_usage,
                    }
                )
                db_session.commit()

                logger.info(
                    f"[{session.user_id}] [{session.session_id}] Message added successfully: "
                    f"event_id={event.event_id}, role={role}"
                )

        except SQLAlchemyError as e:
            logger.error(f"[{session.user_id}] [{session.session_id}] Message addition failed: {e}")
            raise ValueError(f"添加消息失败: {e}") from e
    
    def get_messages(self, user_id: str, session_id: str) -> List[Dict[str, Any]]:
        """
        根据user_id和session_id获取指定会话的消息
        """
        try:
            with self.SessionLocal() as db_session:
                messages_sql = text(
                    """
                    SELECT event_id, user_id, session_id, role, content, 
                        UNIX_TIMESTAMP(created_at) AS timestamp
                    FROM messages
                    WHERE user_id = :user_id AND session_id = :session_id
                    ORDER BY created_at ASC
                """
                )

                result = db_session.execute(
                    messages_sql,
                    {"user_id": user_id, "session_id": session_id},
                )
                rows = result.mappings().all()
                return rows

        except SQLAlchemyError as e:
            logger.error(f"[{user_id}] [{session_id}] Message retrieval failed: {e}")
            raise ValueError(f"Failed to retrieve messages: {e}") from e

    def close(self):
        """关闭数据库连接"""
        if hasattr(self, "engine"):
            self.engine.dispose()
            logger.info("MySQL connection closed")