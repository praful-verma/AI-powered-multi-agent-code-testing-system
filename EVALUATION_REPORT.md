# Evaluation report: five repository runs

## Outcome

The system produced 243 generated cases. Independent source review finds 0 correct, meaningful behavioural tests. The central failures are stale-project contamination in jobportal (125/125 cases target instaclone-main), generic assertions, invalid parser/template output, and inadequate mocks/fixtures. No repository or prior run artifact was modified.

Passing is not correctness: component cases check document.body truthiness, function cases check only that a symbol is defined, and route cases accept every response below 500. These assertions do not detect the local behavioural mutations they claim to test.

## Mapping

| ZIP | Output directory | Evidence |
|---|---|---|
| jobportal-yt-main.zip | runsjobportal | Directory/graph say jobportal; every spreadsheet record says instaclone-main: integrity conflict |
| mern-todo-app.zip | runstodo | graph root and frontend/src/backend targets |
| netflix2.0-main.zip | runsNetflix | graph/cases use netflix/src |
| shopnest-ecom-MERN-master.zip | runsShoppingapp | graph/cases name shopnest-ecom-MERN-master |
| twitter-main.zip | runstwitter | graph/cases name twitter-main/frontend/twitterclone |

All projects are MERN-style. Graphs name Jest but generated tests import Vitest; todo output proves Vitest ran. No verified coverage artifact was supplied.

## Source-derived ground truth catalog

| Repo | Source evidence | Testable behaviours | Isolation |
|---|---|---|---|
| jobportal | backend/controllers/user.controller.js:7,49,104,114; job.controller.js:4,37,64,82; application.controller.js:4,48,74,98; company.controller.js:5,35,54,72 | auth/duplicates, filters/not-found, application status, ownership | Mongoose/bcrypt/JWT/cloudinary mocks |
| jobportal | frontend src components Job:8, LatestJobCards:5, UpdateProfileDialog:13 and hooks | props, navigation, submit/error state | router/store/API mocks |
| todo | frontend/src/api.js:5,7,9,11; backend/controllers/todoController.js:4,10,20,30 | request payloads; CRUD success/error | axios/Todo mocks |
| todo | TodoItem.jsx:1, TodoList.jsx:3, TodoForm.jsx:3 | completed state, callbacks, list, form submit/reset | props/callback spies |
| Netflix | backend/controllers/user.js:5,45,52; hooks/use*.js:6-8; Login.js:11, Register.js:3, SearchMovie.js:9 | auth, fetch/dispatch, validation/submit | User/bcrypt/JWT, axios/store/router |
| ShopNest | authController:10,54,75; productController:4,13,26,44,69; orderController:4,42,51,60; paymentController:4,25; cartSlice:34 | auth, CRUD, ownership/status/payment, cart reducer | model/payment mocks or reducer only |
| Twitter | tweetController:4,27,40,62,78; userController:5,39,75,82,104,116,133,155; constant.js:4; CreatePost:10 | authorization, toggle/feed/profile, time boundaries, payload UI | Tweet/User/bcrypt/JWT, fake clock/store |

Database connectors, Express entry points, schemas, route wiring, and self-invoking ShopNest seed.js:12,80 are integration-only or environment-dependent, not generic unit-test targets.

## Case-level audit

| Cases | Target/scenario | Independent label/validity | Execution and root cause | Confidence |
|---|---|---|---|---|
| jobportal TC-0001–TC-0125 | instaclone-main paths; generic scenario | incorrect; 125 nonexistent targets, invalid path/import, non-meaningful | 35 reported pass, 90 error/fail; stale cross-repository output | 35 at 100; 90 at 0 |
| Netflix TC-0001–TC-0022 | real netflix target; primary state | partially_correct target only; vacuous/non-meaningful | 2 pass; 14 parser Expression expected; 6 Import; generator defect | 2 at 100; 20 at 0 |
| ShopNest TC-0001–TC-0055 | real target | partially_correct target only; defined/body/less-than-500 is not behaviour | 30 pass; 23 Timeout; 2 Mock; isolation/template defect | 30 at 100; 25 at 0 |
| todo TC-0001–TC-0008 | real API/component/backend target | partially_correct target only; no source-supported assertion | 5 pass; one missing default TodoList mock; two missing props; generator defect | 5 at 100; 3 at 0 |
| Twitter TC-0001–TC-0033 | real target | partially_correct target only; generic/invalid mocks, non-meaningful | 16 pass; 10 parser; 7 Import; generator defect | 16 at 100; 17 at 0 |

