#!/usr/bin/env python3
"""
generate_dashboard.py - Inject live orchestrator metrics into the HTML dashboard.

Reads the dashboard template (metrics_dashboard.html), generates a fresh report
via orchestrator_metrics.generate_report(), replaces the placeholder DATA object,
and writes the final dashboard to ~/.claude-orchestrator/dashboard.html.

Usage:
    python generate_dashboard.py                    # default output path
    python generate_dashboard.py --out /tmp/dash.html  # custom output path
    python generate_dashboard.py --open             # generate and open in browser
"""

import os
import sys
import json
import re
import argparse
import webbrowser

# Ensure runner/ is on the path so orchestrator_metrics can import its deps.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import orchestrator_metrics


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "metrics_dashboard.html",
)

_DEFAULT_OUTPUT = os.path.join(
    os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator")),
    "dashboard.html",
)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def generate_dashboard(template_path: str = _TEMPLATE_PATH,
                       output_path: str = _DEFAULT_OUTPUT) -> str:
    """Generate a dashboard HTML file with live metrics data.

    Args:
        template_path: Path to the HTML template with placeholder DATA.
        output_path:   Where to write the final HTML.

    Returns:
        The output path on success, empty string on failure.
    """
    # 1. Read template
    try:
        with open(template_path, "r", encoding="utf-8") as fh:
            template = fh.read()
    except (FileNotFoundError, PermissionError, OSError) as exc:
        print(f"[generate_dashboard] ERROR: cannot read template: {exc}",
              file=sys.stderr)
        return ""

    # 2. Generate report
    try:
        report = orchestrator_metrics.generate_report()
    except Exception as exc:
        print(f"[generate_dashboard] ERROR: generate_report() failed: {exc}",
              file=sys.stderr)
        return ""

    # 3. Serialize the report as indented JSON for readability
    report_json = json.dumps(report, indent=2, default=str)

    # 4. Replace the DATA block between the marker comments.
    #    Pattern: everything between __DASHBOARD_DATA_START__ and __DASHBOARD_DATA_END__
    pattern = re.compile(
        r"(// __DASHBOARD_DATA_START__\n)"
        r".*?"
        r"(\n// __DASHBOARD_DATA_END__)",
        re.DOTALL,
    )

    replacement = r"\1const DATA = " + report_json + r";\2"

    new_html, count = pattern.subn(replacement, template)
    if count == 0:
        # Fallback: try replacing the entire `const DATA = {...};` block
        fallback_pattern = re.compile(
            r"const DATA\s*=\s*\{.*?\};",
            re.DOTALL,
        )
        new_html, count = fallback_pattern.subn(
            "const DATA = " + report_json + ";",
            template,
            count=1,
        )
        if count == 0:
            print("[generate_dashboard] ERROR: could not find DATA placeholder in template",
                  file=sys.stderr)
            return ""

    # 5. Write output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    try:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(new_html)
    except (OSError, PermissionError) as exc:
        print(f"[generate_dashboard] ERROR: cannot write output: {exc}",
              file=sys.stderr)
        return ""

    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate the orchestrator metrics dashboard with live data."
    )
    parser.add_argument(
        "--out", metavar="FILE", default=_DEFAULT_OUTPUT,
        help=f"Output path (default: {_DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--template", metavar="FILE", default=_TEMPLATE_PATH,
        help=f"Template path (default: {_TEMPLATE_PATH})",
    )
    parser.add_argument(
        "--open", action="store_true",
        help="Open the dashboard in the default browser after generating.",
    )
    args = parser.parse_args()

    path = generate_dashboard(template_path=args.template, output_path=args.out)
    if path:
        print(f"Dashboard written to {path}")
        if args.open:
            webbrowser.open("file://" + os.path.abspath(path))
    else:
        print("Failed to generate dashboard.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
