"""The barrier schema: what is held back, when it was declared, and what released it.

THIS REPOSITORY OWNS THIS SCHEMA. QUALMZ adopts it rather than inventing a second one, so the
shape here is a public contract and not an implementation detail.

WHY THE HOLDOUT IS DATA AND NOT A CONSTANT. A held out range written as a number in the source
is a range that changes in a commit, which is a change that looks like every other change. As a
declared row it carries the date it was declared and the reason, and releasing it takes a second
row saying who released it and why. That is the difference between a boundary somebody can move
quietly and one that leaves a record.

A PROMOTION IS A ROW, NOT A DELETION. Releasing a window never removes the window: it adds a
promotion referring to it. The history of what was held back and when it stopped being held back
is therefore additive, and a reader can reconstruct what any given run was allowed to see.

THE ROLE SCOPED GRANT. The retrieval role is granted select on the documents and nothing else.
It cannot read these two tables. That is deliberate: a role that can read the holdout definition
can compute the boundary exactly, and a barrier a caller can measure is a barrier a caller can
work around. The definitions are public in this file, which is a different thing: the rules are
published, and the role's own queries cannot reach them.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The two tables, in the dialect both stores accept. This is the artefact QUALMZ adopts.
SCHEMA_SQL = """
create table if not exists holdout_window (
    name             text primary key,
    from_period_rank integer not null,
    to_period_rank   integer,
    declared_on      text not null,
    reason           text not null
);
create table if not exists promotion (
    holdout_name text not null references holdout_window(name),
    promoted_on  text not null,
    promoted_by  text not null,
    reason       text not null,
    primary key (holdout_name, promoted_on)
);
"""

#: Granted to the retrieval role, and this is the whole of it. No select on the tables above.
GRANT_SQL = "grant select on notes to {role}"


def period_rank(period: str) -> int:
    """`2024-Q2` and `2024-07` on one integer scale, by the last month each covers."""
    year, rest = period.split("-", 1)
    month = int(rest[1:]) * 3 if rest.startswith("Q") else int(rest)
    return int(year) * 12 + month


@dataclass(frozen=True)
class HoldoutWindow:
    """A range of observation periods that is not answered, and why.

    `to_period` of None means open ended, which is the usual shape: everything from here on is
    held back, because the recent end of a series is where an evaluation set is worth having.
    """

    name: str
    from_period: str
    to_period: str | None
    declared_on: str
    reason: str

    def covers(self, period: str) -> bool:
        rank = period_rank(period)
        if rank < period_rank(self.from_period):
            return False
        return self.to_period is None or rank <= period_rank(self.to_period)


@dataclass(frozen=True)
class Promotion:
    """A deliberate release, by a named person, on a date, with a reason."""

    holdout_name: str
    promoted_on: str
    promoted_by: str
    reason: str


WINDOWS: tuple[HoldoutWindow, ...] = (
    HoldoutWindow(
        name="recent-tail",
        from_period="2025-07",
        to_period=None,
        declared_on="2026-08-25",
        reason=(
            "The recent end of every series, held back so a scoring run cannot be tuned against "
            "the periods a reader is most likely to ask about."
        ),
    ),
)

#: Empty on purpose, and the empty tuple is the point: nothing has been released.
PROMOTIONS: tuple[Promotion, ...] = ()


def active_windows() -> tuple[HoldoutWindow, ...]:
    released = {promotion.holdout_name for promotion in PROMOTIONS}
    return tuple(window for window in WINDOWS if window.name not in released)


def is_held_out(period: str) -> bool:
    return any(window.covers(period) for window in active_windows())


def earliest_held_out_rank() -> int:
    """The lowest rank any active window covers, for the index predicates that need a number.

    A partial index predicate is a single comparison, so it can express "everything from here
    on" and cannot express a window with an end to it. Rather than returning a number that
    would be quietly wrong the moment somebody declares a closed window, this refuses. The
    index is the mechanism that makes forbidden rows unreachable, and a mechanism that silently
    covers the wrong rows is worse than one that stops.
    """
    windows = active_windows()
    closed = [window.name for window in windows if window.to_period is not None]
    if closed:
        raise ValueError(
            f"window(s) {closed} have an end date, and a single index predicate cannot express "
            "a range with two ends. Give the index both bounds, or split it, before relying on "
            "this number."
        )
    return min((period_rank(window.from_period) for window in windows), default=1 << 30)


def _quote(text: str) -> str:
    """Double any apostrophe, because these reasons are prose and prose has apostrophes in it."""
    return text.replace("'", "''")


def install(execute: object, role: str | None = None) -> list[str]:
    """The statements that materialise this schema, returned rather than run.

    Returned so a caller can apply them to SQLite or to PostgreSQL, and so a test can read what
    would be run without a server. The grant is included only when a role is named, because the
    oracle's store has no roles and pretending otherwise would put a statement in the list that
    only one of the two stores can execute.
    """
    statements = [line for line in SCHEMA_SQL.split(";") if line.strip()]
    # Every insert is an upsert. Applying this schema twice has to be the same as applying it
    # once, or the second deployment fails on a primary key and the first person to see it is
    # whoever runs it against a database that already exists. The declaration in this file
    # wins on conflict, because this file is the source of truth and the table is a copy of it.
    for window in WINDOWS:
        statements.append(
            "insert into holdout_window (name, from_period_rank, to_period_rank, declared_on, "
            f"reason) values ('{window.name}', {period_rank(window.from_period)}, "
            f"{period_rank(window.to_period) if window.to_period else 'null'}, "
            f"'{window.declared_on}', '{_quote(window.reason)}') "
            "on conflict (name) do update set "
            "from_period_rank = excluded.from_period_rank, "
            "to_period_rank = excluded.to_period_rank, "
            "declared_on = excluded.declared_on, reason = excluded.reason"
        )
    for promotion in PROMOTIONS:
        statements.append(
            "insert into promotion (holdout_name, promoted_on, promoted_by, reason) values "
            f"('{promotion.holdout_name}', '{promotion.promoted_on}', "
            f"'{promotion.promoted_by}', '{_quote(promotion.reason)}') "
            "on conflict (holdout_name, promoted_on) do update set "
            "promoted_by = excluded.promoted_by, reason = excluded.reason"
        )
    if role:
        statements.append(GRANT_SQL.format(role=role))
    return statements
