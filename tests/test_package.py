"""Package import and version tests."""

import scene_grammar_kit


def test_package_import_and_version() -> None:
    """The package imports and exposes its declared version."""
    assert scene_grammar_kit.__version__ == "0.1.0"
