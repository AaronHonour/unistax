"""PostgreSQL fixtures for data source tests.

Uses ``AGENT_API_TEST_DATABASE_URL`` when set (CI), otherwise starts an embedded
server with ``pgserver`` if installed, otherwise the tests are skipped.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

READER_PASSWORD = "reader-pw-" + secrets.token_hex(4)


def _asyncpg(url: str) -> str:
    return make_url(url).set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def pg_admin_url() -> Iterator[str]:
    """URL of a superuser connection to a scratch PostgreSQL."""
    external = os.environ.get("AGENT_API_TEST_DATABASE_URL")
    if external:
        yield _asyncpg(external)
        return
    try:
        import pgserver
    except ImportError:
        pytest.skip("needs PostgreSQL: set AGENT_API_TEST_DATABASE_URL or install pgserver")
    server = pgserver.get_server(tempfile.mkdtemp())
    host = server.get_uri().split("host=")[1]
    yield f"postgresql+asyncpg://postgres@/postgres?host={host}"
    server.cleanup()


async def _admin(url: str, statements: list[str]) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))
    finally:
        await engine.dispose()


@dataclass
class Warehouse:
    """A seeded schema plus the roles and URLs to reach it."""

    admin_url: str
    reader_url: str
    writer_url: str
    schema: str
    other_schema: str
    reader: str
    writer: str

    def url_for(self, role: str, password: str) -> str:
        return (
            make_url(self.admin_url)
            .set(username=role, password=password)
            .render_as_string(hide_password=False)
        )


def _seed_sql(s: str, o: str) -> list[str]:
    statements = [
        f"CREATE SCHEMA {s}",
        f"CREATE SCHEMA {o}",
        f"""CREATE TABLE {s}.customers (
              id bigserial PRIMARY KEY, email text NOT NULL, full_name text, phone text,
              notes text, ssn text, card text, ip inet, signup_ts timestamptz,
              legacy text, score int)""",
        f"COMMENT ON TABLE {s}.customers IS 'Customer master data'",
        f"COMMENT ON COLUMN {s}.customers.email IS 'Primary contact address'",
        f"""INSERT INTO {s}.customers (email, full_name, phone, notes, ssn, card, ip, signup_ts, score)
            SELECT 'user' || g || '@example.com', 'Person ' || g,
                   '+44 20 7946 ' || lpad(g::text, 4, '0'),
                   'note ' || g,
                   lpad((100 + g)::text, 3, '0') || '-45-' || lpad((6000 + g)::text, 4, '0'),
                   (ARRAY['4111111111111111','5555555555554444','378282246310005'])[1 + g % 3],
                   ('10.0.0.' || (1 + g % 250))::inet,
                   now() - (g || ' days')::interval,
                   g
              FROM generate_series(1, 60) g""",
        f"""CREATE TABLE {s}.orders (
              id bigserial PRIMARY KEY, customer_id bigint NOT NULL REFERENCES {s}.customers(id),
              amount numeric(12,2), status text, created_at timestamptz DEFAULT now())""",
        f"""INSERT INTO {s}.orders (customer_id, amount, status)
            SELECT 1 + g % 60, g * 1.5, CASE WHEN g % 10 = 0 THEN NULL ELSE 'paid' END
              FROM generate_series(1, 200) g""",
        f"""CREATE TABLE {s}.order_items (
              order_id bigint NOT NULL REFERENCES {s}.orders(id), line int NOT NULL, sku text,
              PRIMARY KEY (order_id, line))""",
        f"CREATE INDEX orders_status_idx ON {s}.orders (status)",
        f"CREATE VIEW {s}.big_orders AS SELECT * FROM {s}.orders WHERE amount > 100",
        f"CREATE TABLE {s}.empty_table (id int)",
        f'CREATE TABLE {s}."Weird ""Name:x" ("odd \\:col" text, "100%" int, normal int)',
        f"""INSERT INTO {s}."Weird ""Name:x" VALUES ('a', 1, 1), ('b', 2, 2)""",
        # data with known defects, for quality checks
        f"CREATE TABLE {s}.orphans (id serial PRIMARY KEY, customer_id bigint)",
        f"INSERT INTO {s}.orphans (customer_id) VALUES (1), (2), (999), (1000), (NULL)",
        f"ALTER TABLE {s}.orphans ADD CONSTRAINT orphans_fk FOREIGN KEY (customer_id) "
        f"REFERENCES {s}.customers(id) NOT VALID",
        f"CREATE TABLE {s}.dups (code text, label text)",
        f"INSERT INTO {s}.dups VALUES ('a','1'), ('a','2'), ('b','3'), ('c','4'), ('c','5'), ('c','6'), (NULL,'7'), (NULL,'8')",
        f"CREATE TABLE {s}.events (id serial PRIMARY KEY, happened_at timestamptz)",
        f"INSERT INTO {s}.events (happened_at) VALUES (now() - interval '3 days'), (now() - interval '5 days')",
        f"CREATE TABLE {s}.fresh_events (id serial PRIMARY KEY, happened_at timestamptz)",
        f"INSERT INTO {s}.fresh_events (happened_at) VALUES (now() - interval '5 minutes')",
        f"CREATE TABLE {s}.strict_table (id int PRIMARY KEY, name text NOT NULL)",
        f"INSERT INTO {s}.strict_table VALUES (1, 'a'), (2, 'b')",
        f"CREATE TABLE {s}.ghost_events (happened_at timestamptz)",
        f"INSERT INTO {s}.ghost_events VALUES (NULL), (NULL)",
        f"CREATE TABLE {s}.long_text (body text)",
        f"INSERT INTO {s}.long_text SELECT repeat('x', 5000) FROM generate_series(1, 2)",
        # a table in another schema that agents must never reach
        f"CREATE TABLE {o}.secrets (id int, value text)",
        f"INSERT INTO {o}.secrets VALUES (1, 'top-secret-value')",
        # a table the reader role is NOT granted
        f"CREATE TABLE {s}.no_access (id int, secret text)",
        f"CREATE TABLE {s}.misc (contact text, handle text, hits int)",
        f"INSERT INTO {s}.misc SELECT 'person' || g || '@corp.example', 'h' || g, g FROM generate_series(1, 30) g",
    ]
    return statements


@pytest.fixture(scope="session")
def warehouse(pg_admin_url: str) -> Iterator[Warehouse]:
    suffix = secrets.token_hex(3)
    s, o = f"ds_{suffix}", f"other_{suffix}"
    reader, writer = f"agent_reader_{suffix}", f"agent_writer_{suffix}"
    writer_pw = "writer-pw-" + secrets.token_hex(4)

    setup = [
        *_seed_sql(s, o),
        f"CREATE ROLE {reader} LOGIN PASSWORD '{READER_PASSWORD}' NOSUPERUSER",
        f"CREATE ROLE {writer} LOGIN PASSWORD '{writer_pw}' NOSUPERUSER",
        f"GRANT USAGE ON SCHEMA {s} TO {reader}, {writer}",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA {s} TO {reader}, {writer}",
        f"REVOKE SELECT ON {s}.no_access FROM {reader}",
        f"GRANT INSERT, UPDATE, DELETE ON {s}.dups TO {writer}",
    ]
    asyncio.run(_admin(pg_admin_url, setup))
    wh = Warehouse(
        admin_url=pg_admin_url,
        reader_url="",
        writer_url="",
        schema=s,
        other_schema=o,
        reader=reader,
        writer=writer,
    )
    wh.reader_url = wh.url_for(reader, READER_PASSWORD)
    wh.writer_url = wh.url_for(writer, writer_pw)
    yield wh
    asyncio.run(
        _admin(
            pg_admin_url,
            [
                f"DROP SCHEMA {s} CASCADE",
                f"DROP SCHEMA {o} CASCADE",
                f"DROP OWNED BY {reader}",
                f"DROP OWNED BY {writer}",
                f"DROP ROLE {reader}",
                f"DROP ROLE {writer}",
            ],
        )
    )
