from __future__ import annotations



import logging
import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from multiagent_testing.adapters.registry import DEFAULT_REGISTRY
from multiagent_testing.confidence import confidence_breakdown, confidence_score
from multiagent_testing.excel_store import ExcelStore
from multiagent_testing.failure_analyzer import categorize_failure
from multiagent_testing.models import AgentState, TestCaseResult
from multiagent_testing.repair import repair_test_code
from multiagent_testing.validators import validate_test_code


logger = logging.getLogger(__name__)


def test_runner_node(state: AgentState) -> AgentState:
    if state.get("skip_runner"):
        _score_skipped_runner_rows(state)
        return state

    repo_path = state["repo_path"]
    adapter = DEFAULT_REGISTRY.detect(repo_path, state.get("adapter_name") or state.get("stack"))
    state["adapter_name"] = adapter.name
    store = ExcelStore(state["excel_path"])
    workbook_rows = store.rows()
    rows = workbook_rows if state.get("rerun_all_tests") else [row for row in workbook_rows if not row.get("status")]

    updates: dict[str, dict] = {}
    try:
        adapter.setup_environment(repo_path)
    except Exception as exc:
        for row in rows:
            updates[str(row["test_id"])] = _error_update(f"Environment setup failed: {exc}")
        store.bulk_update_by_test_id(updates)
        state["failing_count"] = len(rows)
        return state

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        try:
            test_file_path = _materialize_row_test_file(adapter, repo_path, row)
        except Exception as exc:
            updates[str(row["test_id"])] = _error_update(f"Failed preparing test case {row.get('test_id')}: {exc}")
            continue
        grouped[str(test_file_path)].append(row)

    for test_file_path, file_rows in grouped.items():
        file_updates = _run_one_test_file(adapter, repo_path, test_file_path, file_rows, bool(state.get("coverage")))
        updates.update(file_updates)
        store.bulk_update_by_test_id(file_updates)

    _write_execution_reports(Path(state.get("output_dir") or Path(state["excel_path"]).parent), store.rows())
    state["failing_count"] = sum(1 for update in updates.values() if update.get("status") in {"Fail", "Error"})
    return state


def _run_one_test_file(adapter, repo_path: str, test_file_path: str, rows: list[dict], collect_coverage: bool = False) -> dict[str, dict]:
    started = datetime.now(timezone.utc)
    command = adapter.get_test_runner_command(test_file_path)
    cwd = adapter.get_test_cwd(repo_path, test_file_path)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_runner_env(),
            timeout=getattr(adapter, "timeout_seconds", 120),
            check=False,
        )
        raw_output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
        test_results = adapter.parse_test_results(raw_output)
        if not test_results:
            detail = raw_output[-7600:] or "Test file did not produce parseable test-runner JSON output"
            message = f"Command failed or produced no parseable assertion results.\nCWD: {cwd}\nCommand: {' '.join(command)}\n\n{detail}"
            return _file_error_updates(rows, test_file_path, message, started)
        updates = _updates_from_test_results(test_file_path, rows, test_results, raw_output, started)
        if collect_coverage:
            _attach_coverage(adapter, repo_path, test_file_path, rows, updates)
        return updates
    except subprocess.TimeoutExpired as exc:
        return _file_error_updates(rows, test_file_path, f"Timed out running {Path(test_file_path).name}: {exc}", started)
    except Exception as exc:
        return _file_error_updates(rows, test_file_path, f"Failed running {Path(test_file_path).name}: {exc}", started)


def _attach_coverage(adapter, repo_path: str, test_file_path: str, rows: list[dict], updates: dict[str, dict]) -> None:
    command_factory = getattr(adapter, "get_coverage_command", None)
    parser = getattr(adapter, "parse_coverage_percent", None)
    if not callable(command_factory) or not callable(parser):
        return
    command = command_factory(test_file_path)
    cwd = adapter.get_test_cwd(repo_path, test_file_path)
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_runner_env(),
            timeout=getattr(adapter, "timeout_seconds", 120),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _mark_coverage_error(rows, updates, f"Coverage run timed out for {Path(test_file_path).name}: {exc}")
        return
    except Exception as exc:
        _mark_coverage_error(rows, updates, f"Coverage run failed for {Path(test_file_path).name}: {exc}")
        return

    raw_output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    if completed.returncode != 0:
        _mark_coverage_error(rows, updates, f"Coverage command failed.\nCWD: {cwd}\nCommand: {' '.join(command)}\n\n{raw_output[-4000:]}")
        return
    percent = parser(raw_output, cwd, test_file_path)
    if percent is None:
        _mark_coverage_error(rows, updates, f"Coverage command completed but no coverage percent was found.\n\n{raw_output[-4000:]}")
        return
    for row in rows:
        update = updates.get(str(row["test_id"]))
        if update is not None:
            update["coverage_percent"] = percent
            _finish_result_metadata(update)


