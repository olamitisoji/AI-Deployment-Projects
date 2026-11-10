"""Compile the initial PostgreSQL migration without loading settings or secrets."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from echo.database import Base  # noqa: E402 -- metadata only; no Settings/.env loading.


def render_schema() -> str:
    dialect = postgresql.dialect()
    preparer = dialect.identifier_preparer
    tables = list(Base.metadata.sorted_tables)

    def compile_ddl(statement) -> str:
        compiled = statement.compile(dialect=dialect, schema_translate_map={None: "public"}, render_schema_translate=True)
        return "\n".join(line.rstrip() for line in str(compiled).strip().splitlines()) + ";"

    qualified = [f"public.{preparer.quote(table.name)}" for table in tables]
    table_list = ", ".join(qualified)
    parts = [
        "-- Generated from echo.database.Base.metadata by scripts/export_postgres_schema.py.",
        "-- Python ORM defaults are intentionally not PostgreSQL server defaults.",
        "-- Empty Echo schema only; no participant, project, or study records are inserted.",
        "BEGIN;",
    ]
    for table in tables:
        parts.append(compile_ddl(CreateTable(table)))
        for index in sorted(table.indexes, key=lambda item: item.name):
            parts.append(compile_ddl(CreateIndex(index)))
    parts.append("-- Table creation and browser-role denial become visible in one commit.")
    parts.extend(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY;" for name in qualified)
    parts.append(f"REVOKE ALL PRIVILEGES ON TABLE {table_list} FROM PUBLIC;")
    conditional = ["DO $echo_access$", "BEGIN"]
    for role in ("anon", "authenticated"):
        conditional.extend([
            f"    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{role}') THEN",
            f"        REVOKE ALL PRIVILEGES ON TABLE {table_list} FROM {preparer.quote(role)};",
            "    END IF;",
        ])
    conditional.extend(["END;", "$echo_access$;"])
    parts.append("\n".join(conditional))
    parts.append("COMMIT;")
    return "\n\n".join(parts) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "supabase/migrations/202611100001_echo_initial.sql")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_schema(), encoding="utf-8")
    print(f"PostgreSQL schema exported to {args.output}")


if __name__ == "__main__":
    main()
