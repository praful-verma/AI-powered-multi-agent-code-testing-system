from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from multiagent_testing.models import CodeUnit


class TokenCounter:
    def __init__(self) -> None:
        try:
            import tiktoken

            self._encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoding = None

    def count(self, text: str) -> int:
        if self._encoding:
            return len(self._encoding.encode(text))
        return max(1, len(text) // 4)


def group_units_for_llm(units: list[CodeUnit], repo_path: str, max_input_tokens: int = 2200) -> list[list[CodeUnit]]:
    counter = TokenCounter()
    grouped: dict[str, list[CodeUnit]] = defaultdict(list)
    for unit in units:
        grouped[unit.relative_path].append(unit)

    chunks: list[list[CodeUnit]] = []
    for file_units in grouped.values():
        current: list[CodeUnit] = []
        current_tokens = 0
        for unit in sorted(file_units, key=lambda u: u.start_line):
            unit_tokens = counter.count(unit.source) + 200
            if current and current_tokens + unit_tokens > max_input_tokens:
                chunks.append(current)
                current = []
                current_tokens = 0
            current.append(unit)
            current_tokens += unit_tokens
        if current:
            chunks.append(current)
    return chunks


def build_chunk_prompt_context(units: list[CodeUnit], repo_path: str) -> str:
    root = Path(repo_path)
    parts: list[str] = []
    if not units:
        return ""

    target_file = root / units[0].relative_path
    imports = signature_only_import_context(target_file)
    if imports:
        parts.append("Target file import/export signatures:\n" + imports)

    dependencies = direct_dependency_context(target_file, root)
    if dependencies:
        parts.append("Direct local dependency context for mocking/stubbing:\n" + dependencies)

    for unit in units:
        parts.append(
            "\n".join(
                [
                    f"Unit: {unit.unit_type} {unit.name}",
                    f"Location: {unit.relative_path}:{unit.start_line}-{unit.end_line}",
                    "Source:",
                    "```javascript",
                    unit.source,
                    "```",
                ]
            )
        )
    return "\n\n".join(parts)


def direct_dependency_context(file_path: Path, repo_root: Path, max_files: int = 6, max_chars_per_file: int = 1800) -> str:
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception:
        return ""

    dependency_paths = _local_dependency_paths(text, file_path.parent, repo_root)
    if not dependency_paths:
        return ""

    blocks: list[str] = []
    for dependency_path in dependency_paths[:max_files]:
        try:
            rel = dependency_path.relative_to(repo_root).as_posix()
        except ValueError:
            rel = dependency_path.as_posix()
        dependency_summary = signature_only_import_context(dependency_path)
        source_excerpt = _dependency_source_excerpt(dependency_path, max_chars_per_file)
        block_parts = [f"Dependency: {rel}"]
        if dependency_summary:
            block_parts.append(dependency_summary)
        if source_excerpt:
            block_parts.extend(["Relevant source excerpt:", "```javascript", source_excerpt, "```"])
        blocks.append("\n".join(block_parts))
    return "\n\n".join(blocks)


def _local_dependency_paths(source: str, base_dir: Path, repo_root: Path) -> list[Path]:
    module_refs: list[str] = []
    patterns = [
        r"\bimport\s+(?:[^'\"]+\s+from\s+)?(['\"])(?P<module>\.{1,2}/[^'\"]+)\1",
        r"\brequire\(\s*(['\"])(?P<module>\.{1,2}/[^'\"]+)\1\s*\)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, source):
            module_refs.append(match.group("module"))

    dependency_paths: list[Path] = []
    for module_ref in module_refs:
        resolved = _resolve_local_module(base_dir, module_ref, repo_root)
        if resolved and resolved not in dependency_paths:
            dependency_paths.append(resolved)
    return dependency_paths


def _resolve_local_module(base_dir: Path, module_ref: str, repo_root: Path) -> Path | None:
    candidate = (base_dir / module_ref).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError:
        return None

    candidates = [candidate]
    candidates.extend(candidate.with_suffix(suffix) for suffix in [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"])
    candidates.extend(candidate / f"index{suffix}" for suffix in [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"])
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def _dependency_source_excerpt(file_path: Path, max_chars: int) -> str:
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception:
        return ""

    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (
            stripped.startswith(("import ", "export ", "module.exports", "exports."))
            or "mongoose.model" in stripped
            or "new mongoose.Schema" in stripped
            or "new Schema" in stripped
            or re.search(r"\b(?:router|app)\.(?:get|post|put|patch|delete|use)\s*\(", stripped)
            or re.search(r"\b(?:async\s+)?function\s+[A-Za-z_$][\w$]*\s*\(", stripped)
            or re.search(r"\bconst\s+[A-Za-z_$][\w$]*\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>", stripped)
        ):
            lines.append(stripped[:260])
        if len("\n".join(lines)) >= max_chars:
            break
    excerpt = "\n".join(lines)
    return excerpt[:max_chars]


def signature_only_import_context(file_path: Path) -> str:
    try:
        text = file_path.read_text(encoding="utf-8")
    except Exception:
        return ""

    imports = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("const ") and "require(" in stripped:
            imports.append(stripped[:220])

    exports = []
    for pattern in [
        r"export\s+(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)",
        r"export\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)",
        r"module\.exports\.([A-Za-z_$][\w$]*)\s*=",
    ]:
        for match in re.finditer(pattern, text):
            name = match.group(1)
            args = match.group(2) if len(match.groups()) > 1 and match.group(2) is not None else ""
            exports.append(f"{name}({args})")

    lines = []
    if imports:
        lines.append("Imports:")
        lines.extend(f"- {item}" for item in imports[:20])
    if exports:
        lines.append("Exports:")
        lines.extend(f"- {item}" for item in exports[:20])
    return "\n".join(lines)


def relevant_source_context(repo_path: str, target_file: str, function_or_route: str, fallback_window: int = 120) -> str:
    path = Path(repo_path) / target_file
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""

    needle = function_or_route.split()[-1] if function_or_route else ""
    for idx, line in enumerate(lines, start=1):
        if needle and needle in line:
            start = max(1, idx - 20)
            end = min(len(lines), idx + fallback_window)
            numbered = [f"{line_no}: {lines[line_no - 1]}" for line_no in range(start, end + 1)]
            return "\n".join(numbered)

    end = min(len(lines), fallback_window)
    return "\n".join(f"{line_no}: {lines[line_no - 1]}" for line_no in range(1, end + 1))