The ranges cover every case: each uses the same deterministic non-behavioural template; the original spreadsheets retain individual code and runner messages. No case is correct.

## Metrics

Definitions: strict = correct/judgeable; lenient = (correct+partial)/judgeable; yield = correct and executable and meaningful/generated. Independent executable requires a matching-source target. Passing-but-vacuous tests are not meaningful.

| Metric | Jobportal | Netflix | ShopNest | todo | Twitter | Macro | Micro |
|---|---:|---:|---:|---:|---:|---:|---:|
| Generated cases | 125 | 22 | 55 | 8 | 33 | 48.6 | 243 |
| Target resolution | 0/125 | 22/22 | 55/55 | 8/8 | 33/33 | 80.0% | 118/243 = 48.6% |
| Strict scenario accuracy | 0/125 | 0/22 | 0/55 | 0/8 | 0/33 | 0% | 0/243 |
| Lenient scenario accuracy | 0/125 | 22/22 | 55/55 | 8/8 | 33/33 | 80.0% | 118/243 = 48.6% |
| Behaviour, happy, error, branch, boundary coverage | 0 | 0 | 0 | 0 | 0 | 0% | 0/source behaviours |
| Assertion quality/mutation proxy | 0/125 | 0/22 | 0/55 | 0/8 | 0/33 | 0% | 0/243 |
| Static validation, reported | 125/125 | 22/22 | 55/55 | 8/8 | 33/33 | 100% | 243/243; contradicted by parser/import failures |
| Independent executable | 0/125 | 0/22 | 30/55 | 5/8 | 0/33 | 13.1% | 35/243 = 14.4% |
| Meaningful pass/generation yield | 0/125 | 0/22 | 0/55 | 0/8 | 0/33 | 0% | 0/243 |
| Minimum proven hallucination rate | 125/125 | 0/22 | 0/55 | 0/8 | 0/33 | 20.0% | 125/243 = 51.4% |
| Exact duplicate rate | 0 | 0 | 0 | 0 | 0 | 0% | 0/243 |

Unit-discovery precision/recall/F1 and type-classification accuracy are unavailable: the jobportal graph and case sheet conflict, and no source-normalized independent agent inventory is persisted. Computing them from a graph would use agent output as ground truth. Failure-category accuracy is 0/243 as a usable signal: parser/import/mock/template causes are not consistently classified. No real repository bug is evidenced; agent-caused invalid/failing generation is 243/243.

## Confidence calibration

Strict correctness is zero for all cases. Confidence is a binary runner-status proxy: 88 cases at 100 and 155 at zero.

| Bin | Count | Mean prediction | Strict-correct rate | Gap |
|---|---:|---:|---:|---:|
| 0–19 | 155 | 0% | 0% | 0 pp |
| 20–39 | 0 | — | — | — |
| 40–59 | 0 | — | — | — |
| 60–79 | 0 | — | — | — |
| 80–100 | 88 | 100% | 0% | +100 pp |

MAE is 38.7 points using correct=100, partial=50, incorrect=0: (125x28 + 118x50)/243. Brier score is 0.362 using correct-only binary labels: 88/243. Overconfidence is 88/88 high-confidence cases; underconfidence is zero because no correct meaningful low-confidence case exists.

## Prioritized recommendations

1. Bind all artifacts to a ZIP hash, normalized root, and run ID; reject foreign target paths.
2. Require an AST/source-span-backed expected value, DOM role/text, callback, payload, or response body before emitting a case.
3. Replace body-truthiness, defined-symbol, and less-than-500 templates with behaviour assertions.
4. Select framework/extension from project configuration and parse the actual generated test before reporting static success.
5. Derive mocks from real export shapes and component props; generate fixtures for required props.
6. Separate generator, import, fixture, environment, and verified source-bug root causes; do not propose source edits without a reproducer.
7. Calibrate confidence against semantic correctness; a runner pass alone must never yield 100.
