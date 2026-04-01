# SKILL: React Conventions

Apply every rule in this file to all React code generation and review tasks.
No exceptions unless the task brief explicitly overrides a specific rule and states a reason.

---

## Component rules

- **Functional components only.** No class components, ever.
- Every component lives in its own file: `src/components/<FeatureName>/<ComponentName>.tsx`.
- Export components as named exports, not default exports, so refactoring tools track them correctly.
- Component files must not exceed one component per file. Co-locate sub-components only if they are not reused elsewhere.

---

## UIX primitives — never raw Tailwind on non-primitive elements

This codebase uses a UIX primitive library. Use these components for all layout and structure.
Never apply Tailwind utility classes directly to `div`, `span`, or semantic HTML elements.

| Primitive | Use for |
|-----------|---------|
| `<Stack>` | Vertical layout — replaces `flex-col` divs |
| `<Inline>` | Horizontal layout — replaces `flex-row` divs |
| `<PageShell>` | Top-level page wrapper with standard padding and max-width |
| `<AsyncBoundary>` | Wraps any component that fetches data; handles loading and error states |

```tsx
// correct
import { PageShell, Stack, Inline } from '@/uix/primitives';

export function ItemListPage() {
  return (
    <PageShell title="Items">
      <Stack gap="md">
        <Inline justify="between">
          <h1>All Items</h1>
          <AddItemButton />
        </Inline>
        <AsyncBoundary>
          <ItemList />
        </AsyncBoundary>
      </Stack>
    </PageShell>
  );
}
```

```tsx
// wrong — raw Tailwind on structural divs
<div className="flex flex-col gap-4 p-6 max-w-screen-xl">
```

---

## Data fetching — RTK Query

All server state is managed through RTK Query endpoints defined in `apiSlice.ts`.
Do not use `useEffect` + `fetch`, `axios`, or `React Query` (`@tanstack/react-query`).

```ts
// apiSlice.ts
import { createApi, fetchBaseQuery } from '@reduxjs/toolkit/query/react';
import type { Item, ItemRequest } from './types';

export const itemApi = createApi({
  reducerPath: 'itemApi',
  baseQuery: fetchBaseQuery({ baseUrl: '/api/v1' }),
  tagTypes: ['Item'],
  endpoints: (builder) => ({
    listItems: builder.query<Item[], void>({
      query: () => '/items',
      providesTags: ['Item'],
    }),
    createItem: builder.mutation<Item, ItemRequest>({
      query: (body) => ({ url: '/items', method: 'POST', body }),
      invalidatesTags: ['Item'],
    }),
  }),
});

export const { useListItemsQuery, useCreateItemMutation } = itemApi;
```

Rules:
- Every API endpoint is defined in `apiSlice.ts` for the feature, not scattered across components.
- Use `providesTags` / `invalidatesTags` for cache invalidation — never call `refetch()` manually unless reacting to a user action.
- Never call an RTK Query hook conditionally. Use the `skip` option instead.

```tsx
// correct — conditional skip
const { data } = useListItemsQuery(undefined, { skip: !isAuthenticated });

// wrong — conditional hook call
if (isAuthenticated) {
  const { data } = useListItemsQuery();   // Rules of Hooks violation
}
```

---

## AsyncBoundary — mandatory for data-fetching components

Any component that calls an RTK Query hook must be wrapped in `<AsyncBoundary>` by its parent.
Never render loading spinners or error states inline inside the data-fetching component.

```tsx
// parent (page or layout component)
<AsyncBoundary>
  <ItemList />       {/* ItemList calls useListItemsQuery internally */}
</AsyncBoundary>

// ItemList — clean, no loading/error handling
export function ItemList() {
  const { data: items } = useListItemsQuery();   // data is always defined here
  return (
    <Stack>
      {items.map((item) => <ItemRow key={item.id} item={item} />)}
    </Stack>
  );
}
```

---

## shadcn/ui

Use shadcn/ui components for all interactive UI elements (buttons, dialogs, inputs, tables, etc.).
Do not build custom interactive components from scratch if a shadcn equivalent exists.

```tsx
import { Button }   from '@/components/ui/button';
import { Input }    from '@/components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
```

Customise via `className` props using Tailwind — but only on shadcn components, never on raw HTML.

---

## TypeScript

- All props are typed with a `interface <ComponentName>Props { ... }` declared in the same file or in `types.ts`.
- Never use `any`. Use `unknown` and narrow with type guards where the type is genuinely dynamic.
- Prefer `type` aliases for union types and `interface` for object shapes.
- All RTK Query types are declared in `types.ts` alongside the slice.

```ts
// types.ts
export interface Item {
  id: number;
  name: string;
  createdAt: string;   // ISO-8601 string from API
}

export interface ItemRequest {
  name: string;
}
```

---

## State management

| State type | Where it lives |
|------------|----------------|
| Server state (API data) | RTK Query cache — never duplicate into `useState` |
| Global UI state (theme, auth, modals) | Redux slice |
| Local UI state (form input, open/closed) | `useState` in the component |

- Do not lift state higher than necessary.
- Never store derived data in state — compute it from the source.
- Avoid prop drilling deeper than 2 levels. Use a context or Redux slice instead.

---

## File naming

| File | Convention |
|------|-----------|
| Component | `PascalCase.tsx` |
| Hook | `use<Name>.ts` |
| Slice / API | `<feature>Slice.ts` / `<feature>ApiSlice.ts` |
| Types | `types.ts` (co-located with slice) |
| Test | `<ComponentName>.test.tsx` |

---

## Testing

- Every component gets a co-located `<ComponentName>.test.tsx`.
- Use React Testing Library (`@testing-library/react`). Never test implementation details (state shape, internal methods).
- Wrap the component under test in the Redux `<Provider>` and any required context providers using a shared `renderWithProviders` utility.
- Mock RTK Query endpoints with `msw` (Mock Service Worker) — never mock the hook directly.
- Every test that renders a data-fetching component must test both the loading state and the populated state.
