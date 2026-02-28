# openai-lorongai-hackathon

## Simulation agent: 3-month red/blue security simulation

Use `simulate_agent.py` with a context file for security-focused iterative runs:

```bash
python simulate_agent.py \
  --source demo-project \
  --workspace .simulations \
  --run-name smoke-security-sprint \
  --simulation-weeks 12 \
  --weeks-per-iteration 2 \
  --agent-context simulation_context.md \
  --features-file demo-project/features.example.txt \
  --max-iterations 6 \
  --iteration-command "python -m pip install -e . --disable-pip-version-check --no-input && python -m unittest discover -s tests"
``` 

### Run directly against a GitHub repo

```bash
python simulate_agent.py \
  --source-url https://github.com/openai-lorongai-hackathon/sample \
  --source-ref main \
  --workspace .simulations \
  --run-name smoke-security-sprint \
  --simulation-weeks 12 \
  --weeks-per-iteration 2 \
  --agent-context simulation_context.md \
  --features-file features.example.txt \
  --max-iterations 6 \
  --iteration-command "python -m pip install -e . --disable-pip-version-check --no-input && python -m unittest discover -s tests"
```

Use `org/repo` shorthand for GitHub URLs if you prefer:

```bash
python simulate_agent.py \
  --source-url openai-lorongai-hackathon/sample \
  --source-subdir demo-project \
  --source-ref main
```

If needed, you can install dependencies explicitly before running anything:

```bash
cd demo-project
python -m pip install -r requirements.txt --disable-pip-version-check --no-input
python -m unittest discover -s tests
```

Each iteration now emits:
- standard checkpoint artifacts
- `.simulation/agent-notes/<iter>-<slug>.{red-team,blue-team,refactorer,historian}.md`
- `simulation_report.md` with per-agent markdown summaries and timeline.
