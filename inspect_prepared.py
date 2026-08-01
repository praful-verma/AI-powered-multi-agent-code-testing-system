from pathlib import Path
from multiagent_testing.adapters.mern import MERNAdapter

adapter = MERNAdapter()
paths = [
    Path(r'C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\src\api.generated.TC-0006_createTodo.test.js'),
    Path(r'C:\Users\vpraf\OneDrive\Desktop\mern-todo-app\mern-todo-app\frontend\src\components\TodoForm.generated.TC-0017_handleSubmit.test.jsx'),
]
for p in paths:
    code = p.read_text(encoding='utf-8')
    prepared = adapter.prepare_test_code(code, str(p))
    print('---', p.name, '---')
    print(prepared)
    print()
