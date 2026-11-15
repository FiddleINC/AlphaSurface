"""Routes queued tasks to registered sub-agent handlers (non-blocking)."""

import asyncio
import traceback
from typing import Awaitable, Callable

from agent_tasks import AgentTask, get_task_queue

AgentHandler = Callable[[dict], Awaitable[None]]
_handlers: dict[str, AgentHandler] = {}


def register_handler(agent_name: str, handler: AgentHandler) -> None:
    _handlers[agent_name] = handler


async def _run(task: AgentTask, handler: AgentHandler) -> None:
    try:
        await handler(task.payload)
    except Exception as e:
        print(f"[Dispatcher] Handler '{task.agent}' failed: {e}")
        traceback.print_exc()


async def run_dispatcher() -> None:
    queue = get_task_queue()
    while True:
        try:
            task: AgentTask = await queue.get()
            handler = _handlers.get(task.agent)
            if handler is None:
                print(f"[Dispatcher] No handler for '{task.agent}', dropped")
                continue
            asyncio.create_task(_run(task, handler))
        except asyncio.CancelledError:
            break