def _mark_coverage_error(rows: list[dict], updates: dict[str, dict], message: str) -> None:
    for row in rows:
        update = updates.get(str(row["test_id"]))
        if update is None:
            continue
        update["coverage_percent"] = ""
        original_status = update.get("status")
        if original_status == "Pass":
            update["status"] = "Error"
            update["score"] = 0
            update["actual_output"] = message[:8000]
            update["failure_category"] = "Coverage"
        else:
            update["actual_output"] = f"{update.get('actual_output') or ''}\n\nCoverage:\n{message}"[:8000]
            update["failure_category"] = update.get("failure_category") or "Coverage"
        _finish_result_metadata(update)


def _updates_from_test_results(
    test_file_path: str,
    rows: list[dict],
    test_results: list[TestCaseResult],
    raw_output: str,
    started: datetime,
) -> dict[str, dict]:
    matched = _match_results_by_test_id(test_results)
    updates = {}
    if not matched and len(rows) == 1:
        matched[str(rows[0]["test_id"])] = test_results
    elif not matched and len(rows) == len(test_results):
        for row, result in zip(rows, test_results, strict=False):
            matched[str(row["test_id"])].append(result)

    for row in rows:
        test_id = str(row["test_id"])
        results = matched.get(test_id, [])
        if not results:
            updates[test_id] = _error_update(
                f"Test ID [{test_id}] did not appear in test-runner results for {Path(test_file_path).name}. "
                f"The file may have a syntax/import error.\n\n{raw_output[-4000:]}",
                started,
            )
            updates[test_id]["test_file_path"] = test_file_path
            updates[test_id]["test_code"] = row.get("test_code")
            _copy_pre_run_metadata(row, updates[test_id])
            _finish_result_metadata(updates[test_id])
            continue
        updates[test_id] = _aggregate_results(test_file_path, results, started)
        updates[test_id]["test_code"] = row.get("test_code")
        _copy_pre_run_metadata(row, updates[test_id])
        _finish_result_metadata(updates[test_id])
    return updates


def _match_results_by_test_id(test_results: list[TestCaseResult]) -> dict[str, list[TestCaseResult]]:
    matched: dict[str, list[TestCaseResult]] = defaultdict(list)
    id_pattern = re.compile(r"\[(TC-\d+)\]")
    for result in test_results:
        match = id_pattern.search(result.test_title)
        if match:
            matched[match.group(1)].append(result)
    return matched


def _aggregate_results(test_file_path: str, results: list[TestCaseResult], started: datetime) -> dict:
    failed = [result for result in results if result.status in {"Fail", "Error"}]
    skipped = [result for result in results if result.status == "Skipped"]
    passed = [result for result in results if result.status == "Pass"]
    total = len(results)
    duration_ms = sum(result.duration_ms for result in results)

    if failed:
        status = "Fail" if any(result.status == "Fail" for result in failed) else "Error"
        score = round((len(passed) / total) * 100, 2) if total else 0
        output = "\n\n".join(result.error_message or result.test_title for result in failed)
    elif skipped and not passed:
        status = "Skipped"
        score = 0
        output = "All matching assertions were skipped."
    else:
        status = "Pass"
        score = 100
        output = "OK"

    return {
        "test_file_path": test_file_path,
        "status": status,
        "score": score,
        "actual_output": output[:8000],
        "execution_time_ms": duration_ms,
        "run_timestamp": started.isoformat(),
    }


