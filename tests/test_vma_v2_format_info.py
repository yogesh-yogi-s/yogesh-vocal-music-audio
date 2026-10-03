import pytest

from vma.v2.format_info import (
    FILE_EXTENSION,
    MEDIA_TYPE,
    SOURCE_FILENAME,
    FormatInfoError,
    FormatInfoTLV,
    parse_format_info,
    serialize_format_info,
)


@pytest.mark.parametrize(
    "tlv",
    [
        FormatInfoTLV(SOURCE_FILENAME, "vocal ü.wav".encode()),
        FormatInfoTLV(MEDIA_TYPE, b"audio/wav"),
        FormatInfoTLV(FILE_EXTENSION, b"wav"),
    ],
)
def test_each_defined_tlv_round_trips(tlv):
    encoded = serialize_format_info([tlv])
    assert parse_format_info(encoded).tlvs == (tlv,)


def test_tlv_uses_exact_little_endian_length_bytes():
    tlv = FormatInfoTLV(SOURCE_FILENAME, b"abcde")
    assert serialize_format_info([tlv]) == b"\x01\x05\x00abcde"


def test_multiple_tlvs_preserve_input_order_without_canonicalization():
    tlvs = (
        FormatInfoTLV(FILE_EXTENSION, b"wav"),
        FormatInfoTLV(SOURCE_FILENAME, b"vocal.wav"),
        FormatInfoTLV(MEDIA_TYPE, b"audio/wav"),
    )
    assert parse_format_info(serialize_format_info(tlvs)).tlvs == tlvs


def test_empty_format_info_is_valid():
    parsed = parse_format_info(b"", format_info_size=0)
    assert parsed.tlvs == ()
    assert not parsed.has_unknown_critical_tlv
    assert serialize_format_info(()) == b""


def test_unknown_non_critical_tlv_is_preserved_and_semantically_ignored():
    tlv = FormatInfoTLV(0x7F, b"opaque")
    parsed = parse_format_info(b"\x7f\x06\x00opaque")
    assert parsed.tlvs == (tlv,)
    assert not parsed.has_unknown_critical_tlv


def test_unknown_critical_tlv_is_preserved_without_structural_failure():
    tlv = FormatInfoTLV(0xFF, b"opaque")
    parsed = parse_format_info(b"\xff\x06\x00opaque")
    assert parsed.tlvs == (tlv,)
    assert parsed.has_unknown_critical_tlv


def test_reserved_non_critical_type_is_accepted():
    parsed = parse_format_info(b"\x04\x01\x00x")
    assert parsed.tlvs == (FormatInfoTLV(0x04, b"x"),)


def test_reserved_critical_type_is_accepted_and_marked_unsupported_semantically():
    parsed = parse_format_info(b"\x84\x01\x00x")
    assert parsed.tlvs == (FormatInfoTLV(0x84, b"x"),)
    assert parsed.has_unknown_critical_tlv


def test_truncated_tlv_header_is_rejected():
    with pytest.raises(FormatInfoError, match="truncated FORMAT_INFO TLV header"):
        parse_format_info(b"\x01\x00")


def test_truncated_tlv_value_is_rejected():
    with pytest.raises(FormatInfoError, match="truncated FORMAT_INFO TLV value"):
        parse_format_info(b"\x01\x02\x00x")


def test_declared_length_cannot_overrun_format_info_boundary():
    with pytest.raises(FormatInfoError, match="truncated FORMAT_INFO TLV value"):
        parse_format_info(b"\x7f\x02\x00x", format_info_size=4)


def test_invalid_utf8_source_filename_is_rejected():
    with pytest.raises(FormatInfoError, match="SOURCE_FILENAME must be valid UTF-8"):
        parse_format_info(b"\x01\x01\x00\xff")


def test_source_filename_accepts_a_utf8_basename_and_rejects_path_separators():
    basename = "vocal ü.wav".encode("utf-8")
    assert parse_format_info(bytes((SOURCE_FILENAME, len(basename), 0)) + basename).tlvs == (FormatInfoTLV(SOURCE_FILENAME, basename),)
    for value in (b"directory/file.wav", b"directory\\file.wav"):
        data = bytes((SOURCE_FILENAME, len(value), 0)) + value
        with pytest.raises(FormatInfoError, match="basename"):
            parse_format_info(data)


@pytest.mark.parametrize(
    "data, message",
    [
        (b"\x01\x00\x00", "SOURCE_FILENAME must be non-empty"),
        (b"\x02\x00\x00", "MEDIA_TYPE must be non-empty"),
        (b"\x03\x00\x00", "FILE_EXTENSION must be non-empty"),
    ],
)
def test_empty_required_text_is_rejected(data, message):
    with pytest.raises(FormatInfoError, match=message):
        parse_format_info(data)


@pytest.mark.parametrize(
    "data, message",
    [
        (b"\x02\x01\x00\xff", "MEDIA_TYPE must be valid ASCII"),
        (b"\x03\x01\x00\xff", "FILE_EXTENSION must be valid ASCII"),
    ],
)
def test_invalid_ascii_is_rejected(data, message):
    with pytest.raises(FormatInfoError, match=message):
        parse_format_info(data)


def test_file_extension_with_leading_dot_is_rejected():
    with pytest.raises(FormatInfoError, match="FILE_EXTENSION must not begin with a dot"):
        parse_format_info(b"\x03\x04\x00.wav")


def test_format_info_size_must_match_the_exact_supplied_block_boundary():
    block = b"\x01\x01\x00x"
    assert parse_format_info(block, format_info_size=len(block)).tlvs == (FormatInfoTLV(1, b"x"),)
    with pytest.raises(FormatInfoError, match="FORMAT_INFO boundary"):
        parse_format_info(block + b"\x00", format_info_size=len(block))


def test_serializer_rejects_unknown_writer_tlvs_but_accepts_known_critical_base_type():
    with pytest.raises(FormatInfoError, match="defined V2 TLV types"):
        serialize_format_info([FormatInfoTLV(0x04, b"x")])
    assert serialize_format_info([FormatInfoTLV(0x81, b"vocal.wav")]) == b"\x81\x09\x00vocal.wav"
