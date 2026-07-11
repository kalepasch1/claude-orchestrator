"""
pattern_transfer -- transfer proven patterns across projects.

If "add-field-*" diffs work identically in project A and project B (same ORM,
same test framework), patterns compiled from A should apply in B.

Env vars
--------
ORCH_PATTERN_TRANSFER_ENABLED   "true" (default) / "false"
ORCH_TRANSFER_MIN_CONFIDENCE    minimum confidence to transfer (default "0.7")
ORCH_TRANSFER_MIN_APPLICATIONS  minimum successful applications (default "10")
"""

import sys, os, json, time, threading, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log as _log_mod

_log = _log_mod.get("pattern_transfer")
import db

# ---------------------------------------------------------------------------
# env helpers
# ---------------------------------------------------------------------------

_ENABLED = os.environ.get("ORCH_PATTERN_TRANSFER_ENABLED", "true").lower() == "true"
_MIN_CONFIDENCE = float(os.environ.get("ORCH_TRANSFER_MIN_CONFIDENCE", "0.7"))
_MIN_APPLICATIONS = int(os.environ.get("ORCH_TRANSFER_MIN_APPLICATIONS", "10"))

# framework detection: filename pattern -> framework name
_FRAMEWORK_MARKERS = {
    r"conftest\.py|test_.*\.py|pytest\.ini": "pytest",
    r"\.test\.[jt]sx?$|jest\.config": "jest",
    r"_spec\.rb|spec_helper\.rb": "rspec",
    r"_test\.go$": "go-test",
    r"\.test\.ts$|vitest\.config": "vitest",
    r"\.spec\.[jt]sx?$": "jasmine",
    r"phpunit\.xml|Test\.php$": "phpunit",
}

# import-based framework detection: regex on diff content -> framework name
_IMPORT_MARKERS = {
    r"from django": "django",
    r"from flask": "flask",
    r"from fastapi": "fastapi",
    r"from sqlalchemy": "sqlalchemy",
    r"import express": "express",
    r"from react": "react",
    r"import pytest": "pytest",
    r"require\s*\(\s*['\"]rails": "rails",
    r"from typing": "python-typing",
    r"import prisma|from.*prisma": "prisma",
    r"from pydantic": "pydantic",
}

# directory structure markers
_DIR_MARKERS = [
    "src/", "lib/", "app/", "tests/", "test/", "spec/",
    "models/", "views/", "controllers/", "services/",
    "components/", "pages/", "utils/", "helpers/",
    "migrations/", "fixtures/", "schemas/",
]


# ---------------------------------------------------------------------------
# singleton
# ---------------------------------------------------------------------------