def _materialize_row_test_file(adapter, repo_path: str, row: dict) -> Path:
    test_code = str(row.get("test_code") or "").strip()
    if not test_code:
        raise ValueError("Excel row has no test_code to execute")

    test_file_path = _runtime_test_path(repo_path, row)
    test_file_path.parent.mkdir(parents=True, exist_ok=True)
    test_code = _stamp_test_id_in_titles(test_code, str(row.get("test_id") or "TC-0000"))
    prepare_test_code = getattr(adapter, "prepare_test_code", None)
    if callable(prepare_test_code):
        test_code = prepare_test_code(test_code, str(test_file_path))
    framework = adapter.get_test_framework()
    issues = validate_test_code(test_code, str(test_file_path), framework)
    repair = repair_test_code(test_code, issues, framework)
    test_code = repair.test_code
    final_issues = validate_test_code(test_code, str(test_file_path), framework)
    row["validation_status"] = _validation_status(final_issues)
    row["validation_errors"] = "; ".join(f"{issue.code}: {issue.message}" for issue in final_issues)
    row["repairs_applied"] = "; ".join(repair.repairs)
    row["test_code"] = test_code
    test_file_path.write_text(test_code, encoding="utf-8")
    return test_file_path


def _validation_status(issues) -> str:
    if not issues:
        return "Pass"
    if any(issue.severity == "error" for issue in issues):
        return "Error"
    return "Warning"


def _runtime_test_path(repo_path: str, row: dict) -> Path:
    root = Path(repo_path).resolve()
    target_file = _normalize_target_file(str(row.get("target_file") or "generated_target"))
    target_path = _resolve_target_path(root, target_file)
    test_id = _safe_filename_part(str(row.get("test_id") or "TC"))
    target_name = _safe_filename_part(str(row.get("target_function_or_route") or target_path.stem))
    test_suffix = _test_suffix_for_target(target_path)
    return target_path.parent / f"{target_path.stem}.generated.{test_id}_{target_name}{test_suffix}"


def _resolve_target_path(root: Path, target_file: str) -> Path:
    candidate = Path(target_file)
    if candidate.is_absolute() and not _is_ignored_source_path(candidate, root):
        _log_resolved_target(target_file, candidate, "absolute candidate", [candidate])
        return candidate

    normalized = _normalize_target_file(candidate.as_posix())
    considered: list[Path] = []
    if normalized.startswith("backend/") or normalized.startswith("frontend/"):
        direct = root / normalized
        considered.append(direct)
        if direct.exists() and not _is_ignored_source_path(direct, root):
            _log_resolved_target(target_file, direct, "direct prefixed path", considered)
            return direct
    if normalized.startswith("backend") or normalized.startswith("frontend"):
        direct = root / normalized
        considered.append(direct)
        if direct.exists() and not _is_ignored_source_path(direct, root):
            _log_resolved_target(target_file, direct, "direct loose-prefixed path", considered)
            return direct

    for prefix in ("backend/", "frontend/"):
        guessed = root / prefix / normalized
        considered.append(guessed)
        if guessed.exists() and not _is_ignored_source_path(guessed, root):
            _log_resolved_target(target_file, guessed, f"{prefix.rstrip('/')} prefix guess", considered)
            return guessed

    if normalized.startswith("controller") or normalized.endswith("controller") or "controller" in normalized:
        for guessed in [root / "backend" / "controllers", root / "backend", root / "frontend" / "src", root / "frontend"]:
            considered.append(guessed)
            if guessed.exists():
                direct = _find_in_directory(guessed, normalized)
                if direct is not None:
                    _log_resolved_target(target_file, direct, "controller directory scan", considered)
                    return direct

    if normalized.startswith("backend") and "controllers" in normalized.lower():
        controller_name = re.sub(r"^backend", "", normalized).replace("controllers", "")
        controller_name = re.sub(r"[^a-zA-Z0-9]+", "", controller_name)
        if controller_name:
            guessed = root / "backend" / "controllers" / f"{controller_name}.js"
            considered.append(guessed)
            if guessed.exists() and not _is_ignored_source_path(guessed, root):
                _log_resolved_target(target_file, guessed, "inferred controller file", considered)
                return guessed
            for path in sorted((root / "backend" / "controllers").glob("*.js")):
                considered.append(path)
                lower_name = path.name.lower()
                if "generated" in lower_name or lower_name.endswith((".test.js", ".spec.js")):
                    continue
                if "controller" in path.stem.lower() or controller_name.lower() in path.stem.lower():
                    _log_resolved_target(target_file, path, "controller glob match", considered)
                    return path

    path_variants = _guess_path_variants(normalized)
    for path_variant in path_variants:
        guessed = root / path_variant
        considered.append(guessed)
        if guessed.exists() and not _is_ignored_source_path(guessed, root):
            _log_resolved_target(target_file, guessed, "path variant", considered)
            return guessed
        if guessed.parent.exists():
            direct = _find_in_directory(guessed.parent, guessed.name)
            if direct is not None:
                _log_resolved_target(target_file, direct, "path variant directory scan", considered)
                return direct

    best_match = _best_target_match(root, normalized)
    if best_match is not None:
        _log_resolved_target(target_file, best_match, "best target match", considered)
        return best_match

    if normalized.startswith("backend") and "controllers" in normalized.lower():
        fallback = root / "backend" / "controllers"
        _log_resolved_target(target_file, fallback, "controller directory fallback", considered + [fallback])
        return fallback
    if normalized.startswith("frontend") and ("src" in normalized.lower() or "component" in normalized.lower()):
        fallback = root / "frontend" / "src"
        _log_resolved_target(target_file, fallback, "frontend source directory fallback", considered + [fallback])
        return fallback
    fallback = root / normalized
    _log_resolved_target(target_file, fallback, "fallback normalized path", considered + [fallback])
    return fallback


