#!/usr/bin/env python3
"""Reject or rewrite expensive native failures before provider inference."""
from __future__ import annotations
import os,re

_UNSUITABLE=("figma","browser login","send email","google drive","manual approval","production secret")
_PATH=re.compile(r"(?<![\w/])(?:[\w.-]+/)+[\w.-]+\.(?:py|js|jsx|ts|tsx|vue|go|rs|sql|md|json)")

def distill(task,prompt,repo=""):
    raw=(prompt or "").strip(); lower=raw.lower()
    blockers=[x for x in _UNSUITABLE if x in lower]
    if blockers:
        return {"eligible":False,"reason":"requires non-patch capability: "+", ".join(blockers)}
    targets=sorted(set(_PATH.findall(raw)))[:20]
    max_chars=int(os.environ.get("ORCH_NATIVE_DISTILLED_CHARS","14000"))
    # Preserve the objective and terminal acceptance criteria; remove repeated
    # orchestration transcripts that caused context overflow and vague output.
    parts=[p.strip() for p in re.split(r"\n{2,}",raw) if p.strip()]
    unique=[]; seen=set()
    for p in parts:
        key=re.sub(r"\s+"," ",p).lower()[:500]
        if key not in seen:seen.add(key);unique.append(p)
    body="\n\n".join(unique)
    if len(body)>max_chars:
        body=body[:max_chars//3]+"\n\n[distilled]\n\n"+body[-(max_chars-max_chars//3):]
    contract=("\n\nNATIVE PATCH CONTRACT:\n- Return only one complete git unified diff."
              "\n- Do not omit diff headers or invent files/symbols."
              "\n- Keep the smallest change satisfying the objective and existing tests.")
    if targets:contract+="\n- Explicit target files: "+", ".join(targets)
    return {"eligible":True,"prompt":body+contract,"targets":targets,
            "original_chars":len(raw),"distilled_chars":len(body+contract)}

