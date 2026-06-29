#!/usr/bin/env python3
"""
recipes.py - reusable SKILL RECIPES. Common capabilities ("add RLS", "add a feature flag",
"add Stripe checkout") are stored as parameterized prompt templates so the swarm assembles
them instead of re-reasoning from scratch. Recipes live in runner/recipes/*.md with a
front-matter-ish header. apply('add-rls', table='ledger') -> a ready task prompt.
"""
import os, re, glob

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recipes")


def list_recipes():
    return [os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(DIR, "*.md"))]


def apply(name, **params):
    path = os.path.join(DIR, name + ".md")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"recipe '{name}' not found; have: {list_recipes()}")
    body = open(path).read()
    # {{param}} substitution
    for k, v in params.items():
        body = body.replace("{{" + k + "}}", str(v))
    # warn on unfilled params
    missing = set(re.findall(r"\{\{(\w+)\}\}", body))
    if missing:
        body += f"\n\n# NOTE: fill these params: {', '.join(missing)}"
    return body


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("recipes:", ", ".join(list_recipes()))
    else:
        kv = dict(p.split("=", 1) for p in sys.argv[2:] if "=" in p)
        print(apply(sys.argv[1], **kv))