def _log_resolved_target(target_file: str, resolved_path: Path, branch: str, candidates: list[Path] | None = None) -> None:
    candidate_text = ", ".join(str(path) for path in candidates or [])
    logger.debug("Resolved target_file='%s' -> '%s' via %s; candidates=[%s]", target_file, resolved_path, branch, candidate_text)


def _guess_source_candidates(root: Path, target_file: str) -> list[Path]:
    candidates: list[Path] = []
    cleaned = _normalize_target_file(target_file)
    lowered = cleaned.lower()
    stem = Path(cleaned).stem.lower()

    if "backend" in lowered or lowered.startswith("controllers") or lowered.startswith("controller"):
        controller_dir = root / "backend" / "controllers"
        candidates.append(controller_dir)
        cleaned_name = _infer_source_name(cleaned)
        if cleaned_name:
            candidates.append(controller_dir / f"{cleaned_name}.js")
            candidates.append(controller_dir / f"{cleaned_name}.jsx")
            candidates.append(controller_dir / f"{cleaned_name}.ts")
            candidates.append(controller_dir / f"{cleaned_name}.tsx")

    if "route" in lowered or "routes" in lowered:
        routes_dir = root / "backend" / "routes"
        candidates.append(routes_dir)
        cleaned_name = _infer_source_name(cleaned)
        if cleaned_name:
            candidates.append(routes_dir / f"{cleaned_name}.js")

    if "model" in lowered or "models" in lowered:
        models_dir = root / "backend" / "models"
        candidates.append(models_dir)
        cleaned_name = _infer_source_name(cleaned)
        if cleaned_name:
            candidates.append(models_dir / f"{cleaned_name}.js")

    if "frontend" in lowered or "src" in lowered or "api" in lowered or "app" in lowered:
        src_dir = root / "frontend" / "src"
        candidates.append(src_dir)
        cleaned_name = _infer_source_name(cleaned)
        if cleaned_name:
            candidates.append(src_dir / f"{cleaned_name}.js")
            candidates.append(src_dir / f"{cleaned_name}.jsx")
            candidates.append(src_dir / f"{cleaned_name}.ts")
            candidates.append(src_dir / f"{cleaned_name}.tsx")

    if stem and stem not in {"backend", "frontend", "src", "app"}:
        for prefix in ("backend", "frontend"):
            candidates.append(root / prefix / stem)

    return list(dict.fromkeys(candidates))


def _infer_source_name(target_file: str) -> str:
    stem = Path(target_file).stem
    cleaned = re.sub(r"(?i)(backend|frontend|controllers?|routes?|models?|src|api|app|test|spec|generated|js|jsx|ts|tsx|mjs|cjs)", "", stem)
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "", cleaned)
    return cleaned or stem


