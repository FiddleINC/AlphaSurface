"""Hand work to background sub-agents (they place results on the canvas)."""

from agent_tasks import dispatch


def dispatch_research(query: str) -> str:
    """
    Search the web and place a research card on the canvas.

    Use when the user asks about a real-world fact, recent event, or wants
    information researched. The card appears by itself in a few seconds;
    do not wait for it or describe it.

    query: what to research, phrased as a search request
    """
    dispatch("research", {"query": query}, source="canvas_agent")
    return f"Research started: {query}"


def dispatch_super_think() -> str:
    """
    Run a deep analysis of everything on the canvas (gaps, risks, next steps)
    and place the result as a cluster of notes. Use when the user asks to
    "super think", "deep dive", or "analyse the whole board". Takes ~30s.
    """
    dispatch("super_think", {}, source="canvas_agent")
    return "Deep analysis started"
