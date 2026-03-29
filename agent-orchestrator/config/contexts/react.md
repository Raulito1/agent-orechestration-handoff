# React Conventions

<!-- TODO: Copy full conventions from .roo/react.md -->

## Components
- Use functional components with hooks — no class components.
- Every component lives in its own file under `src/components/`.
- Never use raw Tailwind classes directly; use UIX primitive components only.

## State Management
- Prefer React Query for server state; use local state (`useState`) for UI-only state.
- Avoid prop drilling deeper than 2 levels — lift state or use context.

## Typing
- All props must be typed with TypeScript interfaces.
- Never use `any` — use `unknown` and narrow where needed.

## Testing
- Every component gets a co-located `*.test.tsx` file.
- Use React Testing Library; never test implementation details.