def _guess_path_variants(target_file: str) -> list[str]:
    variants: list[str] = []
    cleaned = _normalize_target_file(target_file)
    if cleaned.startswith("backend") or cleaned.startswith("frontend"):
        variants.append(cleaned)
    lowered = cleaned.lower()
    for prefix in ("backend/", "frontend/"):
        if lowered.startswith(prefix):
            variants.append(cleaned)
            break
    if "controllers" in lowered or "controller" in lowered:
        variants.append(f"backend/controllers/{Path(cleaned).name}")
        variants.append(f"backend/controllers/{Path(cleaned).stem}.js")
    if "routes" in lowered:
        variants.append(f"backend/routes/{Path(cleaned).name}")
    if "models" in lowered:
        variants.append(f"backend/models/{Path(cleaned).name}")
    if "src" in lowered or "api" in lowered:
        variants.append(f"frontend/src/{Path(cleaned).name}")
    return list(dict.fromkeys(variants))


def _find_in_directory(directory: Path, target_file: str) -> Path | None:
    name = Path(target_file).name.lower()
    stem = Path(name).stem.lower()
    best_path: Path | None = None
    best_score = 0.0
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel_parts = path.relative_to(directory).parts
        except ValueError:
            continue
        lower_parts = {part.lower() for part in rel_parts}
        if lower_parts & {"node_modules", ".git", "dist", "build", "coverage", "generated_tests"}:
            continue
        lower_name = path.name.lower()
        path_stem = path.stem.lower()
        if any(token in lower_name for token in (".test.", ".spec.", ".generated.", "generated")):
            continue
        if lower_name == name or path_stem == stem or stem in path_stem or path_stem in stem:
            return path
        score = SequenceMatcher(None, stem, path_stem).ratio()
        if "controller" in stem and "controller" in path_stem:
            score = max(score, 0.8)
        if "api" in stem and "api" in path_stem:
            score = max(score, 0.8)
        if score > best_score and score >= 0.5:
            best_score = score
            best_path = path
    return best_path


def _best_target_match(root: Path, target_file: str) -> Path | None:
    raw = target_file.replace("\\", "/").lstrip("./")
    name = Path(raw).name
    stem = Path(name).stem.lower()
    suffix = Path(name).suffix.lower()
    tokens = _tokenize(raw)
    if not tokens:
        return None

    best_path: Path | None = None
    best_score = -1

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            continue
        lower_parts = {part.lower() for part in rel_parts}
        if lower_parts & {"node_modules", ".git", "dist", "build", "coverage", "generated_tests"}:
            continue
        lower_name = path.name.lower()
        if (
            ".generated." in lower_name
            or ".test." in lower_name
            or ".spec." in lower_name
            or lower_name.endswith((".test.js", ".test.jsx", ".test.ts", ".test.tsx", ".spec.js", ".spec.jsx", ".spec.ts", ".spec.tsx"))
        ):
            continue

        score = 0
        path_name = lower_name
        path_stem = path.stem.lower()
        path_tokens = _tokenize(path.as_posix())
        rel_text = " ".join(rel_parts).lower()
        rel_tokens = _tokenize(rel_text)

        if path_name == name.lower():
            score = 100
        elif path_stem == stem:
            score = 90
        elif suffix and path.suffix.lower() == suffix and path_stem.replace("_", "") == stem.replace("_", ""):
            score = 85
        else:
            overlap = len(set(tokens) & set(path_tokens))
            if overlap:
                score = 20 + overlap * 10
                if any(part in {"backend", "frontend"} for part in rel_parts):
                    score += 5
                if overlap >= len(tokens) - 1:
                    score += 20
                if stem in path_stem or path_stem in stem:
                    score += 15
                if len(rel_tokens & tokens) >= 1:
                    score += 10

        if score > best_score and (score >= 30 or path_name == name.lower() or path_stem == stem):
            best_score = score
            best_path = path

    return best_path


def _tokenize(value: str) -> set[str]:
    text = value.replace("\\", "/").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = {token for token in text.split() if token not in {"js", "jsx", "ts", "tsx", "mjs", "cjs"}}
    return tokens


def _runner_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "CI": "1",
            "NPM_CONFIG_YES": "true",
            "npm_config_yes": "true",
            "NO_COLOR": "1",
        }
    )
    return env


