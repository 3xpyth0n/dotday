import copy

from dotday import DEFAULT_CONFIG, merge_dict


def test_merge_dict_nested():
    base = copy.deepcopy(DEFAULT_CONFIG)
    override = {"display": {"language": "fr"}, "colors": {"background": "#000000"}}
    merged = merge_dict(base, override)
    assert merged["display"]["language"] == "fr"
    assert merged["colors"]["background"] == "#000000"
