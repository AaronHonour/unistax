"""The read-only PostgreSQL data source against a real server."""

from __future__ import annotations

import asyncio
import logging

import pytest
from sqlalchemy import text

from unistax.agents.connectors import (
    DataSourceError,
    DataSourceUnavailable,
    DataSourceUnsafe,
    QueryTimeout,
    TableNotFound,
    TableNotPermitted,
)
from unistax.agents.connectors.postgres import PostgresConfig, PostgresDataSource

pytestmark = pytest.mark.agents


@pytest.fixture
async def source(warehouse):
    ds = PostgresDataSource(
        PostgresConfig(url=warehouse.reader_url, name="wh", schemas=(warehouse.schema,))
    )
    yield ds
    await ds.close()


def make(warehouse, **overrides):
    config = {
        "url": warehouse.reader_url,
        "name": "wh",
        "schemas": (warehouse.schema,),
        **overrides,
    }
    return PostgresDataSource(PostgresConfig(**config))


class TestVerification:
    async def test_accepts_a_select_only_role(self, source, warehouse):
        report = await source.verify()
        assert report.role == warehouse.reader and report.server_version
        assert report.warnings == ()

    async def test_refuses_a_superuser(self, warehouse):
        ds = make(warehouse, url=warehouse.admin_url)
        try:
            with pytest.raises(DataSourceUnsafe, match="superuser"):
                await ds.verify()
            with pytest.raises(DataSourceUnsafe):  # a failure is never cached as success
                await ds.resolve("customers")
        finally:
            await ds.close()

    async def test_warns_about_write_privileges_but_keeps_sessions_read_only(
        self, warehouse, caplog
    ):
        ds = make(warehouse, url=warehouse.writer_url)
        try:
            with caplog.at_level(logging.WARNING):
                report = await ds.verify()
            assert any("write privileges" in w for w in report.warnings)
            assert any("write privileges" in r.message for r in caplog.records)

            # The role may INSERT into dups, but the session cannot.
            async with ds.read() as conn:
                with pytest.raises(Exception, match="read-only"):
                    await conn.execute(
                        text(f"INSERT INTO {warehouse.schema}.dups VALUES ('x', 'y')")
                    )
        finally:
            await ds.close()

    async def test_writes_fail_even_without_session_defaults(self, warehouse):
        """The per-transaction READ ONLY is independent of the connection-level default."""
        ds = make(warehouse, url=warehouse.writer_url, session_defaults=False)
        try:
            await ds.verify()
            async with ds.read() as conn:
                with pytest.raises(Exception, match="read-only"):
                    await conn.execute(text(f"DELETE FROM {warehouse.schema}.dups"))
            async with ds.read() as conn:
                rows = (
                    await conn.execute(text(f"SELECT count(*) FROM {warehouse.schema}.dups"))
                ).scalar()
            assert rows == 8  # nothing was deleted
        finally:
            await ds.close()

    async def test_transactions_are_read_only_and_snapshot_consistent(self, source, warehouse):
        async with source.read() as conn:
            assert (
                await conn.execute(text("SELECT current_setting('transaction_read_only')"))
            ).scalar() == "on"
            assert (
                await conn.execute(text("SELECT current_setting('transaction_isolation')"))
            ).scalar() == "repeatable read"

    async def test_connections_default_to_read_only_before_any_transaction_starts(self, warehouse):
        """Second layer: even a statement outside our read() helper could not write."""
        on = make(warehouse)
        off = make(warehouse, session_defaults=False)
        try:
            async with on._engine.connect() as conn:
                assert (
                    await conn.execute(text("SHOW default_transaction_read_only"))
                ).scalar() == "on"
                assert (
                    await conn.execute(text("SHOW application_name"))
                ).scalar() == "unistax-agent-api"
            async with off._engine.connect() as conn:
                assert (
                    await conn.execute(text("SHOW default_transaction_read_only"))
                ).scalar() != "on"
        finally:
            await on.close()
            await off.close()

    async def test_timeouts_are_applied_per_transaction(self, warehouse):
        ds = make(warehouse, catalog_timeout_ms=1234, scan_timeout_ms=4321)
        try:
            async with ds.read() as conn:
                assert (await conn.execute(text("SHOW statement_timeout"))).scalar() == "1234ms"
            async with ds.read(scan=True) as conn:
                assert (await conn.execute(text("SHOW statement_timeout"))).scalar() == "4321ms"
        finally:
            await ds.close()

    async def test_a_slow_statement_is_cancelled_with_a_friendly_error(self, warehouse):
        ds = make(warehouse, catalog_timeout_ms=50)
        try:
            with pytest.raises(QueryTimeout, match="time limit"):
                async with ds.read() as conn:
                    await conn.execute(text("SELECT pg_sleep(2)"))
        finally:
            await ds.close()


