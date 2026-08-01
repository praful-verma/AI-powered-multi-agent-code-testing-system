# Repository-Aware Multi-Agent Autonomous Unit Testing Framework for MERN Applications

## 1. Final Vision

The project should evolve from an LLM-first test generator into a repository-aware testing compiler. The LLM remains important, but it becomes one component inside a deterministic pipeline that analyzes the repository, plans mocks, generates structured test specifications, validates generated files, executes them, and produces fix suggestions with confidence scores.

### Input

- Local repository path
- GitHub repository URL
- Optional stack override, initially `mern`
- Optional execution controls such as skip runner, skip fixes, rerun all tests, and max LLM chunk size

### Output

- Repository analysis
- Dependency graph
- Unit discovery
- Test plan
- Runnable tests
- Test execution results
- Coverage report
- Failure report
- AI fix suggestions
- Confidence score per test
- Excel workbook and Markdown reports

## 2. Current Project State

The current codebase already has a useful foundation:

- `repo_loader.py` materializes local or GitHub repositories.
- `adapters/mern.py` detects MERN repositories, discovers testable units, prepares generated tests, executes Jest/Vitest, and parses results.
- `agents/test_generator.py` chunks units and asks Groq to generate complete test files.
- `agents/test_runner.py` materializes and executes generated tests, then updates Excel rows.
- `agents/fix_suggester.py` sends failing test context to Groq and writes fix suggestions.
- `graph.py` connects generation, execution, and fix suggestion through LangGraph.
- `schema.py`, `models.py`, and `excel_store.py` define the workbook contract and shared state.

The biggest weakness is that too much responsibility is inside prompts. The redesigned architecture should move repository understanding, dependency analysis, mock planning, file templates, validation, repair, and scoring into deterministic Python modules.

## 3. Target Architecture

```text
User
  |
  v
Repository Loader
  |
  v
Repository Analyzer
  |
  +--> Import Analyzer
  +--> Export Analyzer
  +--> Dependency Analyzer
  +--> Unit Analyzer
  +--> Call Graph Generator
  |
  v
Repository Knowledge Graph
  |
  v
Mock Planner
  |
  v
Agent 1: Test Planner
  |
  v
Test Specification Objects
  |
  v
Template-Based Test Builder
  |
  v
Agent 2: Assertion Generator
  |
  v
Static Validation Pass
  |
  v
Auto Repair Pass
  |
  v
Test Runner
  |
  v
Failure Analyzer
  |
  v
Agent 3: Fix Generator
  |
  v
Confidence Scorer
  |
  v
Excel + Markdown + Coverage Reports
```

## 4. Proposed Folder Structure

```text
src/multiagent_testing/
  analyzer/
    __init__.py
    models.py
    repository_graph.py
    repository_analyzer.py
    import_analyzer.py
    export_analyzer.py
    dependency_analyzer.py
    call_graph.py
    unit_classifier.py
    mock_planner.py

  templates/
    __init__.py
    base.py
    controller.py
    route.py
    component.py
    api.py
    middleware.py
    service.py
    model.py

  validators/
    __init__.py
    syntax_validator.py
    import_validator.py
    mock_validator.py
    template_validator.py
    path_validator.py

  repair/
    __init__.py
    auto_import.py
    duplicate_fix.py
    mock_fix.py
    path_fix.py
    syntax_fix.py

  agents/
    test_planner.py
    assertion_generator.py
    test_runner.py
    fix_suggester.py
```

The existing `adapters/` layer should remain. Stack-specific behavior belongs there, while the new analyzer, validator, repair, and template modules should expose reusable contracts that future adapters can implement for Spring Boot, Django, Flask, FastAPI, or other stacks.

## 5. Core Data Model

### RepositoryGraph

The Repository Knowledge Graph should become the central object passed between deterministic modules and LLM agents.

Recommended fields:

- `root_path`
- `stack`
- `package_managers`
- `test_framework`
- `files`
- `units`
- `dependencies`
- `imports`
- `exports`
- `call_edges`
- `routes`
- `models`
- `frontend_components`
- `warnings`

### SourceFileNode

Every source file should be represented as a structured object:

