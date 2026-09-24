"""Тесты моделей и FreqType операторов."""
import pytest
from rb_wordstat.core.models import FreqType, WordstatParams, ALL_FREQ_TYPES


class TestFreqTypeApply:
    def test_broad_returns_query_unchanged(self):
        assert FreqType.broad.apply("купить диван") == "купить диван"

    def test_phrase_wraps_in_quotes(self):
        assert FreqType.phrase.apply("купить диван") == '"купить диван"'

    def test_exact_adds_exclamation_to_each_word(self):
        assert FreqType.exact.apply("купить угловой диван") == '"!купить !угловой !диван"'

    def test_exact_single_word(self):
        assert FreqType.exact.apply("диван") == '"!диван"'

    def test_exact_ord_wraps_in_square_brackets(self):
        assert FreqType.exact_ord.apply("купить угловой диван") == '"[!купить !угловой !диван]"'

    def test_exact_ord_single_word(self):
        assert FreqType.exact_ord.apply("диван") == '"[!диван]"'

    def test_all_freq_types_covered(self):
        query = "тест запрос"
        for ft in ALL_FREQ_TYPES:
            result = ft.apply(query)
            assert isinstance(result, str)
            assert len(result) > 0


class TestFreqTypeLabel:
    def test_labels_exist(self):
        for ft in FreqType:
            assert isinstance(ft.label, str)
            assert len(ft.label) > 0


class TestWordstatParams:
    def test_default_lr(self):
        params = WordstatParams(query="диван")
        assert params.lr == 213

    def test_default_freq_is_broad(self):
        params = WordstatParams(query="диван")
        assert params.freq == [FreqType.broad]

    def test_get_queries_string(self):
        params = WordstatParams(query="купить диван")
        assert params.get_queries() == ["купить диван"]

    def test_get_queries_list(self):
        params = WordstatParams(query=["диван", "кресло", "стол"])
        assert params.get_queries() == ["диван", "кресло", "стол"]

    def test_custom_lr(self):
        params = WordstatParams(query="такси", lr=2)
        assert params.lr == 2

    def test_custom_freq(self):
        params = WordstatParams(
            query="диван",
            freq=[FreqType.broad, FreqType.phrase, FreqType.exact],
        )
        assert len(params.freq) == 3
        assert FreqType.phrase in params.freq