class TestErrorsAreSafe:
    async def test_wrong_password_never_leaks_credentials(self, warehouse):
        bad = warehouse.url_for(warehouse.reader, "definitely-wrong-password")
        ds = make(warehouse, url=bad)
        try:
            # Trust-auth servers (embedded) accept anything; only assert on safety if rejected.
            try:
                await ds.verify()
            except DataSourceUnavailable as exc:
                assert "definitely-wrong-password" not in str(exc) and "authentication" in str(exc)
        finally:
            await ds.close()

    async def test_unreachable_host_is_a_clean_error(self):
        ds = PostgresDataSource(
            PostgresConfig(
                url="postgresql://u:supersecret@127.0.0.1:1/db",
                connect_timeout=2,
                schemas=("public",),
            )
        )
        try:
            with pytest.raises(DataSourceUnavailable) as exc:
                await ds.verify()
            assert "supersecret" not in str(exc.value) and "127.0.0.1" not in str(exc.value)
        finally:
            await ds.close()

    def test_repr_hides_the_password(self, warehouse):
        config = PostgresConfig(url="postgresql://u:supersecret@h/db")
        assert "supersecret" not in repr(config)
        assert "supersecret" not in repr(PostgresDataSource(config))

    @pytest.mark.parametrize("url", ["not a url", "mysql://u:p@h/db", "sqlite:///x.db"])
    def test_invalid_urls_are_rejected_without_echoing_them(self, url):
        with pytest.raises(DataSourceError) as exc:
            PostgresDataSource(PostgresConfig(url=url))
        assert url not in str(exc.value)

    def test_postgres_scheme_aliases_are_accepted(self):
        for scheme in ("postgres", "postgresql", "postgresql+asyncpg"):
            PostgresDataSource(PostgresConfig(url=f"{scheme}://u:p@h/db"))

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"schemas": ()},
            {"schemas": ("pg_catalog",)},
            {"schemas": ("information_schema",)},
            {"table_patterns": ()},
            {"name": "bad name!"},
            {"sample_rows": 0},
            {"max_scan_rows": 0},
            {"url": ""},
        ],
    )
    def test_unsafe_configuration_is_rejected(self, kwargs):
        with pytest.raises(ValueError):
            PostgresConfig(**{"url": "postgresql://u@h/db", **kwargs}).validate()


