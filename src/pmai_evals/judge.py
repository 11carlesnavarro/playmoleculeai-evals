"""LLM judge for what code cannot check.

    grade(criteria, files=[...], text=...) -> [{"reason": ..., "pass": ...}, ...]   one call, a verdict a line
    judge(criterion, files=[...], text=...) -> bool

One fixed judge model and no fallback, so all trials get the same judge (JUDGE_MODEL and JUDGE_EFFORT
change it). The reasons go to JUDGE_LOG. A judge that cannot answer is an InfraError: no reward, not a 0.
"""

import base64
import json
import os
from pathlib import Path

import openai

from pmai_evals.reward import InfraError

MODEL = os.getenv("JUDGE_MODEL", "gpt-6.1-sol")
EFFORT = os.getenv("JUDGE_EFFORT", "high")
LOG = Path(os.getenv("JUDGE_LOG", "/logs/verifier/judge.md"))
IMAGES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
ASK = (
    "Judge each criterion on what the files and the text above show. A criterion passes only when it "
    "clearly holds; when you cannot see that it holds, it fails. Give the reason, then the verdict."
)


def _data_url(f: Path, media: str) -> str:
    return f"data:{media};base64,{base64.standard_b64encode(f.read_bytes()).decode()}"


def _content(files, text: str) -> list[dict]:
    content = [{"type": "input_text", "text": text}] if text else []
    for f in map(Path, files):
        suffix = f.suffix.lower()
        if suffix in IMAGES:
            content.append(
                {"type": "input_image", "image_url": _data_url(f, IMAGES[suffix]), "detail": "high"}
            )
        elif suffix == ".pdf":
            content.append(
                {"type": "input_file", "filename": f.name, "file_data": _data_url(f, "application/pdf")}
            )
        else:
            body = f.read_text(errors="replace")
            content.append({"type": "input_text", "text": f"<file name='{f.name}'>\n{body}\n</file>"})
    return content


def _schema(n: int) -> dict:
    verdict = {
        "type": "object",
        "properties": {"reason": {"type": "string"}, "pass": {"type": "boolean"}},
        "required": ["reason", "pass"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"verdicts": {"type": "array", "items": verdict, "minItems": n, "maxItems": n}},
        "required": ["verdicts"],
        "additionalProperties": False,
    }


def grade(criteria: list[str], files=(), text: str = "") -> list[dict]:
    listing = "\n".join(f"{i}. {c}" for i, c in enumerate(criteria, 1))
    try:
        r = _ask(files, text, listing, len(criteria))
    except openai.OpenAIError as e:
        raise InfraError(f"judge: {e}") from e
    if any(c.type == "refusal" for o in r.output if o.type == "message" for c in o.content):
        raise InfraError("the judge refused")
    verdicts = json.loads(r.output_text)["verdicts"]
    if len(verdicts) != len(criteria):
        raise InfraError(f"the judge gave {len(verdicts)} verdicts for {len(criteria)} criteria")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as log:
        for c, v in zip(criteria, verdicts, strict=True):
            log.write(f"## {c}\n\n{v['reason']}\n\n{'PASS' if v['pass'] else 'FAIL'}\n\n")
    return verdicts


def _ask(files, text: str, listing: str, n: int):
    return openai.OpenAI().responses.create(
        model=MODEL,
        reasoning={"effort": EFFORT},
        input=[
            {
                "role": "user",
                "content": [
                    *_content(files, text),
                    {"type": "input_text", "text": f"Criteria:\n{listing}\n\n{ASK}"},
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "verdicts",
                "strict": True,
                "schema": _schema(n),
            }
        },
    )


def judge(criterion: str, files=(), text: str = "") -> bool:
    return grade([criterion], files, text)[0]["pass"]
