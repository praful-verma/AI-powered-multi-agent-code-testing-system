from __future__ import annotations

import re

from multiagent_testing.analyzer.models import ExportNode


NAMED_EXPORT_RE = re.compile(r"\bexport\s+(?:async\s+)?(?:function|const|let|var|class)\s+([A-Za-z_$][\w$]*)")
DEFAULT_EXPORT_RE = re.compile(r"\bexport\s+default\s+([A-Za-z_$][\w$]*)?")
MODULE_EXPORT_OBJECT_RE = re.compile(r"module\.exports\s*=\s*\{(?P<body>[^}]+)\}")
MODULE_EXPORT_NAME_RE = re.compile(r"module\.exports(?:\.([A-Za-z_$][\w$]*))?\s*=")
EXPORTS_NAME_RE = re.compile(r"\bexports\.([A-Za-z_$][\w$]*)\s*=")


def extract_exports(text: str) -> list[ExportNode]:
    exports: list[ExportNode] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in NAMED_EXPORT_RE.finditer(line):
            exports.append(ExportNode(name=match.group(1), line=line_number, export_kind="named"))

        default_match = DEFAULT_EXPORT_RE.search(line)
        if default_match:
            exports.append(ExportNode(name=default_match.group(1) or "default", line=line_number, export_kind="default"))

        object_match = MODULE_EXPORT_OBJECT_RE.search(line)
        if object_match:
            for name in _object_export_names(object_match.group("body")):
                exports.append(ExportNode(name=name, line=line_number, export_kind="commonjs_named"))
            continue

        module_match = MODULE_EXPORT_NAME_RE.search(line)
        if module_match:
            exports.append(ExportNode(name=module_match.group(1) or "default", line=line_number, export_kind="commonjs"))

        for exports_match in EXPORTS_NAME_RE.finditer(line):
            exports.append(ExportNode(name=exports_match.group(1), line=line_number, export_kind="commonjs_named"))

    return _dedupe_exports(exports)


def _object_export_names(body: str) -> list[str]:
    names = []
    for raw_part in body.split(","):
        part = raw_part.strip()
        if not part:
            continue
        names.append(part.split(":", 1)[0].strip())
    return names


def _dedupe_exports(exports: list[ExportNode]) -> list[ExportNode]:
    seen: set[tuple[str, str]] = set()
    unique: list[ExportNode] = []
    for item in exports:
        key = (item.name, item.export_kind)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
