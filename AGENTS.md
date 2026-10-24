# Development rules

- Python 3.11+ for services, runtime adapters, connectors, and domain logic.
- Vue 3 + TypeScript + Element Plus for frontend; browser code is not Python.
- Generic packages must not import Guanlan domain code.
- SDK-specific types stay inside runtime adapters; channel-specific types stay inside connectors.
- Never commit credentials, stock data dumps, or third-party source repositories.
- Distinguish planned integrations from implemented functionality.
- Run pytest and the frontend production build for relevant changes.
