# Failure Report

## TC-0005 - frontend/src/App.jsx

- Unit: App
- Status: Fail
- Score: 0
- Failure category: Mock
- Coverage percent: Not collected
- Confidence score: 
- Confidence details: fail result categorized as Mock; static validation passed; coverage was not collected

Output:

```text
Error: [vitest] No "default" export is defined on the "./components/TodoForm.jsx" mock. Did you forget to return it from "vi.mock"?
If you need to partially mock a module, you can use "importOriginal" helper inside:

    at VitestMocker.createError (file:///C:/Users/vpraf/OneDrive/Desktop/mern-todo-app/mern-todo-app/frontend/node_modules/vitest/dist/chunks/execute.2pr0rHgK.js:321:19)
    at Object.get (file:///C:/Users/vpraf/OneDrive/Desktop/mern-todo-app/mern-todo-app/frontend/node_modules/vitest/dist/chunks/execute.2pr0rHgK.js:389:22)
    at App (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\src\App.jsx:36:8)
    at renderWithHooks (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:15486:18)
    at mountIndeterminateComponent (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:20103:13)
    at beginWork (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:21626:16)
    at beginWork$1 (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:27465:14)
    at performUnitOfWork (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:26599:12)
    at workLoopSync (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:26505:5)
    at renderRootSync (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:26473:7)
```

## TC-0007 - frontend/src/components/TodoItem.jsx

- Unit: TodoItem
- Status: Fail
- Score: 0
- Failure category: Runtime
- Coverage percent: Not collected
- Confidence score: 
- Confidence details: fail result categorized as Runtime; static validation passed; coverage was not collected

Output:

```text
TypeError: Cannot read properties of undefined (reading 'completed')
    at TodoItem (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\src\components\TodoItem.jsx:5:25)
    at renderWithHooks (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:15486:18)
    at mountIndeterminateComponent (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:20103:13)
    at beginWork (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:21626:16)
    at beginWork$1 (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:27465:14)
    at performUnitOfWork (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:26599:12)
    at workLoopSync (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:26505:5)
    at renderRootSync (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:26473:7)
    at recoverFromConcurrentError (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:25889:20)
    at performConcurrentWorkOnRoot (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:25789:22)
```

## TC-0008 - frontend/src/components/TodoList.jsx

- Unit: TodoList
- Status: Fail
- Score: 0
- Failure category: Runtime
- Coverage percent: Not collected
- Confidence score: 
- Confidence details: fail result categorized as Runtime; static validation passed; coverage was not collected

Output:

```text
TypeError: Cannot read properties of undefined (reading 'length')
    at TodoList (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\src\components\TodoList.jsx:4:13)
    at renderWithHooks (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:15486:18)
    at mountIndeterminateComponent (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:20103:13)
    at beginWork (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:21626:16)
    at beginWork$1 (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:27465:14)
    at performUnitOfWork (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:26599:12)
    at workLoopSync (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:26505:5)
    at renderRootSync (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:26473:7)
    at recoverFromConcurrentError (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:25889:20)
    at performConcurrentWorkOnRoot (C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\node_modules\react-dom\cjs\react-dom.development.js:25789:22)
```
