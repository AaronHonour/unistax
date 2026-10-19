"""Quality checks against real tables with known defects."""

from __future__ import annotations

import pytest

from unistax.agents.connectors import DataSourceUnavailable, QueryTimeout
from unistax.agents.connectors.postgres import PostgresConfig, PostgresDataSource
from unistax.agents.connectors.quality import QualityOptions, run_quality_checks

pytestmark = pytest.mark.agents


@pytest.fixture
async def ds(warehouse):
    source = PostgresDataSource(
        PostgresConfig(url=warehouse.reader_url, name="wh", schemas=(warehouse.schema,))
    )
    yield source
    await source.close()


async def check(ds, table, **context):
    options = QualityOptions.from_context(context, ds.config.max_scan_rows)
    ref = await ds.resolve(table)
    return await run_quality_checks(ds, ref, await ds.describe(ref), options)


def issues_for(report, check_name):
    return [i for i in report["issues"] if i["check"] == check_name]


class TestOptions:
    def test_defaults(self):
        options = QualityOptions.from_context({}, 1000)
        assert (
            options.checks == ("row_count", "nulls", "foreign_keys") and options.scan_rows == 1000
        )

    def test_scan_rows_can_only_be_lowered(self):
        assert QualityOptions.from_context({"max_scan_rows": 10}, 1000).scan_rows == 10
        assert QualityOptions.from_context({"max_scan_rows": 10**9}, 1000).scan_rows == 1000

    @pytest.mark.parametrize(
        ("context", "fragment"),
        [
            ({"checks": "nulls"}, "list"),
            ({"checks": ["nulls", "dance"]}, "unknown checks"),
            ({"checks": ["duplicates"]}, "unique_columns"),
            ({"checks": ["freshness"]}, "timestamp_column"),
            ({"checks": ["freshness"], "timestamp_column": "t"}, "max_age_hours"),
            ({"checks": ["freshness"], "timestamp_column": "t", "max_age_hours": -1}, "positive"),
            ({"max_scan_rows": 0}, "positive"),
            ({"max_scan_rows": True}, "positive"),
            ({"max_null_rate": 2}, "between 0 and 1"),
            ({"unique_columns": "id"}, "list"),
        ],
    )
    def test_invalid_options(self, context, fragment):
        with pytest.raises(ValueError, match=fragment):
            QualityOptions.from_context(context, 1000)

    def test_duplicate_check_names_collapse(self):
        assert QualityOptions.from_context({"checks": ["nulls", "nulls"]}, 10).checks == ("nulls",)


class TestRowCount:
    async def test_counts_rows(self, ds):
        report = await check(ds, "customers", checks=["row_count"])
        detail = report["details"]["row_count"]
        assert detail["rows_counted"] == 60 and detail["at_least"] is False
        assert report["checks"] == {"row_count": "passed"} and report["issues"] == []

    async def test_empty_table_is_a_warning(self, ds):
        report = await check(ds, "empty_table", checks=["row_count"])
        assert [i["severity"] for i in issues_for(report, "row_count")] == ["warning"]
        assert report["checks"]["row_count"] == "passed"  # warnings do not fail a check

    async def test_the_scan_limit_bounds_the_count(self, ds):
        report = await check(ds, "customers", checks=["row_count"], max_scan_rows=25)
        detail = report["details"]["row_count"]
        assert detail["rows_counted"] == 25 and detail["at_least"] is True


