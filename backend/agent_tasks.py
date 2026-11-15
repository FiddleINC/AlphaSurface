"""Shared background task queue for sub-agents."""

import asyncio
from dataclasses import dataclass


@dataclass
class AgentTask:
    agent: str
    payload: dict
    source: str


_task_queue: asyncio.Queue[AgentTask] | None = None


def get_task_queue() -> asyncio.Queue[AgentTask]:
    global _task_queue
    if _task_queue is None:
        _task_queue = asyncio.Queue()
    return _task_queue


def dispatch(agent: str, payload: dict, source: str = "canvas_agent") -> None:
    get_task_queue().put_nowait(AgentTask(agent=agent, payload=payload, source=source))
    print(f"[TaskQueue] {source} -> {agent}: {payload}")