- `path`
- `relative_path`
- `language`
- `stack_area`: backend, frontend, shared, unknown
- `file_role`: controller, route, model, service, utility, component, hook, context, api_helper, middleware, config
- `imports`
- `exports`
- `functions`
- `classes`
- `jsx_components`
- `hooks`
- `routes`
- `dependencies`
- `source_hash`

### UnitNode

Every testable unit should preserve compatibility with the current `CodeUnit` dataclass while adding richer metadata:

- `id`
- `file_path`
- `relative_path`
- `unit_type`
- `name`
- `start_line`
- `end_line`
- `source`
- `imports_used`
- `exports_used`
- `calls`
- `dependencies`
- `mock_plan`
- `template_kind`
- `risk_level`

### DependencyNode

Dependencies should be classified before the LLM sees them:

- `name`
- `import_path`
- `resolved_path`
- `dependency_type`: mongoose_model, axios_client, fetch_client, filesystem, jwt, auth_middleware, payment_sdk, logger, timer, env, local_module, unknown
- `methods`
- `side_effect_level`
- `mock_strategy`
- `framework_api`: jest, vi, sinon, none

### TestSpecification

The LLM should first produce test ideas, not complete files:

- `target_unit_id`
- `scenario_name`
- `purpose`
- `arrange_steps`
- `act_steps`
- `expected_behavior`
- `required_mocks`
- `priority`

### GeneratedTestArtifact

The builder and validators should operate on a separate artifact object:

- `test_id`
- `target_unit_id`
- `test_file_path`
- `test_code`
- `template_kind`
- `static_validation_status`
- `repairs_applied`
- `execution_status`
- `confidence_score`

## 6. Pipeline Phases

### Phase 1: Repository Loader

Status: already implemented.

Responsibilities:

- Accept a local repository path or GitHub URL.
- Clone remote repositories into a temporary directory.
- Preserve the original repo path in state.
- Ignore directories such as `node_modules`, `.git`, `dist`, `build`, and `coverage`.
- Return a stable repository root for downstream modules.

Implementation notes:

- Keep `materialize_repo()` as the entry point.
- Add tests that verify temporary repo cleanup still works.
- Add future support for branch selection only after the core analyzer is stable.

### Phase 2: Repository Analyzer

Status: new.

This module should replace shallow unit discovery with a complete repository graph.

Responsibilities:

- Walk all JavaScript, TypeScript, JSX, and TSX files.
- Classify each file by stack area and role.
- Extract imports and exports.
- Extract top-level functions, classes, React components, hooks, Express routers, and Mongoose models.
- Attach line ranges and source snippets.
- Produce `RepositoryGraph`.

Recommended implementation:

- Start with regex and lightweight parsing because the current project is Python-only.
- Add optional AST support later through a Node parser helper if accuracy becomes a blocker.
- Keep all ignored directory rules centralized.

Deliverables:

- `analyzer/models.py`
- `analyzer/repository_graph.py`
- `analyzer/repository_analyzer.py`
- Unit tests using small fixture repositories.

### Phase 3: Import and Export Analysis

Status: new.

Responsibilities:

- Parse CommonJS `require`.
- Parse ES module `import`.
- Parse named exports, default exports, and `module.exports`.
- Resolve local relative imports to actual files.
- Keep unresolved third-party dependencies as external dependencies.

Examples to support:

```javascript
const Book = require("../models/Book");
const { sendEmail } = require("../services/mail");
import axios from "axios";
import { useAuth } from "../context/AuthContext";
module.exports = { getBooks, addBook };
export default BookList;
export const fetchBooks = () => {};
```

Deliverables:

- `analyzer/import_analyzer.py`
- `analyzer/export_analyzer.py`
- Tests for CommonJS, ESM, mixed exports, and relative path resolution.

### Phase 4: Dependency Analyzer

Status: new.

Responsibilities:

- Convert imports and calls into typed dependencies.
- Identify local modules versus third-party packages.
- Detect Mongoose models, axios/fetch clients, JWT/auth helpers, filesystem access, timers, environment reads, logging, and SDK calls.
- Attach mock strategies to each dependency.

Example output:

