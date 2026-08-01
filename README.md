# Repository-Aware Multi-Agent Code Testing System

LangGraph + Groq system that analyzes a MERN repository, plans isolated unit tests, builds deterministic test skeletons, validates and repairs generated tests, executes them, categorizes failures, and reports confidence for each result.

The current implementation focuses on testing **MERN** repositories. The overall architecture is modular and designed so that support for additional technology stacks can be added in the future without major changes to the core workflow.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file in the repo root with:

```env
GROQ_API_KEY=your-groq-key
```

## Run

```powershell
python -m multiagent_testing.main --repo C:\path\to\repo --stack auto
```

Common options:

```powershell
python -m multiagent_testing.main --repo https://github.com/org/project.git --stack mern --output-dir .\runs --max-input-tokens 3000
python -m multiagent_testing.main --repo C:\path\to\repo --skip-runner
python -m multiagent_testing.main --repo C:\path\to\repo --skip-fixes
python -m multiagent_testing.main --repo C:\path\to\repo --runner-only --rerun-all-tests --skip-fixes
python -m multiagent_testing.main --repo C:\path\to\repo --reuse-existing-tests --rerun-all-tests
python -m multiagent_testing.main --repo C:\path\to\repo --analyze-only
python -m multiagent_testing.main --repo C:\path\to\repo --plan-only
python -m multiagent_testing.main --repo C:\path\to\repo --validate-only
python -m multiagent_testing.main --repo C:\path\to\repo --coverage
python -m multiagent_testing.main --repo C:\path\to\repo --legacy-generator
uv run python -m multiagent_testing.main --repo C:\Users\vpraf\OneDrive\Desktop\mern-bookshelf-app\mern-bookshelf-app --stack mern --excel-path .\runs\test_cases_fresh.xlsx
python -m multiagent_testing.main --repo C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app --stack mern
```

Use `--skip-fixes` while iterating on test generation/running to avoid spending Groq tokens on Agent 3 fix suggestions.

`--legacy-generator` keeps the old full-file LLM generator path available. The default path uses deterministic repository analysis, test planning, assertion fragments, and template-based test construction.

## Outputs

- `runs/test_cases.xlsx`: shared source of truth between all agents.
- `runs/repository_graph.json`: deterministic repository knowledge graph.
- `runs/test_plan.json`: behavior-focused test specifications.
- `runs/assertion_blocks.json`: localized assertion fragments.
- `runs/validation_report.md`: static validation and repair summary.
- `runs/repair_report.md`: deterministic repair summary.
- `runs/failure_report.md`: categorized runner failures.
- `runs/confidence_report.md`: confidence score summary and per-test explanations.
- `runs/fix_report.md`: consolidated fix suggestions grouped by file.
- `runs/checkpoints/`: graph checkpoint database when LangGraph checkpointing is available.

## Architecture

- Repository analyzer: walks JavaScript/TypeScript source, extracts imports, exports, dependencies, calls, units, and mock plans.
- Test planner: creates behavior-focused `TestSpecification` objects.
- Assertion generator: produces localized assertion bodies instead of complete test files.
- Test builder: creates deterministic test files from templates plus assertion fragments.
- Static validator and auto repair: catch common generated-test problems before execution.
- Test runner: executes generated tests, attaches validation/repair/coverage/failure/confidence fields to Excel, and writes Markdown reports.
- Fix suggester: sends categorized failure context plus repository graph/mock-plan context to Groq.

The current implementation is designed for MERN repositories. The overall workflow is modular, making it straightforward to extend support for additional technology stacks in the future.

## Confidence Scores

Each test receives `confidence_score` and `confidence_details` in Excel. The score considers execution status, runner score, static validation, deterministic repairs, coverage, and unresolved dependency hints. Clean passing tests with validation and coverage score highest; repaired or failed tests are penalized and explained in `runs/confidence_report.md`.

