"""Pure-Python tests for the self-healing scorer + locator parser.

These do not require a browser and are wired into CI via ``pytest``.
"""
from __future__ import annotations

from selenium.webdriver.common.by import By

from libraries.SelfHealingPlugin import Fingerprint, score_fingerprints, split_locator


def _fp(**kwargs) -> Fingerprint:
    defaults = {"tag": "button", "text": "", "attrs": {}, "xpath": ""}
    defaults.update(kwargs)
    return Fingerprint(**defaults)


class TestScoreFingerprints:
    def test_identical_elements_score_one(self) -> None:
        fp = _fp(
            tag="button",
            text="Login",
            attrs={"id": "submit", "class": "primary cta", "type": "submit"},
        )
        assert score_fingerprints(fp, fp) == 1.0

    def test_tag_mismatch_scores_zero(self) -> None:
        primary = _fp(tag="button")
        candidate = _fp(tag="div")
        assert score_fingerprints(primary, candidate) == 0.0

    def test_matching_tag_alone_is_low(self) -> None:
        primary = _fp(tag="button")
        candidate = _fp(tag="button")
        assert score_fingerprints(primary, candidate) == 0.2

    def test_exact_attribute_match_boosts_score(self) -> None:
        primary = _fp(tag="input", attrs={"id": "username"})
        candidate = _fp(tag="input", attrs={"id": "username"})
        assert score_fingerprints(primary, candidate) == 0.2 + 0.2

    def test_class_jaccard_partial_overlap(self) -> None:
        primary = _fp(tag="button", attrs={"class": "btn primary cta"})
        candidate = _fp(tag="button", attrs={"class": "btn primary"})
        expected = 0.2 + 0.15 * (2 / 3)
        assert abs(score_fingerprints(primary, candidate) - expected) < 1e-9

    def test_text_exact_match_counts(self) -> None:
        primary = _fp(tag="a", text="Sign in")
        candidate = _fp(tag="a", text="Sign in")
        assert score_fingerprints(primary, candidate) == 0.2 + 0.25

    def test_text_substring_match_counts_less(self) -> None:
        primary = _fp(tag="a", text="Sign in")
        candidate = _fp(tag="a", text="Please Sign in here")
        assert abs(score_fingerprints(primary, candidate) - 0.3) < 1e-9

    def test_score_is_capped_at_one(self) -> None:
        primary = _fp(
            tag="button",
            text="Submit",
            attrs={
                "id": "submit",
                "name": "submit",
                "class": "btn",
                "role": "button",
                "data-testid": "submit",
                "type": "submit",
            },
        )
        assert score_fingerprints(primary, primary) == 1.0

    def test_empty_attrs_do_not_raise(self) -> None:
        primary = _fp(tag="div", attrs={"class": ""})
        candidate = _fp(tag="div", attrs={"class": ""})
        assert score_fingerprints(primary, candidate) == 0.2


class TestSplitLocator:
    def test_xpath_prefix(self) -> None:
        assert split_locator("xpath=//div[@id='a']") == (By.XPATH, "//div[@id='a']")

    def test_css_prefix(self) -> None:
        assert split_locator("css=.foo > .bar") == (By.CSS_SELECTOR, ".foo > .bar")

    def test_id_prefix(self) -> None:
        assert split_locator("id=username") == (By.ID, "username")

    def test_name_prefix(self) -> None:
        assert split_locator("name=email") == (By.NAME, "email")

    def test_implicit_xpath_by_leading_slashes(self) -> None:
        assert split_locator("//button") == (By.XPATH, "//button")

    def test_implicit_xpath_by_parenthesis(self) -> None:
        assert split_locator("(//button)[1]") == (By.XPATH, "(//button)[1]")

    def test_implicit_css_fallback(self) -> None:
        assert split_locator("div.card > button.primary") == (
            By.CSS_SELECTOR,
            "div.card > button.primary",
        )

    def test_unknown_prefix_falls_back_to_css(self) -> None:
        assert split_locator("weird=val") == (By.CSS_SELECTOR, "weird=val")


class TestFingerprint:
    def test_round_trip_to_dict(self) -> None:
        original = Fingerprint(
            tag="input",
            text="",
            attrs={"id": "email", "class": "form-control"},
            xpath="/html/body/form/input[1]",
            original_locator="id=email",
        )
        restored = Fingerprint.from_dict(original.to_dict())
        assert restored == original

    def test_from_dict_tolerates_missing_keys(self) -> None:
        fp = Fingerprint.from_dict({"tag": "button"})
        assert fp.tag == "button"
        assert fp.text == ""
        assert fp.attrs == {}
        assert fp.xpath == ""
