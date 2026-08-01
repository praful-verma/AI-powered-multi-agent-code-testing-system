from __future__ import annotations

import re
from pathlib import Path

from multiagent_testing.analyzer.models import ImportNode


REQUIRE_RE = re.compile(
    r"(?:const|let|var)\s+(?P<binding>[A-Za-z_$][\w$]*|\{[^}]+\})\s*=\s*require\(\s*['\"](?P<source>[^'\"]+)['\"]\s*\)"
)
MULTILINE_REQUIRE_RE = re.compile(
    r"(?:const|let|var)\s+\{(?P<binding>[^}]+)\}\s*=\s*require\(\s*['\"](?P<source>[^'\"]+)['\"]\s*\)",
    re.MULTILINE | re.DOTALL,
)
SIDE_EFFECT_REQUIRE_RE = re.compile(r"require\(\s*['\"](?P<source>[^'\"]+)['\"]\s*\)")
IMPORT_RE = re.compile(
    r"^\s*import\s+(?P<body>.+?)\s+from\s+['\"](?P<source>[^'\"]+)['\"]\s*;?\s*$"
)
SIDE_EFFECT_IMPORT_RE = re.compile(r"^\s*import\s+['\"](?P<source>[^'\"]+)['\"]\s*;?\s*$")


def extract_imports(text: str, file_path: Path, root: Path) -> list[ImportNode]:
    imports: list[ImportNode] = []
    for require_match in MULTILINE_REQUIRE_RE.finditer(text):
        imports.append(
            _make_import(
                source=require_match.group("source"),
                binding_text=require_match.group("binding"),
                line=text[: require_match.start()].count("\n") + 1,
                import_kind="require",
                file_path=file_path,
                root=root,
            )
        )
    for line_number, line in enumerate(text.splitlines(), start=1):
        require_match = REQUIRE_RE.search(line)
        if require_match:
            imports.append(
                _make_import(
                    source=require_match.group("source"),
                    binding_text=require_match.group("binding"),
                    line=line_number,
                    import_kind="require",
                    file_path=file_path,
                    root=root,
                )
            )
            continue

        import_match = IMPORT_RE.search(line)
        if import_match:
            imports.append(
                _make_import(
                    source=import_match.group("source"),
                    binding_text=import_match.group("body"),
                    line=line_number,
                    import_kind="import",
                    file_path=file_path,
                    root=root,
                )
            )
            continue

        side_effect_match = SIDE_EFFECT_IMPORT_RE.search(line) or SIDE_EFFECT_REQUIRE_RE.search(line)
        if side_effect_match:
            imports.append(
                _make_import(
                    source=side_effect_match.group("source"),
                    binding_text="",
                    line=line_number,
                    import_kind="side_effect",
                    file_path=file_path,
                    root=root,
                )
            )
    return _dedupe_imports(imports)


def _make_import(
    source: str,
    binding_text: str,
    line: int,
    import_kind: str,
    file_path: Path,
    root: Path,
) -> ImportNode:
    resolved_path = _resolve_import_path(source, file_path, root)
    return ImportNode(
        source=source,
        bindings=_extract_bindings(binding_text),
        line=line,
        import_kind=import_kind,
        resolved_path=resolved_path,
        is_external=not source.startswith("."),
    )


def _extract_bindings(binding_text: str) -> list[str]:
    cleaned = binding_text.strip()
    if not cleaned:
        return []
    cleaned = cleaned.replace("{", "").replace("}", "")
    cleaned = cleaned.replace("* as ", "")
    parts = []
    for raw_part in cleaned.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if " as " in part:
            part = part.rsplit(" as ", 1)[-1].strip()
        parts.append(part)
    return parts


def _resolve_import_path(source: str, file_path: Path, root: Path) -> str | None:
    if not source.startswith("."):
        return None

    base = (file_path.parent / source).resolve()
    candidates = [
        base,
        *[base.with_suffix(ext) for ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")],
        *[(base / f"index{ext}") for ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")],
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            try:
                return candidate.relative_to(root).as_posix()
            except ValueError:
                return candidate.as_posix()
    return None


def _dedupe_imports(imports: list[ImportNode]) -> list[ImportNode]:
    seen: set[tuple[str, int, tuple[str, ...]]] = set()
    unique: list[ImportNode] = []
    for item in imports:
        key = (item.source, item.line, tuple(item.bindings))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
