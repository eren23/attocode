# Example Project Rules

These rules guide the agent's behavior for this project.

## Code Style
- Use TypeScript strict mode
- Prefer explicit types over inference for public APIs
- Keep files focused — prefer new files over growing existing ones

## Testing
- Write tests for new functionality
- Run `npm test` after making changes
- Follow existing test patterns in `tests/`

## Git
- Write clear, concise commit messages
- One logical change per commit
- Don't commit generated files (dist/, coverage/)
