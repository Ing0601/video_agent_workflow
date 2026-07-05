import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


class TaskStorage:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def task_dir(self, task_id: str) -> Path:
        path = self.base_dir / "tasks" / task_id
        path.mkdir(parents=True, exist_ok=True)
        (path / "intermediates").mkdir(exist_ok=True)
        (path / "outputs").mkdir(exist_ok=True)
        return path

    def intermediates_dir(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "intermediates"

    def outputs_dir(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "outputs"

    def save_json(self, task_id: str, relative_path: str, data: Any) -> str:
        path = self.task_dir(task_id) / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return str(path)

    def load_json(self, task_id: str, relative_path: str) -> Any:
        path = self.task_dir(task_id) / relative_path
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def append_event(self, task_id: str, event: Dict[str, Any]) -> None:
        path = self.task_dir(task_id) / "events.jsonl"
        event = {"timestamp": datetime.utcnow().isoformat(), **event}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
