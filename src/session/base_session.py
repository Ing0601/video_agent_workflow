from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from .types import Session
from abc import ABC, abstractmethod
from ..event.events import Event


class SessionList(BaseModel):
    """
    Session list model
    """
    sessions: List[Session] = Field(default_factory=list, description="Sessions")

class GetSessionConfig(BaseModel):
    pass

class BaseSessionService(ABC):
    """
    Base session service class
    """

    @abstractmethod
    async def create_session(
        self,
        *,
        user_id: str,
        session_id: Optional[str] = None,
        state: Optional[Dict[str, Any]] = None,
    ) -> Session:
        """
        Create a new session
        """
        pass
    
    @abstractmethod
    async def get_session(
        self,
        *,
        user_id: str,
        session_id: str,
        config: Optional[GetSessionConfig] = None,
    ) -> Optional[Session]:
        """
        Get a session by session ID
        """
        pass

    
    @abstractmethod
    async def list_sessions(
        self,
        *,
        user_id: str,
    ) -> SessionList:
        """
        List sessions
        """
        pass
    
    @abstractmethod
    async def delete_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> None:
        """
        Delete a session
        """
        pass

    @abstractmethod
    async def append_event(
        self, 
        session: Session,
        event: Event,
    ):
        """
        Append an event to a session
        """
        pass

    def _update_session_state(
        self,
        session: Session,
        event: Event,
    ) -> None:
        """
        Update the state of a session
        """
        pass