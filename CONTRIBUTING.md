# Contributing to Mayday

## Development Workflow

1. **Branch from `main`** for new features, `deployment` for production fixes
2. **Keep changes focused** — one feature/fix per branch
3. **Test before committing** — run both backend and frontend
4. **Write meaningful commit messages** — describe *what* and *why*

## Setup

```bash
git clone https://github.com/AjayAnandx/Project-Mayday.git
cd Project-Mayday
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env   # Fill in your API keys
npm run dev            # Starts both servers
```

## Code Standards

### Backend (Python)

- Use type hints on all function signatures
- Thread-safe data access (use `threading.Lock` or `RLock`)
- New tool functions go in `backend/functions/`, registered in `function_registry.py`
- API routes go in `backend/api/`, wired in `backend/main.py`
- Config loading through `backend/core/config.py` (never hardcode secrets)

### Frontend (TypeScript + React)

- **No `dangerouslySetInnerHTML`** — use `react-markdown` for rendered content
- Tailwind CSS with the defined black+green palette (see `tailwind.config.js`)
- Icons via `lucide-react`, animations via `motion` (framer-motion)
- Components in `components/` by domain, shared primitives in `components/ui/`
- Hooks in `hooks/`, service layer in `services/`, types in `types/`
- New components should match existing patterns (styled-components not used)

### Testing

- Python tests use `pytest` — run with `python -m pytest`
- Frontend tests (if any) use Vitest
- New features should include tests for:
  - CRUD operations
  - Search/query edge cases
  - Concurrent access (if relevant)

## Adding a New Tool

1. Implement the function in `backend/functions/` (or appropriate module)
2. Add the tool definition + dispatch entry in `backend/assistant/function_registry.py`
3. Add tool name to `CORE_TOOL_NAMES` set if always-on
4. The tool will be automatically available to the LLM

## Adding an MCP Server

1. Add server config under `mcp.servers` in `config.yaml`
2. Set `lazy: true` unless it should always connect
3. Add required env vars (if any) to the server's `env:` section
4. The `MCPManager` handles stdio lifecycle per WebSocket session

## Security Checklist

Before committing, verify:
- [ ] No API keys or tokens in code (they go in `.env`)
- [ ] No `console.log` / `print()` of sensitive data
- [ ] `.env` changes are reflected in `.env.example`
- [ ] New dependencies added to `requirements.txt` or `package.json`
- [ ] File permissions are restricted for sensitive files

## Git Conventions

- `main` — stable, deployable
- `deployment` — production branch
- `feat/*` — new features
- `fix/*` — bug fixes
- Rebase onto `main` before opening a PR
- No force-push to shared branches
