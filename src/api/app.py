import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from src.api.schemas import CommentaryWorkflowRequest, HighlightWorkflowRequest
from src.workflow.runners import run_commentary_graph_stream, run_highlight_graph_stream

load_dotenv()


class SSEResponse(StreamingResponse):
    def __init__(self, content, *args, **kwargs):
        super().__init__(content, *args, **kwargs)
        self.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        self.headers["Pragma"] = "no-cache"
        self.headers["Expires"] = "0"
        self.headers["Connection"] = "keep-alive"
        self.headers["Access-Control-Allow-Origin"] = "*"
        self.headers["X-Accel-Buffering"] = "no"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(**kwargs) -> FastAPI:
    app = FastAPI(
        title="General Video LangGraph Backend",
        description="LangGraph backend for highlight extraction and commentary generation",
        version="0.1.0",
        lifespan=lifespan,
        **kwargs,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    async def healthz():
        return JSONResponse(content={"msg": "OK"}, status_code=status.HTTP_200_OK)

    @app.get("/health")
    async def health():
        return JSONResponse(content={"msg": "OK"}, status_code=status.HTTP_200_OK)

    @app.post("/highlight_sse")
    async def highlight_sse(request: HighlightWorkflowRequest):
        task_id = f"highlight_{uuid.uuid4().hex[:12]}"
        output_dir = request.output_base_dir or "output/langgraph"
        initial_state = {
            "task_id": task_id,
            "task_type": "highlight",
            "input_videos": request.input_videos,
            "output_dir": output_dir,
            "generate_draft": bool(request.generate_draft),
            "draft_config": {
                "draft_output_dir": request.draft_output_dir,
                "goal_times": request.goal_times or [],
                "base_config": request.base_config or {},
            },
            "config": {
                "output_base_dir": output_dir,
                "fps": request.fps if request.fps is not None else 1.0,
                "max_workers": request.max_workers if request.max_workers is not None else 5,
                "save_intermediate": request.save_intermediate
                if request.save_intermediate is not None
                else True,
                "qwen_model": "qwen3-max",
                "temperature": 0.7,
                **(request.config or {}),
            },
        }

        async def event_generator() -> AsyncGenerator[str, None]:
            try:
                async for event in run_highlight_graph_stream(initial_state):
                    yield _sse(event)
                    await asyncio.sleep(0.01)
            except Exception as exc:
                yield _sse(
                    {
                        "event": "error",
                        "task_id": task_id,
                        "message": str(exc),
                    }
                )

        return SSEResponse(event_generator(), media_type="text/event-stream")

    @app.post("/commentary_sse")
    async def commentary_sse(request: CommentaryWorkflowRequest):
        task_id = f"commentary_{uuid.uuid4().hex[:12]}"
        output_dir = request.output_dir or "output/langgraph"
        initial_state = {
            "task_id": task_id,
            "task_type": "commentary",
            "mode": "template",
            "alignment_strategy": request.alignment_strategy or "video_fit_audio",
            "input_videos": request.input_videos,
            "demo_info": request.demo_info,
            "demo_info_path": request.demo_info_path,
            "text_template": request.text_template,
            "material_path": request.material_path or {},
            "corner_badge_files": request.corner_badge_files or [],
            "tail_frame_files": request.tail_frame_files or [],
            "user_demand": request.user_demand,
            "work_dir": request.work_dir,
            "output_dir": output_dir,
            "draft_name": request.draft_name or "解说前贴",
            "voice_type": request.voice_type or "BV411_streaming",
            "speed_ratio": request.speed_ratio or 1.2,
            "target_duration": request.target_duration,
            "config": request.config or {},
        }

        async def event_generator() -> AsyncGenerator[str, None]:
            try:
                async for event in run_commentary_graph_stream(initial_state):
                    yield _sse(event)
                    await asyncio.sleep(0.01)
            except Exception as exc:
                yield _sse(
                    {
                        "event": "error",
                        "task_id": task_id,
                        "message": str(exc),
                    }
                )

        return SSEResponse(event_generator(), media_type="text/event-stream")

    return app


def create_video_agent_app(**kwargs) -> FastAPI:
    """Backward-compatible factory name used by src/api/server.py."""
    return create_app(**kwargs)


app = create_app()
