"""Local runtime files and a process lock; never use these as remote isolation."""

import json
import os
from pathlib import Path
import re
import secrets


class GatewayLock:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.file = (directory / "gateway.lock").open("a+b")
        if self.file.tell() == 0:
            self.file.write(b"1")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("Tavrel is already running for this data directory.") from None

    def close(self):
        self.file.close()


def operator_key(directory: Path, create=False) -> str:
    path = directory / "operator.key"
    if create and not path.exists():
        directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("tvo_" + secrets.token_urlsafe(48) + "\n")
    if not path.exists():
        raise RuntimeError("Operator access key not found. Start the local gateway with 'python -m tavrel serve'.")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 32 or "\n" in value or "\r" in value:
        raise RuntimeError("The local operator key is invalid.")
    return value


def task_path(directory: Path, task_id: str) -> Path:
    if re.fullmatch(r"tsk_[a-f0-9]{16}", task_id) is None:
        raise RuntimeError("Provide a valid Tavrel task ID.")
    return directory / "tasks" / (task_id + ".json")


def save_task_connection(directory: Path, task_id: str, token: str, url: str) -> Path:
    path = task_path(directory, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"task_id": task_id, "task_token": token, "gateway_url": url}, handle, indent=2)
        handle.write("\n")
    os.replace(temporary, path)
    return path


def read_task_connection(directory: Path, task_id: str):
    path = task_path(directory, task_id)
    if not path.exists():
        raise RuntimeError("Task connection file not found. Create the task or rotate its token from the operator CLI.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("task_id") != task_id or not isinstance(value.get("task_token"), str):
        raise RuntimeError("The task connection file is invalid.")
    return value

