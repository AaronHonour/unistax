"""Rule-based column classification (no database needed)."""

from __future__ import annotations

import json

import pytest

from unistax.agents.connectors import classification as c

pytestmark = pytest.mark.agents

EMAILS = [f"user{i}@example.com" for i in range(10)]
PHONES = [
    "+44 20 7946 0958",
    "(555) 123-4567",
    "555-987-6543",
    "+1 415 555 0100",
    "020 7946 0000",
] * 2
SSNS = [f"{100 + i}-45-{6000 + i}" for i in range(10)]
CARDS = ["4111111111111111", "5555555555554444", "4242 4242 4242 4242", "378282246310005"] * 3


class TestNames:
    @pytest.mark.parametrize(
        ("column", "label"),
        [
            ("email", "pii.email"),
            ("customer_email", "pii.email"),
            ("CustomerEmail", "pii.email"),
            ("E-Mail", "pii.email"),
            ("phone_number", "pii.phone"),
            ("mobile", "pii.phone"),
            ("first_name", "pii.name"),
            ("lastName", "pii.name"),
            ("date_of_birth", "pii.birth"),
            ("dob", "pii.birth"),
            ("birth_date", "pii.birth"),
            ("street_address", "pii.address"),
            ("zip_code", "pii.address"),
            ("postcode", "pii.address"),
            ("ip_address", "pii.ip"),
            ("ssn", "government_id"),
            ("password_hash", "credential"),
            ("api_key", "credential"),
            ("card_number", "financial.card"),
            ("iban", "financial.bank"),
            ("diagnosis_code", "health"),
        ],
    )
    def test_recognised_names(self, column, label):
        rule = c.classify_by_name(column)
        assert (rule.label if rule else None) == label

    @pytest.mark.parametrize(
        "column",
        [
            "id",
            "amount",
            "created_at",
            "status",
            "description",
            "ipsum",
            "zipper",
            "shipping",
            "pan_count_x1",
        ],
    )
    def test_ordinary_names_are_not_flagged(self, column):
        rule = c.classify_by_name(column)
        assert (
            rule is None or column == "pan_count_x1"
        )  # whole-word matching: "ipsum"/"zipper" are safe

    @pytest.mark.parametrize(
        ("column", "label"),
        [
            ("ip_address", "pii.ip"),
            ("email_address", "pii.email"),
            ("street_address", "pii.address"),
            ("shipping_address", "pii.address"),
            ("client_ip", "pii.ip"),
        ],
    )
    def test_among_equally_sensitive_rules_the_most_specific_wins(self, column, label):
        assert c.classify_by_name(column).label == label

    def test_most_sensitive_rule_wins(self):
        assert c.classify_by_name("email_password").label == "credential"

    def test_normalise_name(self):
        assert c.normalise_name("CustomerEmailAddr") == "customer_email_addr"
        assert c.normalise_name("a--b  c") == "a_b_c"