def _normalize_target_file(value: str) -> str:
    cleaned = value.replace("\\", "/")
    cleaned = re.sub(r"[\x00-\x1f]+", "/", cleaned)
    cleaned = re.sub(r"/+", "/", cleaned).lstrip("./")
    cleaned = _strip_to_stack_root(cleaned)
    cleaned = re.sub(r"(?i)^backend/?controllers?", "backend/controllers", cleaned)
    cleaned = re.sub(r"(?i)^backend/?routes?", "backend/routes", cleaned)
    cleaned = re.sub(r"(?i)^backend/?models?", "backend/models", cleaned)
    cleaned = re.sub(r"(?i)^frontend/?src", "frontend/src", cleaned)
    return cleaned or "generated_target"


def _strip_to_stack_root(value: str) -> str:
    lowered = value.lower()
    for marker in ("/backend/", "/frontend/"):
        index = lowered.find(marker)
        if index >= 0:
            return value[index + 1 :]
    return value


def _test_suffix_for_target(target_path: Path) -> str:
    suffix = target_path.suffix.lower()
    if suffix == ".tsx":
        return ".test.tsx"
    if suffix == ".jsx":
        return ".test.jsx"
    if suffix == ".ts":
        return ".test.ts"
    return ".test.js"


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
        return True
    except ValueError:
        return False


def _is_ignored_source_path(path: Path, root: Path) -> bool:
    try:
        rel_parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        rel_parts = path.parts
    lower_parts = {part.lower() for part in rel_parts}
    if lower_parts & {"node_modules", ".git", "dist", "build", "coverage", "generated_tests"}:
        return True
    lower_name = path.name.lower()
    return ".generated." in lower_name or ".test." in lower_name or ".spec." in lower_name