class TestNulls:
    async def test_rates_and_entirely_null_columns(self, ds):
        report = await check(ds, "customers", checks=["nulls"])
        rates = report["details"]["nulls"]["null_rates"]
        assert (
            rates["legacy"] == 1.0 and rates["full_name"] == 0.0 and "email" not in rates
        )  # NOT NULL: skipped
        warnings = issues_for(report, "nulls")
        assert [(i["column"], i["severity"]) for i in warnings] == [("legacy", "warning")]
        assert report["checks"]["nulls"] == "passed"

    async def test_partial_null_rate_and_threshold(self, ds):
        loose = await check(ds, "orders", checks=["nulls"], max_null_rate=0.2)
        assert loose["details"]["nulls"]["null_rates"]["status"] == 0.1
        assert loose["checks"]["nulls"] == "passed"

        strict = await check(ds, "orders", checks=["nulls"], max_null_rate=0.05)
        errors = issues_for(strict, "nulls")
        assert [(i["column"], i["severity"], i["value"]) for i in errors] == [
            ("status", "error", 0.1)
        ]
        assert strict["checks"]["nulls"] == "failed"

    async def test_not_null_columns_are_not_scanned(self, ds):
        report = await check(ds, "order_items", checks=["nulls"])
        assert set(report["details"]["nulls"]["null_rates"]) == {
            "sku"
        }  # order_id, line are NOT NULL

    async def test_a_table_of_only_not_null_columns_needs_no_scan(self, ds):
        report = await check(ds, "strict_table", checks=["nulls"])
        detail = report["details"]["nulls"]
        assert detail["null_rates"] == {} and detail["rows_scanned"] == 0
        assert report["checks"]["nulls"] == "passed"

    async def test_empty_table_has_no_rates_to_flag(self, ds):
        report = await check(ds, "empty_table", checks=["nulls"], max_null_rate=0.0)
        assert issues_for(report, "nulls") == []


class TestForeignKeys:
    async def test_clean_relationships_pass(self, ds):
        report = await check(ds, "orders", checks=["foreign_keys"])
        (entry,) = report["details"]["foreign_keys"]["constraints"].values()
        assert entry["status"] == "ok" and entry["orphans"] == 0 and entry["rows_checked"] == 200
        assert report["checks"]["foreign_keys"] == "passed"

    async def test_orphans_are_found_and_nulls_are_not_orphans(self, ds):
        report = await check(ds, "orphans", checks=["foreign_keys"])
        (entry,) = report["details"]["foreign_keys"]["constraints"].values()
        assert entry["orphans"] == 2 and entry["rows_checked"] == 4  # the NULL row is skipped
        assert entry["constraint_validated"] is False
        (found,) = issues_for(report, "foreign_keys")
        assert (
            found["severity"] == "error"
            and found["column"] == "customer_id"
            and found["value"] == 2
        )
        assert report["checks"]["foreign_keys"] == "failed"

    async def test_composite_and_chained_keys(self, ds):
        report = await check(ds, "order_items", checks=["foreign_keys"])
        assert report["checks"]["foreign_keys"] == "passed"

    async def test_parents_outside_the_scope_are_skipped_not_read(self, warehouse):
        source = PostgresDataSource(
            PostgresConfig(
                url=warehouse.reader_url,
                schemas=(warehouse.schema,),
                table_patterns=(f"{warehouse.schema}.orders",),
            )
        )
        try:
            report = await check(source, "orders", checks=["foreign_keys"])
            (entry,) = report["details"]["foreign_keys"]["constraints"].values()
            assert entry["status"] == "skipped" and "scope" in entry["reason"]
        finally:
            await source.close()

    async def test_no_foreign_keys_is_fine(self, ds):
        report = await check(ds, "dups", checks=["foreign_keys"])
        assert report["details"]["foreign_keys"]["constraints"] == {}
        assert report["checks"]["foreign_keys"] == "passed"


class TestDuplicates:
    async def test_finds_duplicates_and_ignores_null_keys(self, ds):
        report = await check(ds, "dups", checks=["duplicates"], unique_columns=["code"])
        detail = report["details"]["duplicates"]
        # a,a  b  c,c,c  (two NULL codes are ignored): 6 checked, 3 distinct, 2 keys repeated
        assert (detail["rows_checked"], detail["duplicate_rows"], detail["duplicated_keys"]) == (
            6,
            3,
            2,
        )
        (found,) = issues_for(report, "duplicates")
        assert found["severity"] == "error" and found["value"] == 3

    async def test_a_unique_key_passes(self, ds):
        report = await check(ds, "customers", checks=["duplicates"], unique_columns=["email"])
        assert report["checks"]["duplicates"] == "passed" and report["issues"] == []

    async def test_composite_keys(self, ds):
        report = await check(ds, "dups", checks=["duplicates"], unique_columns=["code", "label"])
        assert report["checks"]["duplicates"] == "passed"

    async def test_unknown_columns_are_rejected_before_any_sql(self, ds):
        with pytest.raises(ValueError, match="does not exist"):
            await check(ds, "dups", checks=["duplicates"], unique_columns=["nope"])
        with pytest.raises(ValueError, match="does not exist"):
            await check(
                ds, "dups", checks=["duplicates"], unique_columns=['code"; DROP TABLE dups; --']
            )


