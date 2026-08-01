from __future__ import annotations

import logging
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from multiagent_testing.adapters.registry import DEFAULT_REGISTRY
from multiagent_testing.chunking import build_chunk_prompt_context, group_units_for_llm
from multiagent_testing.excel_store import ExcelStore
from multiagent_testing.groq_client import GroqStructuredClient
from multiagent_testing.models import AgentState, GeneratedTestBatch, GeneratedTestCase
from multiagent_testing.repo_loader import materialize_repo


logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You generate runnable JavaScript tests for MERN code.
Return only structured data matching the requested schema.
Use Supertest for Express routes, React Testing Library for React components, and Jest for functions/models.
For Vite/ES module frontend code, prefer Vitest-compatible APIs such as vi.fn and vi.mock over jest.fn and jest.mock.
Generate isolated unit tests, not end-to-end tests. Read the provided source and dependency context, then mock or stub every external side effect: database calls, Mongoose models, axios/fetch/network calls, filesystem access, timers, process.exit, environment-dependent services, auth middleware, and third-party SDKs. Assertions must exercise the target unit's behavior without requiring live services.
For backend controller and route-handler tests that touch Mongoose models, mock model methods such as find, findById, create, findByIdAndUpdate, findByIdAndDelete, findOne, save, deleteOne, and remove with jest.mock()/vi.mock() or spies. Do not write Supertest tests that call a real Express app backed by a real MongoDB connection unless the test itself explicitly spins up and tears down a test database.
For every backend controller OR route test file that touches a Mongoose model, the first executable lines must mock the model module before requiring controllers, routes, or apps. Use the correct relative path from the generated test file, for example:
jest.mock('../models/Book', () => ({
  find: jest.fn(),
  findById: jest.fn(),
  create: jest.fn(),
  findByIdAndUpdate: jest.fn(),
  findByIdAndDelete: jest.fn(),
}));
const Book = require('../models/Book');
Only after that require the controller or route module. Do not write Book.findById.mockResolvedValue(...) unless Book came from a prior jest.mock('../models/Book')/require('../models/Book') setup in the same file.
For Express tests, distinguish controllers from routers. A controller is a plain object of handler functions and must not be passed directly to app.use(). A router is created by express.Router() and is intended for app.use(). Correct route-level setup example:
const request = require('supertest');
const express = require('express');
const bookRoutes = require('../routes/bookRoutes');
const app = express();
app.use(express.json());
app.use('/api/books', bookRoutes);
Do NOT mount the controller directly with app.use('/api/books', bookController).
For frontend API helper modules, always mock axios explicitly with vi.mock('axios', ...) in every frontend API-helper test. Never rely on implicit mocks, auto-mocks, or real network calls, even if the test framework sometimes auto-mocks in other cases. Target the real exported helpers from the source file instead of calling live endpoints.
Use the exact UI text, placeholders, labels, and exported names from the source code.
When writing test titles or any string literals, use double quotes for the outer string if the content contains an apostrophe/single quote, or escape the inner quote. Broken: it('should set default genre to 'Uncategorized'', ...). Correct: it("should set default genre to 'Uncategorized'", ...).
Do not test private or non-exported functions when a public export exists.
Example: if a React component defines an internal function like handleDelete inside the component body and does not export it, do NOT write import { handleDelete } from './Component'; instead test the exported component's behavior by rendering it and triggering the user action, such as a button click with fireEvent/userEvent, or skip that unit entirely.
Do not invent mock files or fake modules; use inline fixtures and local mocks when needed.
Do not invent Excel columns. Every test_code value must be a full runnable test file."""


def test_generator_node(state: AgentState) -> AgentState:
    original_repo = state.get("original_repo") or state.get("repo_path")
    repo_path, temp_dir = materialize_repo(state["repo_path"])
    state["repo_path"] = repo_path
    state["original_repo"] = original_repo or repo_path
    if temp_dir:
        state["temp_dir"] = temp_dir
    output_dir = Path(state.get("output_dir") or "runs").resolve()
    excel_path = Path(state.get("excel_path") or output_dir / "test_cases.xlsx")
    output_dir.mkdir(parents=True, exist_ok=True)

    adapter = DEFAULT_REGISTRY.detect(repo_path, state.get("stack"))
    units = adapter.discover_units(repo_path)
    repository_graph = _load_repository_graph(state)
    graph_units = _graph_units_by_target(repository_graph)
    store = ExcelStore(excel_path)
    store.ensure_workbook()
    errors = list(state.get("errors", []))
    if not units:
        message = f"Agent 1 discovered 0 testable code units in {repo_path} with adapter '{adapter.name}'."
        logger.warning(message)
        errors.append(message)

    test_number = store.next_test_number()
    rows: list[dict] = []
    llm = GroqStructuredClient(model=state.get("agent1_model", "llama-3.1-8b-instant"))
    max_input_tokens = int(state.get("max_input_tokens") or 2200)
    chunks = group_units_for_llm(units, repo_path, max_input_tokens=max_input_tokens)
    empty_batch_count = 0

    for chunk in chunks:
        context = build_chunk_prompt_context(chunk, repo_path)
        context = _append_repository_graph_context(context, chunk, graph_units)
        batch = _invoke_generation_batch(llm, context, adapter.get_test_framework())
        if not batch.tests:
            empty_batch_count += 1
            chunk_units = ", ".join(f"{unit.relative_path}:{unit.name}" for unit in chunk[:5])
            message = f"Agent 1 got 0 usable tests for chunk containing: {chunk_units}"
            logger.warning(message)
            errors.append(message)
            continue
        for generated in batch.tests:
            _fill_missing_case_fields(generated, chunk, repo_path)
            graph_metadata = _metadata_for_generated_case(generated, graph_units)
            row, test_number = _materialize_test_case(generated, repo_path, test_number, adapter, graph_metadata)
            rows.append(row)

    if units and not rows:
        message = (
            f"Agent 1 discovered {len(units)} code unit(s) but generated 0 usable test row(s). "
            "Groq likely returned empty/null test_code values for every chunk."
        )
        logger.warning(message)
        errors.append(message)

    if state.get("reuse_existing_tests"):
        store.upsert_rows(rows, ["unit_id", "scenario_name"])
    else:
        store.append_rows(rows)
    state.update(
        {
            "repo_path": repo_path,
            "original_repo": state.get("original_repo", repo_path),
            "excel_path": str(excel_path),
            "output_dir": str(output_dir),
            "adapter_name": adapter.name,
            "errors": errors,
            "discovered_unit_count": len(units),
            "generation_chunk_count": len(chunks),
            "generated_test_count": len(rows),
            "empty_generation_batch_count": empty_batch_count,
        }
    )
    return state


def _invoke_generation_batch(llm: GroqStructuredClient, context: str, framework: str) -> GeneratedTestBatch:
    user_prompt = _build_user_prompt(context, framework)
    batch = llm.invoke(GeneratedTestBatch, SYSTEM_PROMPT, user_prompt)
    if batch.tests:
        return batch

    retry_prompt = (
        user_prompt
        + "\n\nPrevious response contained no usable test cases. "
        "Return at least one object in tests with a non-empty test_code string containing a full runnable test file."
    )
    return llm.invoke(GeneratedTestBatch, SYSTEM_PROMPT, retry_prompt)


def _build_user_prompt(context: str, framework: str) -> str:
    return f"""Generate high-value test cases for these code units.