```json
{
  "name": "Book",
  "dependency_type": "mongoose_model",
  "methods": ["find", "create", "findById"],
  "mock_strategy": "module_mock"
}
```

Deliverables:

- `analyzer/dependency_analyzer.py`
- `DependencyNode` tests for Mongoose, axios, fetch, JWT, fs, local modules, and unknown packages.

### Phase 5: Call Graph Generator

Status: new.

Responsibilities:

- Identify calls made by each unit.
- Connect unit calls to dependencies.
- Preserve enough information to generate mocks without asking the LLM what to mock.

Example:

```text
addBook
  -> Book.create
  -> sendEmail
  -> logger.info
  -> res.status
  -> res.json
```

Deliverables:

- `analyzer/call_graph.py`
- Tests that verify calls are attached to the right unit.

### Phase 6: Unit Classification

Status: partially implemented in `MERNAdapter.discover_units`.

Responsibilities:

- Classify units into controller, route, React component, custom hook, API helper, context provider, middleware, service, utility, model, and schema.
- Assign a test template kind.
- Assign risk and priority hints based on dependency type and branching.

Implementation notes:

- Keep MERN-specific classification rules in `adapters/mern.py`.
- Move reusable classification helpers into `analyzer/unit_classifier.py`.
- Make `discover_units()` consume the graph rather than scanning independently.

Deliverables:

- `analyzer/unit_classifier.py`
- Adapter integration tests.

### Phase 7: Mock Planner

Status: new.

Responsibilities:

- Produce deterministic mock plans from dependencies and call graph edges.
- Decide whether to use `jest.mock`, `vi.mock`, spies, inline stubs, fake timers, or request/response objects.
- Ensure model mocks appear before requiring controllers or routes.
- Prevent live database, network, filesystem, process, and auth side effects.

Example:

```json
{
  "target_unit": "backend/controllers/bookController.js:addBook",
  "framework": "jest",
  "module_mocks": [
    {
      "import_path": "../models/Book",
      "binding": "Book",
      "methods": ["create", "find", "findById"]
    }
  ],
  "inline_stubs": ["req", "res", "next"],
  "reset_strategy": "beforeEach_clearAllMocks"
}
```

Deliverables:

- `analyzer/mock_planner.py`
- Tests for controller, route, component, API helper, middleware, and utility mocks.

### Phase 8: Agent 1 Test Planner

Status: replace current full-file generation behavior.

Current behavior:

- `agents/test_generator.py` asks Groq to produce complete runnable tests.

Target behavior:

- Rename or split this into `agents/test_planner.py`.
- Send the LLM only the repository graph slice, target unit, mock plan, and relevant source.
- Require structured `TestSpecification` output.
- Do not allow JavaScript test code in this step.

Prompt rule:

```text
Return behavior-focused test scenarios only. Do not write imports, mocks, describe blocks, or JavaScript test files.
```

Deliverables:

- `TestSpecification` Pydantic model.
- Planner agent that writes specifications to memory and Excel.
- Tests for empty planner output and retry behavior.

### Phase 9: Template-Based Test Builder

Status: new.

Responsibilities:

- Convert `TestSpecification` and `MockPlan` into runnable test boilerplate.
- Use deterministic templates per unit type.
- Handle imports, mocks, setup, teardown, `describe`, and shared fixtures.
- Leave only assertion bodies or scenario-specific details for the assertion generator.

Templates:

- Controller template: mocked models, mocked services, `req`, `res`, `next`.
- Route template: Express app, router mounting, Supertest.
- Component template: React Testing Library, mocked API helpers/context/router.
- API helper template: axios/fetch mocks.
- Middleware template: `req`, `res`, `next`.
- Service template: mocked external SDKs and local dependencies.
- Model template: schema validation focused tests, no live database by default.

Deliverables:

- `templates/base.py`
- One template module per unit type.
- Snapshot-style tests for generated boilerplate.

### Phase 10: Agent 2 Assertion Generator

Status: new or extracted from current generator.

Responsibilities:

- Fill only scenario-specific `it()` bodies and `expect()` assertions.
- Receive the source snippet, test specification, mock plan, and generated boilerplate.
- Return a small structured patch or code fragment, not a whole test file.