class TestScope:
    async def test_resolve_finds_tables_and_views(self, source, warehouse):
        table = await source.resolve("customers")
        view = await source.resolve(f"{warehouse.schema}.big_orders")
        assert (table.kind, table.schema, table.name) == ("table", warehouse.schema, "customers")
        assert view.kind == "view" and table.oid != view.oid

    async def test_explicit_schema_argument(self, source, warehouse):
        assert (await source.resolve("orders", schema=warehouse.schema)).name == "orders"

    async def test_other_schemas_are_not_permitted(self, source, warehouse):
        with pytest.raises(TableNotPermitted):
            await source.resolve(f"{warehouse.other_schema}.secrets")
        with pytest.raises(TableNotPermitted):
            await source.resolve("pg_catalog.pg_authid")
        with pytest.raises(TableNotPermitted):
            await source.resolve("information_schema.tables")

    async def test_not_permitted_does_not_reveal_whether_the_table_exists(self, source, warehouse):
        exists = None
        missing = None
        try:
            await source.resolve(f"{warehouse.other_schema}.secrets")
        except TableNotPermitted as exc:
            exists = str(exc)
        try:
            await source.resolve(f"{warehouse.other_schema}.does_not_exist")
        except TableNotPermitted as exc:
            missing = str(exc)
        assert exists.replace("secrets", "X") == missing.replace("does_not_exist", "X")

    async def test_unknown_table(self, source):
        with pytest.raises(TableNotFound):
            await source.resolve("nope")

    @pytest.mark.parametrize("name", ["", "   ", "x" * 300])
    async def test_bad_names(self, source, name):
        with pytest.raises(DataSourceError):
            await source.resolve(name)

    async def test_table_patterns_narrow_the_scope(self, warehouse):
        ds = make(warehouse, table_patterns=(f"{warehouse.schema}.order*",))
        try:
            assert (await ds.resolve("orders")).name == "orders"
            with pytest.raises(TableNotPermitted):
                await ds.resolve("customers")
            names = {t.name for t in (await ds.list_tables())[0]}
            assert names == {"orders", "order_items"}
        finally:
            await ds.close()

    async def test_list_tables_excludes_other_schemas_and_respects_the_cap(self, source, warehouse):
        tables, truncated = await source.list_tables()
        names = {t.name for t in tables}
        assert {"customers", "orders", "big_orders"} <= names
        assert "secrets" not in names and not truncated

        small = make(warehouse, max_tables=3)
        try:
            tables, truncated = await small.list_tables()
            assert len(tables) == 3 and truncated
        finally:
            await small.close()

    async def test_injection_attempts_in_names_are_just_unknown_tables(self, source):
        for attack in [
            'customers"; DROP TABLE customers; --',
            "customers' OR '1'='1",
            "x; SELECT 1",
        ]:
            with pytest.raises(TableNotFound):
                await source.resolve(attack)
        assert (await source.resolve("customers")).name == "customers"  # still there


class TestMetadata:
    async def test_describe_a_table(self, source):
        ref = await source.resolve("customers")
        meta = await source.describe(ref)

        by_name = {c["name"]: c for c in meta["columns"]}
        assert meta["comment"] == "Customer master data"
        assert by_name["id"]["type"] == "bigint" and by_name["id"]["not_null"] is True
        assert by_name["id"]["default_expr"].startswith("nextval")
        assert by_name["email"]["comment"] == "Primary contact address"
        assert by_name["signup_ts"]["type"] == "timestamp with time zone"
        assert by_name["signup_ts"]["category"] == "D"
        assert [c["position"] for c in meta["columns"]] == sorted(
            c["position"] for c in meta["columns"]
        )
        assert meta["primary_key"] == ["id"]
        assert any(i["primary"] for i in meta["indexes"])
        assert meta["size_bytes"] > 0

    async def test_relationships_in_both_directions(self, source, warehouse):
        orders = await source.describe(await source.resolve("orders"))
        assert orders["foreign_keys"][0]["columns"] == ["customer_id"]
        assert orders["foreign_keys"][0]["references"] == {
            "schema": warehouse.schema,
            "table": "customers",
            "columns": ["id"],
            "in_scope": True,
        }
        assert {r["table"] for r in orders["referenced_by"]} == {"order_items"}

        customers = await source.describe(await source.resolve("customers"))
        assert {r["table"] for r in customers["referenced_by"]} == {"orders", "orphans"}

    async def test_composite_keys_keep_column_order(self, source):
        meta = await source.describe(await source.resolve("order_items"))
        assert meta["primary_key"] == ["order_id", "line"]

    async def test_not_valid_constraints_are_reported(self, source):
        meta = await source.describe(await source.resolve("orphans"))
        assert meta["foreign_keys"][0]["validated"] is False

    async def test_views_and_row_estimates(self, source, warehouse):
        view = await source.resolve("big_orders")
        meta = await source.describe(view)
        assert view.kind == "view" and meta["size_bytes"] is None
        assert [c["name"] for c in meta["columns"]][:2] == ["id", "customer_id"]

    async def test_referencing_tables_outside_the_scope_are_hidden(self, warehouse):
        ds = make(warehouse, table_patterns=(f"{warehouse.schema}.customers",))
        try:
            meta = await ds.describe(await ds.resolve("customers"))
            assert meta["referenced_by"] == []
        finally:
            await ds.close()

    async def test_out_of_scope_parents_are_flagged_not_hidden(self, warehouse):
        ds = make(warehouse, table_patterns=(f"{warehouse.schema}.orders",))
        try:
            meta = await ds.describe(await ds.resolve("orders"))
            assert meta["foreign_keys"][0]["references"]["in_scope"] is False
        finally:
            await ds.close()