class TestFreshness:
    async def test_stale_data_fails(self, ds):
        report = await check(
            ds, "events", checks=["freshness"], timestamp_column="happened_at", max_age_hours=24
        )
        detail = report["details"]["freshness"]
        assert 71 < detail["age_hours"] < 73
        (found,) = issues_for(report, "freshness")
        assert found["severity"] == "error" and "72" in found["message"]
        assert report["checks"]["freshness"] == "failed"

    async def test_fresh_data_passes(self, ds):
        report = await check(
            ds,
            "fresh_events",
            checks=["freshness"],
            timestamp_column="happened_at",
            max_age_hours=1,
        )
        assert (
            report["checks"]["freshness"] == "passed"
            and report["details"]["freshness"]["age_hours"] < 1
        )

    async def test_a_generous_limit_passes(self, ds):
        report = await check(
            ds,
            "customers",
            checks=["freshness"],
            timestamp_column="signup_ts",
            max_age_hours=100000,
        )
        assert report["checks"]["freshness"] == "passed"

    async def test_a_column_with_no_values_fails(self, ds):
        report = await check(
            ds,
            "ghost_events",
            checks=["freshness"],
            timestamp_column="happened_at",
            max_age_hours=24,
        )
        (found,) = issues_for(report, "freshness")
        assert found["severity"] == "error" and "no non-NULL" in found["message"]
        assert report["checks"]["freshness"] == "failed"

    async def test_the_column_must_be_a_date_or_time_type(self, ds):
        with pytest.raises(ValueError, match="not a date/time"):
            await check(
                ds, "customers", checks=["freshness"], timestamp_column="email", max_age_hours=1
            )


class TestIsolationAndLimits:
    async def test_one_failing_check_does_not_hide_the_others(self, ds):
        report = await check(
            ds,
            "dups",
            checks=["row_count", "duplicates"],
            unique_columns=["code"],
        )
        assert report["checks"] == {"row_count": "passed", "duplicates": "failed"}

    async def test_a_timed_out_check_is_reported_and_the_rest_still_run(
        self, warehouse, monkeypatch
    ):
        source = PostgresDataSource(
            PostgresConfig(url=warehouse.reader_url, schemas=(warehouse.schema,))
        )
        try:
            from unistax.agents.connectors import quality

            async def slow(*args, **kwargs):
                raise QueryTimeout("the query exceeded its time limit and was cancelled")

            monkeypatch.setattr(quality, "_nulls", slow)
            report = await check(source, "customers", checks=["nulls", "row_count"])
            assert report["checks"] == {"nulls": "errored", "row_count": "passed"}
            assert "time limit" in report["details"]["nulls"]["error"]
        finally:
            await source.close()

    async def test_connection_loss_aborts_instead_of_being_reported_as_a_check_result(
        self, ds, monkeypatch
    ):
        from unistax.agents.connectors import quality

        async def gone(*args, **kwargs):
            raise DataSourceUnavailable("could not connect to the data source")

        monkeypatch.setattr(quality, "_row_count", gone)
        with pytest.raises(DataSourceUnavailable):
            await check(ds, "customers", checks=["row_count"])

    async def test_scan_limit_marks_results_as_possibly_partial(self, ds):
        full = await check(ds, "customers", checks=["nulls"])
        limited = await check(ds, "customers", checks=["nulls"], max_scan_rows=10)
        assert full["possibly_partial"] is False
        assert (
            limited["possibly_partial"] is True
            and limited["details"]["nulls"]["rows_scanned"] == 10
        )
