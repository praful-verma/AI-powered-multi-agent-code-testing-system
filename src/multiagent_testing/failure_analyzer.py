from __future__ import annotations


def categorize_failure(output: str) -> str:
    text = (output or "").lower()
    if not text:
        return "Unknown"
    if any(token in text for token in ("coverage command failed", "coverage run", "no coverage percent", "coverage provider")):
        return "Coverage"
    if any(token in text for token in ("environment setup failed", "enoent", "eacces", "permission", "npm install failed", "cannot find package manager")):
        return "Environment"
    if any(token in text for token in ("timeout", "exceeded timeout", "timed out", "test timed out")):
        return "Timeout"
    if any(token in text for token in ("syntaxerror", "unexpected token", "unterminated string", "missing semicolon", "failed to parse source")):
        return "Syntax"
    if any(token in text for token in ("cannot find module", "module not found", "failed to resolve import", "could not resolve", "does not provide an export")):
        return "Import"
    if any(token in text for token in ("mock", "is not a function", "mockresolvedvalue", "mockimplementation", "vi.fn", "jest.fn", "spyon", "requires a callback function but got", "route.get() requires a callback")):
        return "Mock"
    if any(token in text for token in ("expected", "received", "assertion", "to equal", "to be", "expect(")):
        return "Assertion"
    if any(token in text for token in ("typeerror", "referenceerror", "rangeerror", "cannot read properties", "cannot destructure property")):
        return "Runtime"
    return "Unknown"
