## Commands

### Linting and Type Checking

**Run after modifying any Python code:**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy .
```

Auto-fix: `uv run ruff check . --fix && uv run ruff format .`

## Documentation Standards

Stale docs are worse than no docs. Only document things the code can't say for itself.

- **Don't duplicate** what the code, type hints, or tools (FastAPI Swagger) already express.
- **Don't document** file trees, endpoint tables, or anything that drifts when code changes.
- **Do document** non-obvious constraints, architecture decisions, cross-cutting domain logic, and operational runbooks.
- **Co-locate.** Docstring on the class/function, not a separate README — unless it spans multiple files.

## Coding Standards

### Maximum Nesting Depth of 3

**Maximum nesting depth of 3 levels.** Do not nest logic (if/for/while/try) deeper than 3 layers unless absolutely necessary. Prefer guard clauses and early returns to flatten control flow and improve readability.

### noqa comments must include a reason

Every `# noqa:` suppression must explain **why** the rule is suppressed, inline on the same line.

### No Future Annotations Import

Do NOT use `from __future__ import annotations`. Python 3.13 supports all modern type hint syntax natively:

- Union syntax: `str | None`
- Generic builtins: `list[str]`, `dict[str, Any]`

For forward references (rare), use quoted strings: `def method(self) -> "ClassName":`

### Avoid `Any` Type

Avoid using `Any` as much as possible. Prefer specific types:

- Use `dict[str, str | int | None]` instead of `dict[str, Any]` when the value types are known
- Use `TypedDict` for dictionaries with known keys and value types
- Use `Literal["option1", "option2"]` for string enums
- Use union types (`str | int`) instead of `Any` for multiple known types
- Use generics (`list[T]`, `Callable[[T], R]`) to preserve type information

When `Any` is unavoidable (e.g., third-party library returns, JSON parsing), isolate it at boundaries and cast to specific types as soon as possible.

### Type Aliases

Use the Python 3.12+ `type` statement for all type aliases
