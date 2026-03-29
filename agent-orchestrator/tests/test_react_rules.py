"""Tests for React convention guard rules.

Each rule has a passing case (no violations) and a failing case (violations found).
Rules are pure functions — no file system or I/O needed.
"""
import pytest
from guards.rules.react_rules import (
    check_missing_async_boundary,
    check_no_raw_tailwind,
    check_todo_fixme,
)


# ---------------------------------------------------------------------------
# check_no_raw_tailwind
# ---------------------------------------------------------------------------


def test_no_raw_tailwind_passes_uix_primitive():
    content = """\
export function UserCard() {
    return (
        <Stack className="flex gap-4 p-2">
            <p>Hello</p>
        </Stack>
    );
}
"""
    result = check_no_raw_tailwind("src/components/UserCard.tsx", content)
    assert result == []


def test_no_raw_tailwind_passes_no_classname():
    content = """\
export function UserCard() {
    return <div><p>Hello</p></div>;
}
"""
    result = check_no_raw_tailwind("src/components/UserCard.tsx", content)
    assert result == []


def test_no_raw_tailwind_fails_raw_class_on_div():
    content = """\
export function UserCard() {
    return (
        <div className="flex gap-4 p-2">
            <p>Hello</p>
        </div>
    );
}
"""
    result = check_no_raw_tailwind("src/components/UserCard.tsx", content)
    assert len(result) == 1
    assert result[0].rule_id == "no-raw-tailwind"
    assert result[0].severity == "WARNING"
    assert result[0].line_number == 3


def test_no_raw_tailwind_fails_raw_class_on_custom_component():
    content = """\
export function UserCard() {
    return <MyBox className="bg-white border-2 rounded">content</MyBox>;
}
"""
    result = check_no_raw_tailwind("src/components/UserCard.tsx", content)
    assert len(result) == 1
    assert result[0].rule_id == "no-raw-tailwind"


def test_no_raw_tailwind_ignores_non_react_files():
    content = '<div className="flex gap-4">content</div>'
    result = check_no_raw_tailwind("src/styles.css", content)
    assert result == []


def test_no_raw_tailwind_ignores_all_uix_primitives():
    content = """\
export function Layout() {
    return (
        <PageShell className="p-4">
            <Inline className="gap-2">
                <Stack className="flex-col">
                    <AsyncBoundary className="w-full">
                        <p>content</p>
                    </AsyncBoundary>
                </Stack>
            </Inline>
        </PageShell>
    );
}
"""
    result = check_no_raw_tailwind("src/components/Layout.tsx", content)
    assert result == []


# ---------------------------------------------------------------------------
# check_missing_async_boundary
# ---------------------------------------------------------------------------


def test_missing_async_boundary_passes_with_boundary():
    content = """\
export function UserList() {
    const { data } = useGetUsersQuery();
    return (
        <AsyncBoundary>
            <ul>{data?.map(u => <li key={u.id}>{u.name}</li>)}</ul>
        </AsyncBoundary>
    );
}
"""
    result = check_missing_async_boundary("src/components/UserList.tsx", content)
    assert result == []


def test_missing_async_boundary_fails_missing_boundary():
    content = """\
export function UserList() {
    const { data } = useGetUsersQuery();
    return <ul>{data?.map(u => <li key={u.id}>{u.name}</li>)}</ul>;
}
"""
    result = check_missing_async_boundary("src/components/UserList.tsx", content)
    assert len(result) == 1
    assert result[0].rule_id == "missing-async-boundary"
    assert result[0].severity == "WARNING"


def test_missing_async_boundary_passes_no_rtk_hooks():
    content = """\
export function StaticCard() {
    return <div>Hello World</div>;
}
"""
    result = check_missing_async_boundary("src/components/StaticCard.tsx", content)
    assert result == []


def test_missing_async_boundary_detects_mutation_hook():
    content = """\
export function CreateUser() {
    const [createUser] = usePostUserMutation();
    return <button onClick={() => createUser({})}>Create</button>;
}
"""
    result = check_missing_async_boundary("src/components/CreateUser.tsx", content)
    assert len(result) == 1
    assert result[0].rule_id == "missing-async-boundary"


def test_missing_async_boundary_ignores_non_react_files():
    content = "const { data } = useGetUsersQuery();"
    result = check_missing_async_boundary("src/hooks/useUsers.ts", content)
    assert result == []


# ---------------------------------------------------------------------------
# check_todo_fixme
# ---------------------------------------------------------------------------


def test_todo_fixme_passes_clean():
    content = """\
export function UserCard() {
    return <div>Hello</div>;
}
"""
    result = check_todo_fixme("src/components/UserCard.tsx", content)
    assert result == []


def test_todo_fixme_fails_todo_comment():
    content = """\
export function UserCard() {
    // TODO: add loading state
    return <div>Hello</div>;
}
"""
    result = check_todo_fixme("src/components/UserCard.tsx", content)
    assert len(result) == 1
    assert result[0].rule_id == "todo-fixme-in-new-code"
    assert result[0].severity == "WARNING"
    assert result[0].line_number == 2


def test_todo_fixme_fails_fixme_comment():
    content = """\
export function UserCard() {
    // FIXME: broken on mobile
    return <div>Hello</div>;
}
"""
    result = check_todo_fixme("src/components/UserCard.tsx", content)
    assert len(result) == 1


def test_todo_fixme_works_on_jsx_files():
    content = "// TODO: refactor\nreturn <div />;"
    result = check_todo_fixme("src/components/Old.jsx", content)
    assert len(result) == 1


def test_todo_fixme_ignores_non_react_files():
    content = "// TODO: fix this"
    result = check_todo_fixme("src/utils/helpers.ts", content)
    assert result == []