Framework: {framework}

Rules:
- Use the exact target_file and unit names from the context.
- Include needed mocks/imports/setup in each test_code.
- Isolate each test file like a unit test: mock/stub dependencies and reset mocks/state in beforeEach/afterEach.
- Do not call live databases, live HTTP endpoints, real auth services, or real filesystem/process side effects.
- Derive expected inputs, outputs, labels, route paths, model fields, and exported names from the provided source context.
- Prefer one focused test file per generated case.
- For ambiguous paths, use relative imports from the generated test file to the target source file.
- Prioritize route handlers and critical branching logic as High.

Context:
{context}
"""


def _materialize_test_case(
    test_case: GeneratedTestCase,
    repo_path: str,
    test_number: int,
    adapter: Any | None = None,
    graph_metadata: dict[str, Any] | None = None,
) -> tuple[dict, int]:
    test_id = f"TC-{test_number:04d}"
    normalized_target = _normalize_repo_relative_path(test_case.target_file or "unknown_target")
    safe_name = _safe_filename_part(test_case.target_function_or_route or "test")
    target_path = _resolve_target_path(repo_path, normalized_target)
    test_dir = target_path.parent if target_path.parent != Path(".") else Path(repo_path)
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / f"{target_path.stem}.generated.{test_id}_{safe_name}.test.js"
    stamped_test_code = _stamp_test_id_in_titles(test_case.test_code, test_id)
    prepare_test_code = getattr(adapter, "prepare_test_code", None)
    if callable(prepare_test_code):
        stamped_test_code = prepare_test_code(stamped_test_code, str(test_file))
    test_file.write_text(stamped_test_code, encoding="utf-8")
    row = {
        "test_id": test_id,
        "unit_type": test_case.unit_type,
        "target_file": normalized_target,
        "target_function_or_route": test_case.target_function_or_route,
        "test_description": test_case.test_description,
        "test_code": stamped_test_code,
        "test_file_path": str(test_file),
        "priority": test_case.priority,
        "unit_id": (graph_metadata or {}).get("unit_id", ""),
        "scenario_name": test_case.test_description,
        "mock_plan": json.dumps((graph_metadata or {}).get("mock_plan", {}), ensure_ascii=True),
        "validation_status": "Not Run",
        "validation_errors": "",
        "repairs_applied": "",
        "failure_category": "",
        "coverage_percent": "",
        "confidence_score": "",
    }
    return row, test_number + 1


def _load_repository_graph(state: AgentState) -> dict[str, Any]:
    graph = state.get("repository_graph")
    if isinstance(graph, dict):
        return graph
    graph_path = state.get("repository_graph_path")
    if graph_path and Path(str(graph_path)).exists():
        try:
            return json.loads(Path(str(graph_path)).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _graph_units_by_target(repository_graph: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    graph_units: dict[tuple[str, str], dict[str, Any]] = {}
    for unit in repository_graph.get("units", []) if isinstance(repository_graph, dict) else []:
        if not isinstance(unit, dict):
            continue
        rel = _normalize_repo_relative_path(str(unit.get("relative_path") or ""))
        name = str(unit.get("name") or "")
        graph_units[(rel, name)] = unit
    return graph_units


def _append_repository_graph_context(context: str, chunk, graph_units: dict[tuple[str, str], dict[str, Any]]) -> str:
    sections = []
    for unit in chunk:
        graph_unit = graph_units.get((_normalize_repo_relative_path(unit.relative_path), unit.name))
        if not graph_unit:
            continue
        mock_plan = graph_unit.get("mock_plan") or {}
        sections.append(
            "\n".join(
                [
                    f"Unit: {graph_unit.get('relative_path')} / {graph_unit.get('name')}",
                    f"Unit ID: {graph_unit.get('id')}",
                    f"Calls: {', '.join(graph_unit.get('calls') or []) or 'none detected'}",
                    f"Dependencies: {', '.join(graph_unit.get('dependencies') or []) or 'none detected'}",
                    "Deterministic mock plan:",
                    json.dumps(mock_plan, indent=2, ensure_ascii=True),
                ]
            )
        )
    if not sections:
        return context
    return (
        context
        + "\n\nRepository Knowledge Graph Context\n"
        + "Use this deterministic analysis when deciding imports, mocks, setup, and side-effect isolation.\n\n"
        + "\n\n".join(sections)
    )


def _metadata_for_generated_case(test_case: GeneratedTestCase, graph_units: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    target = _normalize_repo_relative_path(test_case.target_file)
    graph_unit = graph_units.get((target, test_case.target_function_or_route or ""))
    if graph_unit is None:
        for (relative_path, name), candidate in graph_units.items():
            if relative_path == target and (name in (test_case.target_function_or_route or "") or (test_case.target_function_or_route or "") in name):
                graph_unit = candidate
                break
    if not graph_unit:
        return {}
    return {
        "unit_id": graph_unit.get("id", ""),
        "mock_plan": graph_unit.get("mock_plan") or {},
    }


def _fill_missing_case_fields(test_case: GeneratedTestCase, units, repo_path: str) -> None:
    if not units:
        return
    fallback = units[0]
    if not test_case.target_file:
        test_case.target_file = fallback.relative_path
    if not test_case.unit_type:
        test_case.unit_type = fallback.unit_type
    if not test_case.target_function_or_route:
        test_case.target_function_or_route = fallback.name
    if not test_case.test_description:
        test_case.test_description = f"Test {test_case.unit_type} {test_case.target_function_or_route}"

    normalized = _normalize_repo_relative_path(test_case.target_file)
    resolved = _resolve_target_path(repo_path, normalized)
    if resolved.exists() and resolved.is_file():
        test_case.target_file = normalized
        return

    fallback_path = _normalize_repo_relative_path(fallback.relative_path)
    fallback_resolved = _resolve_target_path(repo_path, fallback_path)
    if fallback_resolved.exists() and fallback_resolved.is_file():
        test_case.target_file = fallback_path
        return

    test_case.target_file = normalized


def _safe_filename_part(value: str) -> str:
    value = value.strip()
    value = value.replace("\\", "_").replace("/", "_")
    value = re.sub(r"[\x00-\x1f]+", "_", value)
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._")
    return value[:120] or "item"


def _normalize_repo_relative_path(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"[\x00-\x1f]+", "", value)
    value = value.replace("\\", "/")
    value = re.sub(r"/+", "/", value)
    value = value.lstrip("./")
    value = _strip_to_stack_root(value)
    if value.startswith("backend/") or value.startswith("frontend/"):
        return value
    if value.startswith("backend") and not value.startswith("backend/"):
        return f"backend/{value[len('backend'):].lstrip('/')}"
    if value.startswith("frontend") and not value.startswith("frontend/"):
        return f"frontend/{value[len('frontend'):].lstrip('/')}"
    return value or "unknown_target"


def _strip_to_stack_root(value: str) -> str:
    lowered = value.lower()
    for marker in ("/backend/", "/frontend/"):
        index = lowered.find(marker)
        if index >= 0:
            return value[index + 1 :]
    return value


def _resolve_target_path(repo_path: str, target_file: str) -> Path:
    root = Path(repo_path).resolve()
    candidate = Path(target_file)
    if candidate.is_absolute():
        _log_resolved_target(target_file, candidate, "absolute candidate", [candidate])
        return candidate

    normalized = candidate.as_posix().replace("\\", "/").lstrip("./")
    source_candidates = _guess_source_candidates(root, normalized)
    for guessed in source_candidates:
        if guessed.exists() and guessed.is_file():
            _log_resolved_target(target_file, guessed, "source candidate file", source_candidates)
            return guessed
        if guessed.exists() and guessed.is_dir():
            direct = _find_in_directory(guessed, normalized)
            if direct is not None:
                _log_resolved_target(target_file, direct, "source candidate directory scan", source_candidates)
                return direct

    if normalized.startswith("backend/") or normalized.startswith("frontend/"):
        direct = root / normalized
        if direct.exists():
            _log_resolved_target(target_file, direct, "direct prefixed path", source_candidates + [direct])
            return direct
    if normalized.startswith("backend") or normalized.startswith("frontend"):
        direct = root / normalized
        if direct.exists():
            _log_resolved_target(target_file, direct, "direct loose-prefixed path", source_candidates + [direct])
            return direct

    for prefix in ("backend/", "frontend/"):
        guessed = root / prefix / normalized
        if guessed.exists():
            _log_resolved_target(target_file, guessed, f"{prefix.rstrip('/')} prefix guess", source_candidates + [guessed])
            return guessed

    path_variants = _guess_path_variants(normalized)
    for path_variant in path_variants:
        guessed = root / path_variant
        if guessed.exists():
            _log_resolved_target(target_file, guessed, "path variant", source_candidates + [root / item for item in path_variants])
            return guessed
        if guessed.parent.exists():
            direct = _find_in_directory(guessed.parent, guessed.name)
            if direct is not None:
                _log_resolved_target(target_file, direct, "path variant directory scan", source_candidates + [root / item for item in path_variants])
                return direct

    best_match = _best_target_match(root, normalized)
    if best_match is not None:
        _log_resolved_target(target_file, best_match, "best target match", source_candidates + [root / item for item in path_variants])
        return best_match

    fallback = root / normalized
    _log_resolved_target(target_file, fallback, "fallback normalized path", source_candidates + [root / item for item in path_variants] + [fallback])
    return fallback


def _log_resolved_target(target_file: str, resolved_path: Path, branch: str, candidates: list[Path] | None = None) -> None:
    candidate_text = ", ".join(str(path) for path in candidates or [])
    logger.debug("Resolved target_file='%s' -> '%s' via %s; candidates=[%s]", target_file, resolved_path, branch, candidate_text)


def _guess_source_candidates(root: Path, target_file: str) -> list[Path]:
    candidates: list[Path] = []
    cleaned = target_file.replace("\\", "/").lstrip("./")
    lowered = cleaned.lower()
    stem = Path(cleaned).stem.lower()
    name = Path(cleaned).name

    if "backend" in lowered or lowered.startswith("controllers") or lowered.startswith("controller"):
        controller_dir = root / "backend" / "controllers"
        candidates.append(controller_dir)
        cleaned_name = _infer_source_name(cleaned)
        if not cleaned_name or cleaned_name.lower() == "backend":
            cleaned_name = _infer_source_name(re.sub(r"(?i)backendcontrollers", "", cleaned))
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
    cleaned = target_file.replace("\\", "/").lstrip("./")
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
        if any(part in {"node_modules", ".git", "dist", "build", "coverage", "generated_tests"} for part in rel_parts):
            continue
        lower_name = path.name.lower()
        path_stem = path.stem.lower()
        if any(token in lower_name for token in (".test.", ".spec.", "generated")):
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
        if any(part in {"node_modules", ".git", "dist", "build", "coverage", "generated_tests"} for part in rel_parts):
            continue
        if path.name.lower().endswith((".test.js", ".test.jsx", ".test.ts", ".test.tsx", ".spec.js", ".spec.jsx", ".spec.ts", ".spec.tsx")):
            continue

        score = 0
        path_name = path.name.lower()
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


def _stamp_test_id_in_titles(test_code: str, test_id: str) -> str:
    pattern = re.compile(r"\b(it|test)(\.(?:only|skip|todo|concurrent))?\s*\(\s*(['\"`])(?!\[TC-\d+\])")

    def add_id(match: re.Match) -> str:
        variant = match.group(2) or ""
        quote = match.group(3)
        return f"{match.group(1)}{variant}({quote}[{test_id}] "

    stamped, count = pattern.subn(add_id, test_code)
    if count:
        return stamped
    return test_code
