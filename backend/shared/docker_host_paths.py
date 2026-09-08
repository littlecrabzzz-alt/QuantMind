"""Translate container paths for sibling containers without mixing code and data."""
import os
from pathlib import Path


def host_path(container_path: str, *, runtime_only: bool = False) -> str:
    code = Path(os.path.abspath(os.getenv("HOST_PROJECT_PATH") or os.getcwd()))
    sandbox = os.getenv("QM_NODE_ROLE") == "sandbox"
    configured = os.getenv("HOST_RUNTIME_PATH", "").strip()
    if configured and not Path(configured).is_absolute():
        raise ValueError("HOST_RUNTIME_PATH must be absolute")
    runtime = Path(os.path.abspath(configured)) if configured else code
    if sandbox and (not configured or runtime != code / ".local-dev/project"):
        raise ValueError("Sandbox requires HOST_RUNTIME_PATH=<HOST_PROJECT_PATH>/.local-dev/project")
    path = Path(os.path.normpath(container_path))
    if path.is_relative_to("/data"):
        relative = Path("data") / path.relative_to("/data")
    elif path.is_relative_to("/app"):
        relative = path.relative_to("/app")
    elif path.is_relative_to(code):
        relative = path.relative_to(code)
    elif path.is_absolute():
        if sandbox:
            raise ValueError(f"Unmapped sandbox host path: {path}")
        return str(path)
    else:
        relative = path
    if not relative.parts or ".." in relative.parts:
        raise ValueError(f"Invalid container path: {container_path}")
    is_runtime = relative.parts[0] in {"data", "db", "models", "logs", "user_pools_local"} or relative.parts[0].startswith("results")
    if runtime_only and not is_runtime:
        raise ValueError(f"Not a runtime path: {container_path}")
    return str((runtime if is_runtime else code) / relative)
