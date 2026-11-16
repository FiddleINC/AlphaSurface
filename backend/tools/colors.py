"""tldraw colors and the aliases models tend to use. Mirrors canvasActions.js."""

TL_COLORS = frozenset({
    "black", "grey", "light-violet", "violet", "blue", "light-blue",
    "yellow", "orange", "green", "light-green", "light-red", "red", "white",
})

COLOR_ALIASES = {
    "gray": "grey",
    "purple": "violet",
    "light-purple": "light-violet",
    "light-gray": "grey",
    "cyan": "light-blue",
    "teal": "blue",
    "pink": "light-red",
}


def normalize_color(color: str, default: str) -> str:
    """Map any color string to a tldraw color; unknown values fall back to `default`."""
    c = str(color or default).strip().lower().replace("_", "-").replace(" ", "-")
    c = COLOR_ALIASES.get(c, c)
    return c if c in TL_COLORS else default