def _safe_filename_part(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return cleaned.strip("._")[:100] or "test"


def _has_control_chars(value: str) -> bool:
    return any(ord(char) < 32 for char in value)


def _stamp_test_id_in_titles(test_code: str, test_id: str) -> str:
    pattern = re.compile(r"\b(it|test)(\.(?:only|skip|todo|concurrent))?\s*\(\s*(['\"`])(?!\[TC-\d+\])")

    def add_id(match: re.Match) -> str:
        variant = match.group(2) or ""
        quote = match.group(3)
        return f"{match.group(1)}{variant}({quote}[{test_id}] "

    stamped, count = pattern.subn(add_id, test_code)
    return stamped if count else test_code


def _file_error_updates(rows: list[dict], test_file_path: str, message: str, started: datetime) -> dict[str, dict]:
    updates = {}
    for row in rows:
        update = _error_update(message, started)
        update["test_file_path"] = test_file_path
        update["test_code"] = row.get("test_code")
        _copy_pre_run_metadata(row, update)
        _finish_result_metadata(update)
        updates[str(row["test_id"])] = update
    return updates


def _error_update(message: str, started: datetime | None = None) -> dict:
    update = {
        "status": "Error",
        "score": 0,
        "actual_output": message,
        "execution_time_ms": 0,
        "run_timestamp": (started or datetime.now(timezone.utc)).isoformat(),
    }
    _finish_result_metadata(update)
    return update


def _copy_pre_run_metadata(row: dict, update: dict) -> None:
    for column in ("validation_status", "validation_errors", "repairs_applied", "coverage_percent"):
        if row.get(column) is not None:
            update[column] = row.get(column)


def _finish_result_metadata(update: dict) -> None:
    if not update.get("failure_category"):
        update["failure_category"] = "" if update.get("status") == "Pass" else categorize_failure(str(update.get("actual_output") or ""))
    confidence = confidence_breakdown(update)
    update["confidence_score"] = confidence.score
    update["confidence_details"] = confidence.details


def _score_skipped_runner_rows(state: AgentState) -> None:
    excel_path = state.get("excel_path")
    if not excel_path:
        return
    store = ExcelStore(excel_path)
    updates = {}
    for row in store.rows():
        if not row.get("confidence_score"):
            row_update = {
                "validation_status": row.get("validation_status") or "Not Run",
                "confidence_score": confidence_score(row),
                "confidence_details": confidence_breakdown(row).details,
            }
            updates[str(row["test_id"])] = row_update
    store.bulk_update_by_test_id(updates)
    _write_execution_reports(Path(state.get("output_dir") or Path(excel_path).parent), store.rows())


def _write_execution_reports(output_dir: Path, rows: list[dict]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_validation_report(output_dir, rows)
    _write_repair_report(output_dir, rows)
    _write_failure_report(output_dir, rows)
    _write_confidence_report(output_dir, rows)


def _write_validation_report(output_dir: Path, rows: list[dict]) -> None:
    lines = ["# Validation and Repair Report", ""]
    relevant = [row for row in rows if row.get("validation_status") or row.get("repairs_applied")]
    if not relevant:
        lines.append("No generated tests have been validated yet.")
    for row in relevant:
        lines.extend(
            [
                f"## {row.get('test_id')} - {row.get('target_file')}",
                "",
                f"- Unit: {row.get('target_function_or_route')}",
                f"- Validation: {row.get('validation_status') or 'Not Run'}",
                f"- Repairs: {row.get('repairs_applied') or 'None'}",
                f"- Validation errors: {row.get('validation_errors') or 'None'}",
                f"- Coverage percent: {row.get('coverage_percent') if row.get('coverage_percent') not in (None, '') else 'Not collected'}",
                f"- Confidence score: {row.get('confidence_score') or ''}",
                f"- Confidence details: {row.get('confidence_details') or 'Not scored'}",
                "",
            ]
        )
    (output_dir / "validation_report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_repair_report(output_dir: Path, rows: list[dict]) -> None:
    lines = ["# Repair Report", ""]
    repaired = [row for row in rows if row.get("repairs_applied")]
    if not repaired:
        lines.append("No deterministic repairs were applied.")
    for row in repaired:
        lines.extend(
            [
                f"## {row.get('test_id')} - {row.get('target_file')}",
                "",
                f"- Unit: {row.get('target_function_or_route')}",
                f"- Repairs: {row.get('repairs_applied')}",
                f"- Validation after repair: {row.get('validation_status') or 'Not Run'}",
                f"- Remaining validation errors: {row.get('validation_errors') or 'None'}",
                "",
            ]
        )
    (output_dir / "repair_report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_failure_report(output_dir: Path, rows: list[dict]) -> None:
    lines = ["# Failure Report", ""]
    failing = [row for row in rows if row.get("status") in {"Fail", "Error"}]
    if not failing:
        lines.append("No failing generated tests were recorded.")
    for row in failing:
        lines.extend(
            [
                f"## {row.get('test_id')} - {row.get('target_file')}",
                "",
                f"- Unit: {row.get('target_function_or_route')}",
                f"- Status: {row.get('status')}",
                f"- Score: {row.get('score')}",
                f"- Failure category: {row.get('failure_category') or 'Unknown'}",
                f"- Coverage percent: {row.get('coverage_percent') if row.get('coverage_percent') not in (None, '') else 'Not collected'}",
                f"- Confidence score: {row.get('confidence_score') or ''}",
                f"- Confidence details: {row.get('confidence_details') or 'Not scored'}",
                "",
                "Output:",
                "",
                "```text",
                str(row.get("actual_output") or "")[:4000],
                "```",
                "",
            ]
        )
    (output_dir / "failure_report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_confidence_report(output_dir: Path, rows: list[dict]) -> None:
    lines = ["# Confidence Report", ""]
    scored = [row for row in rows if row.get("confidence_score") not in (None, "")]
    if not scored:
        lines.append("No confidence scores have been calculated yet.")
    else:
        scores = [_to_float(row.get("confidence_score")) for row in scored]
        scores = [score for score in scores if score is not None]
        if scores:
            lines.extend(
                [
                    f"- Tests scored: {len(scored)}",
                    f"- Average confidence: {round(sum(scores) / len(scores), 2)}",
                    f"- High confidence: {sum(1 for score in scores if score >= 80)}",
                    f"- Medium confidence: {sum(1 for score in scores if 50 <= score < 80)}",
                    f"- Low confidence: {sum(1 for score in scores if score < 50)}",
                    "",
                ]
            )
    for row in sorted(scored, key=lambda item: _to_float(item.get("confidence_score")) or -1):
        lines.extend(
            [
                f"## {row.get('test_id')} - {row.get('target_file')}",
                "",
                f"- Unit: {row.get('target_function_or_route')}",
                f"- Status: {row.get('status') or 'Not Run'}",
                f"- Confidence score: {row.get('confidence_score')}",
                f"- Details: {row.get('confidence_details') or 'Not scored'}",
                "",
            ]
        )
    (output_dir / "confidence_report.md").write_text("\n".join(lines), encoding="utf-8")


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