class _PatternTransfer:
    def __init__(self):
        self._lock = threading.Lock()
        self._transfers_attempted = 0
        self._transfers_successful = 0
        self._cross_project_savings = 0

    # -----------------------------------------------------------------------
    # public: find_transferable
    # -----------------------------------------------------------------------

    def find_transferable(self, source_project, target_project):
        """Return patterns from *source_project* that may apply to *target_project*."""
        if not _ENABLED:
            return []
        try:
            sim = self.detect_similarity(source_project, target_project)
            if sim.get("similarity", 0) < 0.3:
                _log.debug("projects too dissimilar (%.2f)", sim["similarity"])
                return []

            # fetch high-success patterns from source project
            patterns = self._compiled_patterns_for(source_project)
            if not patterns:
                return []

            results = []
            for p in patterns:
                conf = p.get("success_rate", 0) * sim["similarity"]
                if conf < _MIN_CONFIDENCE:
                    continue
                results.append({
                    "pattern_id": p["pattern_id"],
                    "slug_prefix": p.get("slug_prefix", ""),
                    "confidence": round(conf, 3),
                    "reason": "shared features: %s" % ", ".join(sim.get("shared_features", [])),
                })
            return results
        except Exception:
            _log.exception("find_transferable failed")
            return []

    # -----------------------------------------------------------------------
    # public: transfer_pattern
    # -----------------------------------------------------------------------

    def transfer_pattern(self, pattern_id, source_project, target_project):
        """Copy a pattern from source to target with reduced confidence."""
        if not _ENABLED:
            return {"transferred": False, "new_pattern_id": "", "adjustments": []}
        try:
            with self._lock:
                self._transfers_attempted += 1

            # fetch the source pattern
            rows = db.select("compiled_patterns", {
                "pattern_id": "eq.%s" % pattern_id,
                "project": "eq.%s" % source_project,
                "limit": "1",
            })
            if not rows:
                # fallback: try outcomes-based reconstruction
                rows = self._reconstruct_pattern(pattern_id, source_project)
            if not rows:
                _log.warning("pattern %s not found in project %s", pattern_id, source_project)
                return {"transferred": False, "new_pattern_id": "", "adjustments": []}

            src = rows[0] if isinstance(rows, list) else rows
            adjustments = self._compute_adjustments(src, source_project, target_project)

            new_id = "%s__from__%s" % (pattern_id, source_project)
            original_confidence = src.get("confidence", src.get("success_rate", 0.8))
            new_confidence = round(original_confidence * 0.6, 3)

            new_row = {
                "pattern_id": new_id,
                "project": target_project,
                "slug_prefix": src.get("slug_prefix", ""),
                "confidence": new_confidence,
                "script": src.get("script", ""),
                "files": src.get("files", ""),
                "keywords": src.get("keywords", ""),
                "provenance_project": source_project,
                "provenance_pattern_id": pattern_id,
                "transferred": True,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            for adj in adjustments:
                if adj.get("field") and adj.get("new_value") is not None:
                    new_row[adj["field"]] = adj["new_value"]

            db.upsert("compiled_patterns", new_row)

            with self._lock:
                self._transfers_successful += 1

            _log.info("transferred pattern %s -> %s (conf %.2f)", pattern_id, new_id, new_confidence)
            return {"transferred": True, "new_pattern_id": new_id, "adjustments": adjustments}

        except Exception:
            _log.exception("transfer_pattern failed")
            return {"transferred": False, "new_pattern_id": "", "adjustments": []}

    # -----------------------------------------------------------------------
    # public: auto_transfer_scan
    # -----------------------------------------------------------------------

    def auto_transfer_scan(self):
        """Scan all projects for transferable high-success patterns."""
        if not _ENABLED:
            return {"transfers_found": 0, "transferred": 0}
        try:
            projects = self._all_projects()
            if len(projects) < 2:
                return {"transfers_found": 0, "transferred": 0}

            # find high-success patterns across all projects
            high_success = []
            for proj in projects:
                patterns = self._compiled_patterns_for(proj)
                for p in patterns:
                    apps = p.get("applications", 0)
                    rate = p.get("success_rate", 0)
                    if apps >= _MIN_APPLICATIONS and rate >= 0.9:
                        high_success.append((proj, p))

            transfers_found = 0
            transferred = 0

            for source_proj, pattern in high_success:
                for target_proj in projects:
                    if target_proj == source_proj:
                        continue
                    # skip if already transferred
                    candidate_id = "%s__from__%s" % (pattern["pattern_id"], source_proj)
                    existing = db.select("compiled_patterns", {
                        "pattern_id": "eq.%s" % candidate_id,
                        "project": "eq.%s" % target_proj,
                        "limit": "1",
                    })
                    if existing:
                        continue

                    sim = self.detect_similarity(source_proj, target_proj)
                    if sim.get("similarity", 0) < _MIN_CONFIDENCE:
                        continue

                    transfers_found += 1
                    result = self.transfer_pattern(
                        pattern["pattern_id"], source_proj, target_proj
                    )
                    if result.get("transferred"):
                        transferred += 1

            with self._lock:
                self._cross_project_savings += transferred

            return {"transfers_found": transfers_found, "transferred": transferred}

        except Exception:
            _log.exception("auto_transfer_scan failed")
            return {"transfers_found": 0, "transferred": 0}

    # -----------------------------------------------------------------------
    # public: detect_similarity
    # -----------------------------------------------------------------------

    def detect_similarity(self, project_a_id, project_b_id):
        """Compare two projects on language, directory structure, test framework."""
        try:
            profile_a = self._project_profile(project_a_id)
            profile_b = self._project_profile(project_b_id)

            if not profile_a or not profile_b:
                return {"similarity": 0.0, "shared_features": []}

            shared = []
            scores = []

            # 1. file extension overlap (language)
            exts_a = set(profile_a.get("extensions", []))
            exts_b = set(profile_b.get("extensions", []))
            if exts_a and exts_b:
                ext_overlap = len(exts_a & exts_b) / max(len(exts_a | exts_b), 1)
                scores.append(ext_overlap)
                common_exts = exts_a & exts_b
                if common_exts:
                    shared.append("languages: %s" % ", ".join(sorted(common_exts)[:5]))
            else:
                scores.append(0.0)

            # 2. directory naming patterns
            dirs_a = set(profile_a.get("directories", []))
            dirs_b = set(profile_b.get("directories", []))
            if dirs_a and dirs_b:
                dir_overlap = len(dirs_a & dirs_b) / max(len(dirs_a | dirs_b), 1)
                scores.append(dir_overlap)
                common_dirs = dirs_a & dirs_b
                if common_dirs:
                    shared.append("dirs: %s" % ", ".join(sorted(common_dirs)[:5]))
            else:
                scores.append(0.0)

            # 3. test framework
            fw_a = set(profile_a.get("frameworks", []))
            fw_b = set(profile_b.get("frameworks", []))
            if fw_a and fw_b:
                fw_overlap = len(fw_a & fw_b) / max(len(fw_a | fw_b), 1)
                scores.append(fw_overlap)
                common_fw = fw_a & fw_b
                if common_fw:
                    shared.append("frameworks: %s" % ", ".join(sorted(common_fw)))
            else:
                scores.append(0.0)

            similarity = sum(scores) / max(len(scores), 1)
            return {"similarity": round(similarity, 3), "shared_features": shared}

        except Exception:
            _log.exception("detect_similarity failed")
            return {"similarity": 0.0, "shared_features": []}

    # -----------------------------------------------------------------------
    # public: stats
    # -----------------------------------------------------------------------

    def stats(self):
        with self._lock:
            return {
                "transfers_attempted": self._transfers_attempted,
                "transfers_successful": self._transfers_successful,
                "cross_project_savings": self._cross_project_savings,
            }

    # -----------------------------------------------------------------------
    # internal helpers
    # -----------------------------------------------------------------------

    def _compiled_patterns_for(self, project):
        """Fetch compiled patterns for a project from the DB."""
        try:
            rows = db.select("compiled_patterns", {
                "project": "eq.%s" % project,
                "limit": "200",
            })
            return rows if rows else []
        except Exception:
            _log.debug("compiled_patterns table query failed, trying outcomes")
            return self._patterns_from_outcomes(project)

    def _patterns_from_outcomes(self, project):
        """Reconstruct patterns from the outcomes table when compiled_patterns unavailable."""
        try:
            rows = db.select("outcomes", {
                "project": "eq.%s" % project,
                "state": "eq.DONE",
                "select": "slug,diff,files_changed,integrated",
                "limit": "500",
                "order": "created_at.desc",
            })
            if not rows:
                return []

            # group by slug prefix (first two tokens)
            groups = {}
            for r in rows:
                slug = r.get("slug", "") or ""
                prefix = "-".join(slug.split("-")[:2]) if slug else ""
                if not prefix:
                    continue
                if prefix not in groups:
                    groups[prefix] = {"total": 0, "success": 0, "diffs": [], "files": []}
                groups[prefix]["total"] += 1
                if r.get("integrated"):
                    groups[prefix]["success"] += 1
                if r.get("diff"):
                    groups[prefix]["diffs"].append(r["diff"][:500])
                if r.get("files_changed"):
                    fc = r["files_changed"]
                    if isinstance(fc, str):
                        try:
                            fc = json.loads(fc)
                        except Exception:
                            fc = []
                    if isinstance(fc, list):
                        groups[prefix]["files"].extend(fc)

            patterns = []
            for prefix, g in groups.items():
                if g["total"] < 3:
                    continue
                rate = g["success"] / g["total"]
                patterns.append({
                    "pattern_id": "outcomes__%s__%s" % (project, prefix),
                    "slug_prefix": prefix,
                    "success_rate": round(rate, 3),
                    "applications": g["total"],
                    "files": list(set(g["files"]))[:20],
                    "confidence": round(rate, 3),
                })
            return patterns

        except Exception:
            _log.exception("_patterns_from_outcomes failed")
            return []

    def _reconstruct_pattern(self, pattern_id, project):
        """Try to build a usable pattern dict from outcomes when compiled_patterns misses."""
        try:
            parts = pattern_id.split("__")
            prefix = parts[-1] if len(parts) > 1 else pattern_id
            rows = db.select("outcomes", {
                "project": "eq.%s" % project,
                "slug": "like.%s*" % prefix,
                "state": "eq.DONE",
                "limit": "50",
            })
            if not rows:
                return []
            total = len(rows)
            success = sum(1 for r in rows if r.get("integrated"))
            rate = success / total if total else 0
            return [{
                "pattern_id": pattern_id,
                "slug_prefix": prefix,
                "success_rate": round(rate, 3),
                "applications": total,
                "confidence": round(rate, 3),
                "script": "",
                "files": "",
                "keywords": "",
            }]
        except Exception:
            return []

    def _project_profile(self, project_id):
        """Build a feature profile for a project from its outcomes."""
        try:
            rows = db.select("outcomes", {
                "project": "eq.%s" % project_id,
                "state": "eq.DONE",
                "select": "slug,diff,files_changed",
                "limit": "200",
                "order": "created_at.desc",
            })
            if not rows:
                return {}

            extensions = set()
            directories = set()
            frameworks = set()

            for r in rows:
                # extract file extensions and directories from files_changed
                fc = r.get("files_changed")
                if fc:
                    if isinstance(fc, str):
                        try:
                            fc = json.loads(fc)
                        except Exception:
                            fc = [fc]
                    if isinstance(fc, list):
                        for f in fc:
                            if not isinstance(f, str):
                                continue
                            _, ext = os.path.splitext(f)
                            if ext:
                                extensions.add(ext.lower())
                            # detect directory markers
                            for marker in _DIR_MARKERS:
                                if marker in f:
                                    directories.add(marker)
                            # detect test frameworks from filenames
                            for pat, fw in _FRAMEWORK_MARKERS.items():
                                if re.search(pat, f):
                                    frameworks.add(fw)

                # detect frameworks from diff content (import statements)
                diff = r.get("diff") or ""
                if diff:
                    for pat, fw in _IMPORT_MARKERS.items():
                        if re.search(pat, diff[:2000]):
                            frameworks.add(fw)

            return {
                "extensions": sorted(extensions),
                "directories": sorted(directories),
                "frameworks": sorted(frameworks),
            }

        except Exception:
            _log.exception("_project_profile failed for %s", project_id)
            return {}

    def _all_projects(self):
        """Return distinct project identifiers from outcomes."""
        try:
            rows = db.select("outcomes", {
                "select": "project",
                "state": "eq.DONE",
                "limit": "1000",
            })
            return list({r["project"] for r in rows if r.get("project")})
        except Exception:
            _log.exception("_all_projects failed")
            return []

    def _compute_adjustments(self, source_pattern, source_project, target_project):
        """Determine path/name adjustments needed for the target project."""
        adjustments = []
        try:
            script = source_pattern.get("script", "") or ""
            if source_project in script:
                adjustments.append({
                    "field": "script",
                    "description": "replaced project reference %s -> %s" % (
                        source_project, target_project),
                    "new_value": script.replace(source_project, target_project),
                })
            files_raw = source_pattern.get("files", "")
            if isinstance(files_raw, str) and source_project in files_raw:
                adjustments.append({
                    "field": "files",
                    "description": "replaced project path reference",
                    "new_value": files_raw.replace(source_project, target_project),
                })
        except Exception:
            _log.debug("_compute_adjustments error (non-fatal)")
        return adjustments


# ---------------------------------------------------------------------------
# module-level singleton + delegating functions
# ---------------------------------------------------------------------------

_instance = _PatternTransfer()


def find_transferable(source_project, target_project):
    """-> [{"pattern_id", "slug_prefix", "confidence", "reason"}, ...]"""
    try:
        return _instance.find_transferable(source_project, target_project)
    except Exception:
        _log.exception("find_transferable top-level error")
        return []


def transfer_pattern(pattern_id, source_project, target_project):
    """-> {"transferred": bool, "new_pattern_id": str, "adjustments": list}"""
    try:
        return _instance.transfer_pattern(pattern_id, source_project, target_project)
    except Exception:
        _log.exception("transfer_pattern top-level error")
        return {"transferred": False, "new_pattern_id": "", "adjustments": []}


def auto_transfer_scan():
    """-> {"transfers_found": int, "transferred": int}"""
    try:
        return _instance.auto_transfer_scan()
    except Exception:
        _log.exception("auto_transfer_scan top-level error")
        return {"transfers_found": 0, "transferred": 0}


def detect_similarity(project_a_id, project_b_id):
    """-> {"similarity": float, "shared_features": list}"""
    try:
        return _instance.detect_similarity(project_a_id, project_b_id)
    except Exception:
        _log.exception("detect_similarity top-level error")
        return {"similarity": 0.0, "shared_features": []}


def stats():
    """-> dict with transfers_attempted, transfers_successful, cross_project_savings"""
    try:
        return _instance.stats()
    except Exception:
        return {"transfers_attempted": 0, "transfers_successful": 0, "cross_project_savings": 0}
