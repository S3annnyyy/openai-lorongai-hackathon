# Demo Task Service (Web API + Frontend)

This project is a lightweight web API with a browser UI for managing tasks.  
It is designed to be easy for both:
- static code analysis (code-autopsy)
- iterative simulation (`simulate_agent.py`) on backend+frontend changes.

## Run the app

```bash
cd demo-project
python -m task_service.main
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## API endpoints

- `GET /api/tasks?completed=<true|false>` - list tasks (optionally filtered)
- `POST /api/tasks` - create a task
- `GET /api/tasks/{task_id}` - get one task
- `PATCH /api/tasks/{task_id}` - update title/priority/completed
- `DELETE /api/tasks/{task_id}` - remove a task
- `GET /api/report` - summary metrics

## Tests

```bash
cd demo-project
python -m unittest discover -s tests
```

## Feature ideas for simulation

See `features.example.txt`.

