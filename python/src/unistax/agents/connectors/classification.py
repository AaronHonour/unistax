"""Rule-based detection of sensitive columns.

Pure functions, no database access. A column is classified from its *name* and,
optionally, from a *sample of its values*. Raw values never leave this module:
results contain labels, rates and evidence kinds only.

These are heuristics. Names mislead (``token_count`` is not a credential) and
free text hides identifiers; treat the output as a starting point for a steward's
review, not as a compliance determination.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

SENSITIVITY_ORDER = ("public", "internal", "confidential", "restricted")
BASELINE_SENSITIVITY = "internal"

MIN_SAMPLE = 5
MIN_MATCH_RATE = 0.6
MAX_VALUE_LENGTH = 256

CONFIDENCE_NAME_ONLY = 0.6
CONFIDENCE_VALUES_ONLY = 0.8
CONFIDENCE_BOTH = 0.95


@dataclass(frozen=True)
class Rule:
    """A named kind of sensitive data and how serious it is."""

    label: str
    sensitivity: str
    name_pattern: re.Pattern[str] | None = None


def _names(*alternatives: str) -> re.Pattern[str]:
    # Regex alternation takes the first alternative that matches, so try the longest first.
    ordered = sorted(alternatives, key=len, reverse=True)
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(ordered) + r")(?![a-z0-9])")


RULES: tuple[Rule, ...] = (
    Rule(
        "credential",
        "restricted",
        _names(
            "password",
            "passwd",
            "pwd",
            "secret",
            "api_?key",
            "private_?key",
            "access_?token",
            "auth_?token",
            "refresh_?token",
            "credentials?",
        ),
    ),
    Rule(
        "government_id",
        "restricted",
        _names(
            "ssn", "social_security(?:_number)?", "national_id", "passport(?:_number)?", "tax_id"
        ),
    ),
    Rule(
        "financial.card",
        "restricted",
        _names("card_?number", "credit_?card", "cc_?num(?:ber)?", "pan", "cvv", "cvc"),
    ),
    Rule(
        "financial.bank",
        "restricted",
        _names("iban", "account_?number", "routing_?number", "bank_?account", "swift", "bic"),
    ),
    Rule(
        "health",
        "restricted",
        _names("diagnosis", "medical(?:_\\w+)?", "prescription", "health(?:_\\w+)?"),
    ),
    Rule("pii.email", "confidential", _names("e_?mail(?:_address)?")),
    Rule(
        "pii.phone",
        "confidential",
        _names("phone(?:_number)?", "mobile", "msisdn", "telephone", "fax"),
    ),
    Rule(
        "pii.name",
        "confidential",
        _names("first_?name", "last_?name", "full_?name", "surname", "given_?name", "family_?name"),
    ),
    Rule("pii.birth", "confidential", _names("birth(?:_?date|day)?", "dob")),
    Rule(
        "pii.address",
        "confidential",
        _names(
            "address(?:_line_?\\d)?",
            "street(?:_address)?",
            "postcode",
            "postal_?code",
            "zip(?:_?code)?",
        ),
    ),
    Rule("pii.location", "confidential", _names("latitude", "longitude", "lat", "lng", "lon")),
    Rule("pii.ip", "confidential", _names("ip", "ip_?addr(?:ess)?")),
)
_RULES_BY_LABEL = {rule.label: rule for rule in RULES}

_REGULATIONS = {
    "pii": ["GDPR", "CCPA"],
    "financial.card": ["PCI-DSS"],
    "financial.bank": ["PCI-DSS", "GDPR"],
    "government_id": ["GDPR", "CCPA"],
    "health": ["HIPAA", "GDPR"],
}

_CONTROLS = {
    "restricted": [
        "Encrypt at rest",
        "Restrict access to named roles",
        "Mask or tokenise in non-production environments",
        "Log all access",
        "Review access quarterly",
    ],
    "confidential": [
        "Encrypt at rest",
        "Role-based access",
        "Mask in non-production environments",
    ],
    "internal": ["Standard access controls"],
    "public": [],
}
_LABEL_CONTROLS = {
    "credential": "Do not store in plain text: keep salted hashes, or move to a secrets manager",
    "financial.card": "Confirm PCI-DSS scope; avoid storing full card numbers",
    "government_id": "Confirm the legal basis for holding national identifiers",
    "health": "Confirm handling requirements for health data",
}


@dataclass(frozen=True)
class ColumnClassification:
    """Why a column was labelled as it was (never contains values)."""

    label: str
    sensitivity: str
    confidence: float
    evidence: tuple[str, ...]
    match_rate: float | None = None

    def as_dict(self) -> dict[str, object]:
        """JSON-friendly form."""
        return {
            "label": self.label,
            "sensitivity": self.sensitivity,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "match_rate": None if self.match_rate is None else round(self.match_rate, 3),
        }


def normalise_name(name: str) -> str:
    """``CustomerEmail`` / ``customer-email`` -> ``customer_email``."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"[^a-z0-9]+", "_", spaced.lower()).strip("_")


def rank(sensitivity: str) -> int:
    """Position of a sensitivity level (higher is more sensitive)."""
    return SENSITIVITY_ORDER.index(sensitivity)


def max_sensitivity(levels: Iterable[str]) -> str:
    """The most sensitive of ``levels`` (baseline if empty)."""
    return max(levels, key=rank, default=BASELINE_SENSITIVITY)


# --------------------------------------------------------------------------
# Name rules
# --------------------------------------------------------------------------
def classify_by_name(column_name: str) -> Rule | None:
    """The most sensitive rule whose name pattern matches ``column_name``."""
    normalised = normalise_name(column_name)
    found: list[tuple[int, int, Rule]] = []
    for rule in RULES:
        match = rule.name_pattern.search(normalised) if rule.name_pattern else None
        if match:
            found.append((rank(rule.sensitivity), match.end() - match.start(), rule))
    # Most sensitive wins; among equals the longest (most specific) match wins, so
    # "ip_address" is an IP address rather than a postal address.
    return max(found, key=lambda item: item[:2], default=(0, 0, None))[2]


