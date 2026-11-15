import os

PROMPTS_DIR = os.path.dirname(__file__)


def load_prompt(filename: str = "system.txt") -> str:
    with open(os.path.join(PROMPTS_DIR, filename), "r", encoding="utf-8") as f:
        return f.read().strip()
