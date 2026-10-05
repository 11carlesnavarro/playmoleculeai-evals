"""LLM judge for what code cannot check. judge(rubric, files=[...], text=...) -> bool

One fixed judge model and no fallback, so all trials get the same judge.
"""

import base64
import os
from pathlib import Path

import anthropic

MODEL = os.getenv("JUDGE_MODEL", "claude-opus-5-5")
LOG = Path(os.getenv("JUDGE_LOG", "/logs/verifier/judge.md"))
KIND = {".png": ("image", "image/png"), ".pdf": ("document", "application/pdf")}
ASK = "Give your reasons, then PASS or FAIL alone on the last line."


def judge(rubric: str, files=(), text: str = "") -> bool:
    content = [{"type": "text", "text": text}] if text else []
    for f in map(Path, files):
        if f.suffix in KIND:
            kind, media = KIND[f.suffix]
            data = base64.standard_b64encode(f.read_bytes()).decode()
            content.append({"type": kind, "source": {"type": "base64", "media_type": media, "data": data}})
        else:
            body = f.read_text(errors="replace")
            content.append({"type": "text", "text": f"<file name='{f.name}'>\n{body}\n</file>"})
    content.append({"type": "text", "text": f"Rubric:\n{rubric}\n\n{ASK}"})
    with anthropic.Anthropic().messages.stream(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": content}],
    ) as stream:
        r = stream.get_final_message()
    if r.stop_reason == "refusal":
        raise RuntimeError("the judge refused")
    out = "".join(b.text for b in r.content if b.type == "text")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as log:
        log.write(f"## {rubric}\n\n{out}\n\n")
    lines = out.strip().splitlines()
    return bool(lines) and lines[-1].strip() == "PASS"
