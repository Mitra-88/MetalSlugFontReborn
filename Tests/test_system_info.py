import re

from system_info import (
    APP_VERSION,
    build_date,
    get_system_info,
    join_parts,
    msfr_version,
    normalize_architecture,
    readable_size,
)


def test_version_embeds_a_stable_commit_identifier():
    assert msfr_version.startswith(f"{APP_VERSION} (")
    assert msfr_version.endswith(")")
    suffix = msfr_version[len(APP_VERSION) + 1 : -1]
    assert suffix and " " not in suffix


def test_build_date_has_release_date_format():
    assert re.match(r"^\d{4}-\d{2}-\d{2} \(", build_date)


def test_readable_size_units():
    assert readable_size(0) == "0 bytes"
    assert readable_size(100) == "100.00 bytes"
    assert readable_size(2048) == "2.00 KB"
    assert readable_size(5 * 1024**3) == "5.00 GB"


def test_readable_size_caps_at_largest_unit():
    assert readable_size(3 * 1024**4) == "3072.00 GB"


def test_normalize_architecture():
    assert normalize_architecture("x86_64") == "64-Bit"
    assert normalize_architecture("amd64") == "AMD64"
    assert normalize_architecture("aarch64") == "ARM64"
    assert normalize_architecture("ARM64") == "ARM64"
    assert normalize_architecture("ppc64le") == "ppc64le"


def test_join_parts_skips_missing_values():
    assert join_parts("a", None, "b") == "a b"
    assert join_parts(None, None) == ""
    assert join_parts() == ""


def test_get_system_info_returns_non_empty_string():
    info = get_system_info()
    assert isinstance(info, str) and info
