## META
name: todo-cli | stack: python 3.12 | runtime: cli | entrypoint: todo.py | smoke_command: list

## OBJECTIVE
CLI that adds and lists todos stored in todos.json.

## END_CRITERIA
- `python todo.py add "x"` writes valid json
- `python todo.py list` prints stored todos
- pytest suite passes

## MILESTONES
- {id: m1, title: add command, acceptance_criteria: ["add writes valid json"], max_attempts: 3}
- {id: m2, title: list command, acceptance_criteria: ["list prints stored todos"], max_attempts: 3}

## BUDGET
token_cap: 500000
llm_call_cap: 50

## OUT_OF_SCOPE
no database, no web UI
