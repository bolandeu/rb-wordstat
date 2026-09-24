"""Тесты CLI: _resolve_freq и предупреждения."""
import pytest
from unittest.mock import patch
from click.testing import CliRunner
import click

from rb_wordstat.cli import _resolve_freq, search
from rb_wordstat.core.models import FreqType, ALL_FREQ_TYPES


class TestResolveFreq:
    """Тесты функции _resolve_freq."""

    def test_single_value(self):
        assert _resolve_freq(("broad",)) == [FreqType.broad]

    def test_multiple_flags(self):
        result = _resolve_freq(("broad", "phrase"))
        assert result == [FreqType.broad, FreqType.phrase]

    def test_comma_separated(self):
        result = _resolve_freq(("broad,phrase",))
        assert result == [FreqType.broad, FreqType.phrase]

    def test_comma_separated_three(self):
        result = _resolve_freq(("broad,phrase,exact",))
        assert result == [FreqType.broad, FreqType.phrase, FreqType.exact]

    def test_comma_and_flag_mixed(self):
        result = _resolve_freq(("broad,phrase", "exact"))
        assert result == [FreqType.broad, FreqType.phrase, FreqType.exact]

    def test_all_expands_to_all_types(self):
        result = _resolve_freq(("all",))
        assert result == ALL_FREQ_TYPES

    def test_all_in_comma_list(self):
        result = _resolve_freq(("broad,all",))
        assert result == ALL_FREQ_TYPES

    def test_exact_ord_value(self):
        result = _resolve_freq(("exact-ord",))
        assert result == [FreqType.exact_ord]

    def test_deduplication(self):
        result = _resolve_freq(("broad,broad",))
        assert result == [FreqType.broad]

    def test_empty_defaults_to_broad(self):
        result = _resolve_freq(())
        assert result == [FreqType.broad]

    def test_invalid_value_raises(self):
        with pytest.raises(click.BadParameter):
            _resolve_freq(("invalid",))

    def test_whitespace_around_comma(self):
        result = _resolve_freq(("broad, phrase",))
        assert result == [FreqType.broad, FreqType.phrase]


class TestCliWarnings:
    """Тесты предупреждений CLI."""

    def _make_runner(self):
        return CliRunner()

    def test_no_warning_when_broad_included(self):
        runner = self._make_runner()

        with patch("rb_wordstat.cli.WordstatClient") as mock_client_cls:
            from rb_wordstat.core.models import WordstatResult
            mock_client = mock_client_cls.return_value
            mock_client.search_sync.return_value = [
                WordstatResult(
                    query="тест",
                    freq_type=FreqType.broad,
                    total_value=100,
                    popular=[],
                    associations=[],
                )
            ]
            with runner.isolated_filesystem():
                result = runner.invoke(
                    search,
                    ["тест", "--freq", "broad", "--output", "out.csv", "--csv-mode", "keywords"],
                )

        assert "Предупреждение" not in result.output

    def test_warning_when_keywords_mode_without_broad(self):
        runner = self._make_runner()

        with patch("rb_wordstat.cli.WordstatClient") as mock_client_cls:
            from rb_wordstat.core.models import WordstatResult
            mock_client = mock_client_cls.return_value
            mock_client.search_sync.return_value = [
                WordstatResult(
                    query="тест",
                    freq_type=FreqType.phrase,
                    total_value=50,
                    popular=[],
                    associations=[],
                )
            ]
            with runner.isolated_filesystem():
                result = runner.invoke(
                    search,
                    ["тест", "--freq", "phrase", "--output", "out.csv", "--csv-mode", "keywords"],
                )

        assert "Предупреждение" in result.output

    def test_no_warning_for_freq_csv_mode(self):
        runner = self._make_runner()

        with patch("rb_wordstat.cli.WordstatClient") as mock_client_cls:
            from rb_wordstat.core.models import WordstatResult
            mock_client = mock_client_cls.return_value
            mock_client.search_sync.return_value = [
                WordstatResult(
                    query="тест",
                    freq_type=FreqType.phrase,
                    total_value=50,
                    popular=[],
                    associations=[],
                )
            ]
            with runner.isolated_filesystem():
                result = runner.invoke(
                    search,
                    ["тест", "--freq", "phrase", "--output", "out.csv", "--csv-mode", "freq"],
                )

        assert "Предупреждение" not in result.output
