Layered architecture migration

Target layout under src/github_bot:
- app/: startup, shutdown and composition root
- core/: settings, logging and constants
- domain/: framework-independent entities, policies and errors
- application/: use cases, services and ports
- infrastructure/: SQLite, GitHub HTTP, Telegram and filesystem adapters
- presentation/: aiogram routers, keyboards, filters and middleware
- workers/: background job runners
- tests/: unit, integration and end-to-end tests

Dependency rules
1. Presentation calls application services; it must not run SQL or download files.
2. Application coordinates use cases and depends on domain types and ports, not concrete adapters.
3. Domain must not import aiogram, SQLite, HTTP clients, environment variables or filesystem APIs.
4. Infrastructure implements application ports.
5. The app package is the composition root and injects dependencies.
6. Workers orchestrate background work and call application services.
7. Load settings once at startup and pass them to components that need them.

Migration policy
- Keep the current entry point working while extracting one feature at a time.
- Preserve the current SQLite schema and data; use explicit migrations for schema changes.
- Do not mix structural refactoring with new user-facing features.
- Add tests before changing behavior and compare old/new behavior.
- Move the runtime to src/ only when imports and packaging are changed together.
- Never commit .env, tokens, runtime databases, downloads, caches or virtual environments.

Feature ownership
- Search and repository metadata: GitHub adapter + repository application service.
- Releases/assets: release application service.
- Queue lifecycle: domain rules + job repository port + database adapter + queue service.
- Telegram callbacks/messages: presentation routers.
- Downloading and Telegram upload: infrastructure adapters coordinated by a use case.