# --------------------------------------------------------------------------
# Value rules
# --------------------------------------------------------------------------
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_SSN = re.compile(r"^\d{3}-\d{2}-\d{4}$")
_PHONE = re.compile(r"^\+?\d[\d\s().-]{5,18}\d$")
_CARD = re.compile(r"^\d{13,19}$")
_IBAN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")


def luhn_valid(digits: str) -> bool:
    """Luhn checksum, used to tell card numbers from arbitrary long digit strings."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def iban_valid(value: str) -> bool:
    """ISO 13616 mod-97 check."""
    if not _IBAN.match(value):
        return False
    rearranged = value[4:] + value[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def _is_email(value: str) -> bool:
    return bool(_EMAIL.match(value))


def _is_ssn(value: str) -> bool:
    return bool(_SSN.match(value))


_DATE_LIKE = re.compile(
    r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:[T ].*)?$|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$"
)
_DECIMAL = re.compile(r"^-?\d+\.\d+$")


def _is_phone(value: str) -> bool:
    if not _PHONE.match(value) or _DATE_LIKE.match(value) or _DECIMAL.match(value):
        return False
    digits = re.sub(r"\D", "", value)
    # Bare digit strings are far more often ids than phone numbers.
    return 7 <= len(digits) <= 15 and not value.isdigit()


def _is_card(value: str) -> bool:
    compact = re.sub(r"[ -]", "", value)
    return bool(_CARD.match(compact)) and luhn_valid(compact)


def _is_iban(value: str) -> bool:
    return iban_valid(value.replace(" ", "").upper())


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


VALUE_DETECTORS = (
    ("government_id", _is_ssn),
    ("financial.card", _is_card),
    ("financial.bank", _is_iban),
    ("pii.email", _is_email),
    ("pii.phone", _is_phone),
    ("pii.ip", _is_ip),
)


def detect_by_values(values: Iterable[str | None]) -> tuple[str, float] | None:
    """Best value-based label and the fraction of sampled values matching it.

    Returns ``None`` when there are too few values, or no pattern reaches
    ``MIN_MATCH_RATE``. More sensitive labels win ties.
    """
    cleaned = [v.strip()[:MAX_VALUE_LENGTH] for v in values if v is not None and v.strip()]
    if len(cleaned) < MIN_SAMPLE:
        return None

    best: tuple[str, float] | None = None
    for label, detector in VALUE_DETECTORS:
        rate = sum(1 for v in cleaned if detector(v)) / len(cleaned)
        if rate < MIN_MATCH_RATE:
            continue
        if best is None or rank(_RULES_BY_LABEL[label].sensitivity) > rank(
            _RULES_BY_LABEL[best[0]].sensitivity
        ):
            best = (label, rate)
        elif rank(_RULES_BY_LABEL[label].sensitivity) == rank(_RULES_BY_LABEL[best[0]].sensitivity):
            best = max(best, (label, rate), key=lambda item: item[1])
    return best


# --------------------------------------------------------------------------
# Combining evidence
# --------------------------------------------------------------------------
def classify_column(
    column_name: str, values: Iterable[str | None] | None = None
) -> ColumnClassification | None:
    """Classify one column, or return ``None`` if nothing sensitive was detected."""
    by_name = classify_by_name(column_name)
    by_values = detect_by_values(values) if values is not None else None

    if by_name and by_values and by_name.label == by_values[0]:
        return ColumnClassification(
            by_name.label,
            by_name.sensitivity,
            CONFIDENCE_BOTH,
            ("column_name", "sample_values"),
            by_values[1],
        )

    candidates: list[ColumnClassification] = []
    if by_name:
        candidates.append(
            ColumnClassification(
                by_name.label, by_name.sensitivity, CONFIDENCE_NAME_ONLY, ("column_name",)
            )
        )
    if by_values:
        label, rate = by_values
        candidates.append(
            ColumnClassification(
                label,
                _RULES_BY_LABEL[label].sensitivity,
                CONFIDENCE_VALUES_ONLY,
                ("sample_values",),
                rate,
            )
        )
    if not candidates:
        return None
    # Most sensitive wins; on a tie prefer the value-based finding (it is evidence, not a guess).
    return max(candidates, key=lambda c: (rank(c.sensitivity), "sample_values" in c.evidence))


def summarise(columns: Mapping[str, ColumnClassification]) -> dict[str, object]:
    """Table-level view derived from per-column classifications."""
    level = max_sensitivity([c.sensitivity for c in columns.values()])
    labels = {c.label for c in columns.values()}

    regulations: list[str] = []
    for label in sorted(labels):
        key = "pii" if label.startswith("pii.") else label
        for regulation in _REGULATIONS.get(key, []):
            if regulation not in regulations:
                regulations.append(regulation)

    controls = list(_CONTROLS[level])
    for label in sorted(labels):
        extra = _LABEL_CONTROLS.get(label)
        if extra and extra not in controls:
            controls.append(extra)

    counts = dict.fromkeys(SENSITIVITY_ORDER, 0)
    for classification in columns.values():
        counts[classification.sensitivity] += 1

    return {
        "sensitivity_level": level,
        "contains_pii": any(label.startswith("pii.") for label in labels),
        "contains_restricted_data": level == "restricted",
        "regulations_to_review": regulations,
        "classified_columns_by_sensitivity": {k: v for k, v in counts.items() if v},
        "required_controls": controls,
    }