Why this matters:

- The LLM no longer controls imports, module paths, mock order, framework choice, or test file structure.
- Hallucinations become smaller and easier to validate.

Deliverables:

- `agents/assertion_generator.py`
- Pydantic model for assertion blocks.
- Validation that the returned fragment does not contain forbidden imports or duplicate framework setup.

### Phase 11: Static Validation

Status: new.

Responsibilities:

- Validate generated tests before execution.
- Catch common failures cheaply.

Checks:

- Duplicate imports.
- Duplicate `const express = require("express")`.
- Missing `supertest` import when `request()` is used.
- Missing axios mock in API helper tests.
- Mongoose mock declared after requiring the controller.
- `jest` used in a Vitest file or `vi` used in a Jest-only file.
- Wrong relative import path.
- Missing `beforeEach` or `clearAllMocks` when mocks exist.
- Test file path points into ignored directories.
- Private or non-exported functions imported directly.

Deliverables:

- `validators/syntax_validator.py`
- `validators/import_validator.py`
- `validators/mock_validator.py`
- `validators/template_validator.py`
- `validators/path_validator.py`
- Tests for every validation rule.

### Phase 12: Auto Repair

Status: new.

Responsibilities:

- Apply deterministic fixes before running tests.
- Track repairs per test for confidence scoring.

Repairs:

- Remove duplicate imports.
- Insert missing `supertest` import.
- Move model mocks before controller imports when safe.
- Replace `jest` with `vi` or `vi` with `jest` based on framework.
- Fix relative import paths using the repository graph.
- Insert missing `beforeEach(() => jest.clearAllMocks())` or Vitest equivalent.
- Remove imports of non-exported functions and mark the case for planner regeneration.

Deliverables:

- `repair/duplicate_fix.py`
- `repair/auto_import.py`
- `repair/mock_fix.py`
- `repair/path_fix.py`
- `repair/syntax_fix.py`
- A repair report stored in Excel and Markdown.

### Phase 13: Test Runner

Status: implemented, needs integration with validation and repair.

Responsibilities:

- Run generated tests through adapter commands.
- Capture stdout, stderr, duration, and assertion-level results.
- Parse JSON output where available.
- Attach results back to test IDs.

Enhancements:

- Run validation and repair before `_run_one_test_file`.
- Persist repaired `test_code`.
- Add optional coverage command support.
- Categorize unparseable runner output before sending to the failure analyzer.

Deliverables:

- Updated `agents/test_runner.py`.
- Adapter contract for coverage command.
- Tests for validation-before-execution behavior.

### Phase 14: Failure Analyzer

Status: new.

Responsibilities:

- Categorize failures without LLM calls.
- Reduce noisy context before fix generation.

Categories:

- Syntax
- Import
- Mock
- Runtime
- Assertion
- Timeout
- Coverage
- Environment
- Unknown

Deliverables:

- `failure_analyzer.py`
- Failure category column in Excel.
- Tests using realistic Jest/Vitest error snippets.

### Phase 15: AI Fix Generator

Status: implemented as `fix_suggester.py`, needs richer context.

Responsibilities:

- Generate targeted fix suggestions after deterministic failure categorization.
- Receive only relevant source, generated test, failure category, dependency graph slice, and mock plan.
- Distinguish source bugs from generated-test bugs.

Enhancements:

- Include mock plan in prompt.
- Include dependency graph slice.
- Include validation and repair history.
- Ask for fixes to the generated test when the failure analyzer indicates a test issue.

Deliverables:

- Updated `agents/fix_suggester.py`.
- Updated `fix_report.md` sections.

### Phase 16: Confidence Scoring

Status: partially represented by `score`, but not full confidence.

Recommended formula:

```text
confidence =
  repository_analysis_score
  + static_validation_score
  + execution_score
  + coverage_score
  - repair_penalty
  - unresolved_dependency_penalty
```

Example scoring:

- `97%`: passed, no repairs, all dependencies resolved, coverage touched target unit.
- `72%`: passed, two deterministic repairs, one unresolved optional dependency.
- `35%`: failed at runtime, repaired imports, low coverage confidence.

