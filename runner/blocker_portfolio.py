#!/usr/bin/env python3
"""Portfolio-wide blocker clearing score for task claim order."""
import collections
import datetime


BLOCKER_WORDS = ("qafix-", "buildfix-", "relfix-", "deployfix-", "toolchain-repair-",
                 "conflict", "missing-branch", "release", "staging")


def _age_hours(value):
    try:
        dt = datetime.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc) if dt.tzinfo else datetime.datetime.utcnow()
        return max(0.0, (now - dt).total_seconds() / 3600.0)
    except Exception:
        return 0.0


def scores(tasks):
    dependents = collections.Counter()
    by_slug = {str(t.get("slug") or ""): t for t in tasks or []}
    for task in tasks or []:
        for dep in task.get("deps") or []:
            dependents[str(dep)] += 1
    result = {}
    for task in tasks or []:
        slug = str(task.get("slug") or "")
        blob = " ".join(str(task.get(k) or "").lower() for k in ("slug", "kind", "note"))
        direct = dependents.get(slug, 0)
        transitive = 0
        frontier = [slug]; seen = set()
        while frontier:
            current = frontier.pop()
            for candidate in tasks or []:
                cslug = str(candidate.get("slug") or "")
                if cslug not in seen and current in [str(x) for x in candidate.get("deps") or []]:
                    seen.add(cslug); frontier.append(cslug); transitive += 1
        release = 1 if any(word in blob for word in BLOCKER_WORDS) else 0
        exact = 1 if len(slug.rsplit("-", 1)[-1]) == 12 else 0
        age = min(72.0, _age_hours(task.get("created_at"))) / 72.0
        score = release * 1000 + transitive * 100 + direct * 25 + exact * 10 + age
        result[str(task.get("id") or slug)] = score
    return result


def rank(tasks):
    values = scores(tasks)
    return sorted(tasks or [], key=lambda t: (-values.get(str(t.get("id") or t.get("slug") or ""), 0),
                                               str(t.get("created_at") or "")))