class TestSampling:
    async def test_sample_returns_text_per_column(self, source):
        ref = await source.resolve("customers")
        data = await source.sample_text(ref, ["email", "ssn"], limit=10)
        assert len(data["email"]) == 10 and data["email"][0].endswith("@example.com")

    async def test_sample_size_is_capped_by_configuration(self, warehouse):
        ds = make(warehouse, sample_rows=7)
        try:
            data = await ds.sample_text(await ds.resolve("customers"), ["email"], limit=10_000)
            assert len(data["email"]) == 7
        finally:
            await ds.close()

    async def test_values_are_truncated(self, source, warehouse):
        data = await source.sample_text(await source.resolve("long_text"), ["body"], limit=5)
        assert [len(v) for v in data["body"]] == [256, 256]

    async def test_weird_identifiers_are_quoted_safely(self, source):
        ref = await source.resolve('Weird "Name:x')
        meta = await source.describe(ref)
        columns = [c["name"] for c in meta["columns"]]
        assert columns == ["odd :col", "100%", "normal"]
        data = await source.sample_text(ref, columns, limit=5)
        assert data["odd :col"] == ["a", "b"] and data["100%"] == ["1", "2"]

    async def test_no_columns_means_no_query(self, source):
        assert await source.sample_text(await source.resolve("customers"), [], 5) == {}

    async def test_a_table_the_role_cannot_read_gives_a_clear_error(self, source):
        ref = await source.resolve("no_access")
        with pytest.raises(DataSourceError, match="permission denied"):
            await source.sample_text(ref, ["secret"], 5)

    async def test_metadata_of_unreadable_tables_is_still_available(self, source):
        meta = await source.describe(await source.resolve("no_access"))
        assert [c["name"] for c in meta["columns"]] == ["id", "secret"]


class TestConcurrency:
    async def test_callers_queue_for_connections_instead_of_failing(self, warehouse):
        ds = make(warehouse, pool_size=1)
        ds._engine.pool._timeout = (
            0.2  # SQLAlchemy would give up after this long; our queue must not
        )
        try:
            peak = 0
            active = 0

            async def work(i):
                nonlocal peak, active
                async with ds.read() as conn:
                    active += 1
                    peak = max(peak, active)
                    await conn.execute(text("SELECT pg_sleep(0.15)"))
                    active -= 1
                return i

            results = await asyncio.gather(*(work(i) for i in range(8)))
            assert sorted(results) == list(range(8))
            assert peak == 1  # never more concurrent connections than the pool allows
        finally:
            await ds.close()

    async def test_many_tasks_share_a_small_pool(self, warehouse):
        ds = make(warehouse, pool_size=2)
        try:
            tables = await asyncio.gather(*(ds.resolve("orders") for _ in range(25)))
            assert {t.name for t in tables} == {"orders"}
        finally:
            await ds.close()

    def test_pool_exhaustion_is_translated_if_it_ever_happens(self):
        from sqlalchemy.exc import TimeoutError as PoolTimeout

        from unistax.agents.connectors.postgres import translate_error

        error = translate_error(PoolTimeout("QueuePool limit of size 3 overflow 0 reached"))
        assert isinstance(error, DataSourceUnavailable) and "QueuePool" not in str(error)