Deliverables:

- `confidence.py`
- Numeric confidence column or richer confidence detail column.
- Keep existing `Low`, `Med`, `High` fix-suggestion confidence for Agent 3 unless changing the Excel schema intentionally.

## 7. Updated LangGraph Flow

The current graph is:

```text
test_generator -> test_runner -> fix_suggester
```

The target graph should become:

```text
repository_analyzer
  -> mock_planner
  -> test_planner
  -> test_builder
  -> assertion_generator
  -> static_validator
  -> auto_repair
  -> test_runner
  -> failure_analyzer
  -> fix_suggester
  -> confidence_scorer
```

The graph can be introduced incrementally. During migration, keep the existing `test_generator` path behind a compatibility flag such as `--legacy-generator`.

## 8. CLI Changes

Recommended new flags:

```powershell
python -m multiagent_testing.main --repo C:\repo --stack mern --analyze-only
python -m multiagent_testing.main --repo C:\repo --plan-only
python -m multiagent_testing.main --repo C:\repo --validate-only
python -m multiagent_testing.main --repo C:\repo --legacy-generator
python -m multiagent_testing.main --repo C:\repo --coverage
python -m multiagent_testing.main --repo C:\repo --write-graph-json
```

Recommended outputs:

```text
runs/repository_graph.json
runs/test_plan.json
runs/validation_report.md
runs/repair_report.md
runs/failure_report.md
runs/fix_report.md
runs/test_cases.xlsx
```

## 9. Excel Schema Changes

Keep existing columns for compatibility:

- `test_id`
- `unit_type`
- `target_file`
- `target_function_or_route`
- `test_description`
- `test_code`
- `test_file_path`
- `priority`
- `status`
- `score`
- `actual_output`
- `execution_time_ms`
- `run_timestamp`
- `root_cause_analysis`
- `suggested_fix`
- `fix_location`
- `confidence`

Recommended additions:

- `unit_id`
- `scenario_name`
- `mock_plan`
- `validation_status`
- `validation_errors`
- `repairs_applied`
- `failure_category`
- `coverage_percent`
- `confidence_score`

Add columns carefully through `schema.py` and make `ExcelStore` preserve older workbooks where possible.

## 10. Development Roadmap

### Milestone 1: Repository Intelligence

Goal: Build deterministic repository understanding.

Tasks:

- Create `analyzer/` package.
- Define `RepositoryGraph`, `SourceFileNode`, `UnitNode`, and `DependencyNode`.
- Implement repository walking and ignored directory handling.
- Extract imports, exports, functions, classes, routes, models, components, hooks, and API helpers.
- Write graph JSON to `runs/repository_graph.json`.
- Add `--analyze-only`.
- Add fixture-based tests.

Acceptance criteria:

- A sample MERN repo produces a graph with backend and frontend files.
- Controllers, routes, models, components, hooks, and API helpers are classified.
- Local relative imports resolve to files.
- Third-party dependencies remain external.
- Existing test generation flow still works.

### Milestone 2: Dependency Analysis and Mock Planning

Goal: Know what to mock before any LLM call.

Tasks:

- Implement dependency classification.
- Implement call graph extraction.
- Implement mock planner.
- Store mock plans in graph and Excel.
- Add tests for Mongoose, axios, fetch, JWT, fs, timers, auth middleware, and SDKs.

Acceptance criteria:

- Controller units receive Mongoose model mocks.
- API helper units receive axios or fetch mocks.
- Component units receive API/context/router mock hints.
- No prompt is needed to decide basic mocks.

### Milestone 3: Planner and Template Builder

Goal: Stop asking the LLM for full test files.

Tasks:

- Add `TestSpecification` model.
- Split current generator into planner and builder responsibilities.
- Implement deterministic templates.
- Build complete test skeletons from template plus mock plan.
- Keep current generator as fallback under `--legacy-generator`.

Acceptance criteria:

- The LLM outputs behavior scenarios only.
- Templates produce runnable file structure.
- Generated files have deterministic imports, mocks, setup, and teardown.

### Milestone 4: Assertion Generator