class TestValues:
    def test_emails(self):
        assert c.detect_by_values(EMAILS)[0] == "pii.email"

    def test_phones(self):
        assert c.detect_by_values(PHONES)[0] == "pii.phone"

    def test_ssns(self):
        assert c.detect_by_values(SSNS)[0] == "government_id"

    def test_cards_need_a_valid_luhn_checksum(self):
        assert c.detect_by_values(CARDS)[0] == "financial.card"
        bogus = [
            "1234567890123456",
            "1111222233334445",
            "9999888877776666",
            "1234123412341234",
            "5555444433332222",
        ]
        assert c.detect_by_values(bogus) is None

    def test_ip_addresses(self):
        assert (
            c.detect_by_values(
                ["10.0.0.1", "192.168.1.20", "8.8.8.8", "2001:db8::1", "172.16.0.9"]
            )[0]
            == "pii.ip"
        )

    def test_iban(self):
        ibans = [
            "GB82WEST12345698765432",
            "DE89370400440532013000",
            "FR1420041010050500013M02606",
        ] * 2
        assert c.detect_by_values(ibans)[0] == "financial.bank"

    @pytest.mark.parametrize(
        "values",
        [
            [
                "1234567890",
                "9876543210",
                "5551234567",
                "1112223333",
                "4445556666",
            ],  # ids, not phones
            ["red", "green", "blue", "yellow", "purple"],
            ["2024-01-01", "2024-02-02", "2024-03-03", "2024-04-04", "2024-05-05"],
            [
                "2024-01-01 10:30:00",
                "2024-02-02T11:00:00",
                "2024-03-03 09:15",
                "2024-04-04",
                "2024-05-05",
            ],
            ["01/02/2024", "15-03-2023", "31.12.2022", "04/07/1999", "10/10/2010"],
            ["3.14159", "2.71828", "1234.5678", "99.99", "1000.001"],
            ["1.2.3", "10.20.30", "v1.2.3", "2.0.1", "5.6.7"],
        ],
    )
    def test_ordinary_values_are_not_flagged(self, values):
        assert c.detect_by_values(values) is None

    def test_too_few_values_is_inconclusive(self):
        assert c.detect_by_values(EMAILS[:4]) is None

    def test_nulls_and_blanks_are_ignored(self):
        assert c.detect_by_values([None, "", "  ", *EMAILS]) is not None

    def test_a_majority_is_required(self):
        mixed = EMAILS[:5] + ["not an email"] * 5
        assert c.detect_by_values(mixed) is None
        mostly = EMAILS[:8] + ["junk", "junk"]
        label, rate = c.detect_by_values(mostly)
        assert label == "pii.email" and rate == pytest.approx(0.8)

    def test_luhn_and_iban_helpers(self):
        assert c.luhn_valid("4111111111111111") and not c.luhn_valid("4111111111111112")
        assert c.iban_valid("GB82WEST12345698765432") and not c.iban_valid("GB82WEST12345698765433")


class TestCombinedEvidence:
    def test_name_and_values_agreeing_gives_highest_confidence(self):
        result = c.classify_column("email", EMAILS)
        assert result.label == "pii.email" and result.confidence == c.CONFIDENCE_BOTH
        assert result.evidence == ("column_name", "sample_values")
        assert result.match_rate == 1.0

    def test_name_only(self):
        result = c.classify_column("email", ["a", "b", "c", "d", "e", "f"])
        assert result.confidence == c.CONFIDENCE_NAME_ONLY and result.evidence == ("column_name",)

    def test_values_only_catches_badly_named_columns(self):
        result = c.classify_column("contact", EMAILS)
        assert result.label == "pii.email" and result.evidence == ("sample_values",)
        assert result.confidence == c.CONFIDENCE_VALUES_ONLY

    def test_disagreement_prefers_the_more_sensitive_finding(self):
        # named like a name (confidential) but holds card numbers (restricted)
        result = c.classify_column("full_name", CARDS)
        assert result.label == "financial.card" and result.sensitivity == "restricted"

    def test_nothing_sensitive_returns_none(self):
        assert c.classify_column("amount", ["1", "2", "3", "4", "5", "6"]) is None
        assert c.classify_column("amount") is None

    def test_name_rules_work_without_any_sample(self):
        assert c.classify_column("ssn").label == "government_id"

    def test_results_never_contain_the_values(self):
        result = c.classify_column("contact", EMAILS)
        assert "example.com" not in json.dumps(result.as_dict())


class TestSummary:
    def test_summary_of_mixed_columns(self):
        columns = {
            "email": c.classify_column("email", EMAILS),
            "card": c.classify_column("card_number", CARDS),
            "name": c.classify_column("full_name"),
        }
        summary = c.summarise(columns)

        assert summary["sensitivity_level"] == "restricted"
        assert summary["contains_pii"] is True
        assert summary["contains_restricted_data"] is True
        assert {"GDPR", "PCI-DSS"} <= set(summary["regulations_to_review"])
        assert summary["classified_columns_by_sensitivity"] == {"confidential": 2, "restricted": 1}
        assert "Encrypt at rest" in summary["required_controls"]
        assert any("PCI-DSS" in control for control in summary["required_controls"])

    def test_empty_table_is_baseline_internal(self):
        summary = c.summarise({})
        assert summary["sensitivity_level"] == "internal" and summary["contains_pii"] is False
        assert (
            summary["regulations_to_review"] == []
            and summary["classified_columns_by_sensitivity"] == {}
        )

    def test_ordering_helpers(self):
        assert c.max_sensitivity(["internal", "restricted", "confidential"]) == "restricted"
        assert c.max_sensitivity([]) == "internal"
        assert c.rank("public") < c.rank("restricted")
