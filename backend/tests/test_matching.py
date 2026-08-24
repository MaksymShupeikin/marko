from marko.services.matching import (
    brands_compatible,
    laterality_conflict,
    normalize_tokens,
    token_similarity,
)


# normalize_tokens

def test_normalize_tokens_none_returns_empty():
    assert normalize_tokens(None) == []


def test_normalize_tokens_drops_stopwords_and_single_chars():
    assert normalize_tokens("Фара для BMW і X") == ["фара", "bmw"]


def test_normalize_tokens_lowercases():
    assert normalize_tokens("Bosch ФАРА") == ["bosch", "фара"]


# token_similarity

def testtoken_similarity_identical_is_one():
    assert token_similarity({"a", "b"}, {"a", "b"}) == 1.0


def testtoken_similarity_disjoint_is_zero():
    assert token_similarity({"a"}, {"b"}) == 0.0


def testtoken_similarity_empty_is_zero():
    assert token_similarity(set(), {"a"}) == 0.0


def testtoken_similarity_blends_jaccard_and_containment():
    assert token_similarity({"a", "b"}, {"a", "b", "c", "d"}) == 0.75


# laterality_conflict

def test_laterality_conflict_left_vs_right():
    assert laterality_conflict(["лівий"], ["правий"]) is True


def test_laterality_conflict_front_vs_rear():
    assert laterality_conflict(["передній"], ["задній"]) is True


def test_laterality_conflict_same_side_is_false():
    assert laterality_conflict(["лівий"], ["лівий"]) is False


def test_laterality_conflict_unspecified_is_false():
    assert laterality_conflict(["фара"], ["правий"]) is False


# brands_compatible

def test_brands_compatible_equal():
    assert brands_compatible("Bosch", "bosch") is True


def test_brands_compatible_missing_one_side():
    assert brands_compatible("Bosch", None) is True


def test_brands_compatible_different_brands():
    assert brands_compatible("Bosch", "Sachs") is False