Goal: Limit LLM code generation to small assertion blocks.

Tasks:

- Implement assertion generator agent.
- Validate returned assertion fragments.
- Insert fragments into template placeholders.
- Reject fragments containing imports, module mocks, or unrelated setup.

Acceptance criteria:

- LLM output is small and localized.
- Test files are still complete and runnable after insertion.
- Bad fragments are rejected and retried.

### Milestone 5: Static Validation and Auto Repair

Goal: Catch and fix common generated-test failures before execution.

Tasks:

- Implement validators.
- Implement deterministic repair modules.
- Add validation and repair report outputs.
- Integrate validation and repair before runner execution.

Acceptance criteria:

- Duplicate imports are removed.
- Missing Supertest import is inserted.
- Wrong framework API is corrected when safe.
- Mongoose mock order is validated.
- Validation failures are visible in Excel.

### Milestone 6: Execution, Coverage, and Failure Analysis

Goal: Make runner output structured and useful.

Tasks:

- Add failure analyzer.
- Add optional coverage command support.
- Parse coverage artifacts where available.
- Update Excel with failure category and coverage.
- Write `failure_report.md`.

Acceptance criteria:

- Syntax, import, mock, runtime, assertion, timeout, and environment failures are categorized.
- Coverage data is attached when available.
- Agent 3 receives smaller, better context.

### Milestone 7: Confidence Scoring and Reporting

Goal: Make the final result understandable and defensible.

Tasks:

- Implement confidence scoring.
- Add `confidence_score` and explanation fields.
- Improve final CLI summary.
- Update README with the redesigned pipeline.

Acceptance criteria:

- Every generated test has a numeric confidence score.
- Passed tests with repairs score lower than clean passed tests.
- Failed tests receive low confidence and a failure category.
- Reports explain what happened without reading raw logs.

## 11. Implementation Order

Recommended order for actual coding:

1. Add analyzer data models.
2. Add repository file walking and ignored directory rules.
3. Add import/export extraction.
4. Add unit classification.
5. Add dependency classification.
6. Add call graph extraction.
7. Add mock planner.
8. Add graph JSON output and `--analyze-only`.
9. Add test specification model and planner prompt.
10. Add templates.
11. Add assertion generator.
12. Add validators.
13. Add repair modules.
14. Integrate validation and repair into runner.
15. Add failure analyzer.
16. Add confidence scorer.
17. Update reports and README.

## 12. Testing Strategy

### Unit Tests

- Analyzer parsing for imports, exports, functions, and calls.
- Dependency classification.
- Mock plan generation.
- Template output.
- Validator rules.
- Repair transforms.
- Failure categorization.
- Confidence scoring.

### Integration Tests

- Tiny backend-only Express fixture.
- Tiny frontend-only React fixture.
- Tiny full MERN fixture.
- Fixture with intentionally broken generated tests.
- Fixture with Vitest frontend and Jest backend.

### Regression Tests

- Existing path normalization tests.
- Existing MERN adapter tests.
- Existing Groq client structured-output tests.
- Existing cleanup tests.

## 13. Main Risks

### JavaScript Parsing Accuracy

Regex parsing is fast to build but imperfect. Start with regex because it is enough for common MERN apps, then add an optional Node parser helper if fixtures reveal too many misses.

### Excel Schema Compatibility

Adding columns can break older workbooks if done carelessly. Add columns append-only and make readers tolerant of missing values.

### LLM Cost and Rate Limits

The redesign should reduce LLM calls by shrinking prompts and avoiding retries caused by invalid full-file generation.

### Test Runner Environment

Some repositories have missing dependencies or unusual scripts. Keep adapter setup isolated and make environment failures explicit rather than treating them as test failures.

## 14. Definition of Done

The redesign is complete when:

- The system can analyze a MERN repository into a structured graph.
- Mock plans are produced deterministically.
- The LLM no longer writes complete test files by default.
- Tests are built from templates.
- Static validation runs before execution.
- Auto repair handles common generated-test issues.
- Runner results are categorized.
- Fix suggestions receive graph and mock context.
- Every test receives a confidence score.
- Excel and Markdown reports explain the full pipeline result.

