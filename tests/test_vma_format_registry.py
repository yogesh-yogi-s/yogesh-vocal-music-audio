import pytest

from vma.formats import (
    FORMAT_REGISTRY,
    FormatEntry,
    FormatIdRange,
    FormatRegistry,
    RegistryError,
    RegistryStatus,
    classify_format_id,
)


def _entry(format_id=0x1001, canonical_name="VMA_TEST", **updates):
    fields = dict(
        format_id=format_id,
        canonical_name=canonical_name,
        reference="tests: explicit fixture allocation",
        status=RegistryStatus.PROVISIONAL,
    )
    fields.update(updates)
    return FormatEntry(**fields)


@pytest.mark.parametrize(
    ("format_id", "expected"),
    [
        (0x0000, FormatIdRange.UNKNOWN),
        (0x0001, FormatIdRange.STANDARDIZED_EXTERNAL),
        (0x0FFF, FormatIdRange.STANDARDIZED_EXTERNAL),
        (0x1000, FormatIdRange.VMA_DEFINED),
        (0x1FFF, FormatIdRange.VMA_DEFINED),
        (0x2000, FormatIdRange.RESERVED),
        (0xEFFF, FormatIdRange.RESERVED),
        (0xF000, FormatIdRange.PRIVATE_EXPERIMENTAL),
        (0xFFFE, FormatIdRange.PRIVATE_EXPERIMENTAL),
        (0xFFFF, FormatIdRange.FUTURE_ESCAPE),
    ],
)
def test_v2_format_registry_classifies_all_authoritative_ranges(format_id, expected):
    assert classify_format_id(format_id) is expected


@pytest.mark.parametrize("format_id", [-1, 0x10000, "1"])
def test_v2_format_registry_rejects_non_u16_lookup_ids(format_id):
    with pytest.raises(RegistryError, match="unsigned 16-bit"):
        classify_format_id(format_id)


def test_v2_format_registry_lookup_resolves_approved_riff_wave_and_preserves_unknown_ids():
    known = FORMAT_REGISTRY.lookup(0x1000)
    assert known.known
    assert known.range is FormatIdRange.VMA_DEFINED
    assert known.entry is not None
    assert known.entry.canonical_name == "RIFF_WAVE"
    assert known.entry.status is RegistryStatus.APPROVED
    assert known.entry.media_type == "audio/vnd.wave"
    assert "Microsoft RIFF" in known.entry.reference
    assert "IANA WAVE" in known.entry.reference

    for format_id, expected_range in ((0, FormatIdRange.UNKNOWN), (0x2000, FormatIdRange.RESERVED), (0xF000, FormatIdRange.PRIVATE_EXPERIMENTAL)):
        result = FORMAT_REGISTRY.lookup(format_id)
        assert result.format_id == format_id
        assert result.range is expected_range
        assert result.entry is None
        assert not result.known


def test_v2_format_registry_append_is_explicit_deterministic_and_does_not_mutate_prior_registry():
    first = _entry(0x1001, "VMA_FIRST")
    second = _entry(0x1002, "VMA_SECOND", media_type="application/example")
    registry = FormatRegistry().append(first).append(second)
    assert tuple(entry.format_id for entry in FORMAT_REGISTRY.entries) == (0x1000,)
    assert registry.entries == (first, second)
    assert registry.lookup(0x1002).entry is second
    assert registry.lookup(0x1002).known


@pytest.mark.parametrize(
    "entries, message",
    [
        ((_entry(), _entry(canonical_name="VMA_OTHER")), "cannot be reassigned"),
        ((_entry(), _entry(0x1002, canonical_name="VMA_TEST")), "canonical names"),
        ((_entry(0x2000),), "limited to"),
        ((_entry(canonical_name=""),), "canonical_name"),
        ((_entry(reference=""),), "canonical_name and reference"),
        ((_entry(status="approved"),), "registry status"),
        ((_entry(media_type=""),), "media_type"),
    ],
)
def test_v2_format_registry_rejects_duplicate_or_incomplete_allocations(entries, message):
    with pytest.raises(RegistryError, match=message):
        FormatRegistry(entries)


def test_v2_format_registry_has_only_the_documented_riff_wave_allocation():
    assert tuple(entry.format_id for entry in FORMAT_REGISTRY.entries) == (0x1000,)
