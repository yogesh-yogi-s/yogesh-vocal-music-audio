import pytest

from vma.v2.constants import (
    DESCRIPTOR_FIXED_SIZE_V2,
    DESCRIPTOR_STRUCT_V2,
    HEADER_SIZE_V2,
    HEADER_STRUCT_V2,
    MAGIC,
    MAX_STREAMS_V2,
    VERSION_V2,
)
from vma.v2.models import V2Header, V2StreamDescriptor
from vma.v2.wire import V2WireError, pack_descriptor, pack_header, unpack_descriptor, unpack_header


def test_v2_fixed_wire_sizes_match_specification():
    assert HEADER_SIZE_V2 == 56
    assert HEADER_STRUCT_V2.size == 56
    assert DESCRIPTOR_FIXED_SIZE_V2 == 48
    assert DESCRIPTOR_STRUCT_V2.size == 48
    assert MAX_STREAMS_V2 == 64


def test_header_pack_unpack_round_trip_and_exact_little_endian_bytes():
    header = V2Header(
        magic=MAGIC,
        version=VERSION_V2,
        header_size=HEADER_SIZE_V2,
        stream_count=2,
        header_flags=0,
        metadata_offset=56,
        metadata_size=0x0102030405060708,
        descriptor_table_offset=0x1112131415161718,
        descriptor_table_size=0x2122232425262728,
        reserved_1=0,
        reserved_2=0,
    )
    expected = bytes.fromhex(
        "564d4146"  # VMAF
        "0200"      # version
        "3800"      # header size
        "02000000"  # stream count
        "00000000"  # header flags
        "3800000000000000"
        "0807060504030201"
        "1817161514131211"
        "2827262524232221"
        "00000000"
        "00000000"
    )
    packed = pack_header(header)
    assert packed == expected
    assert len(packed) == HEADER_SIZE_V2
    assert unpack_header(packed) == header


def test_descriptor_pack_unpack_round_trip_and_exact_little_endian_bytes():
    descriptor = V2StreamDescriptor(
        stream_id=0x01020304,
        role=0x0506,
        stream_flags=0,
        format_id=0x0708,
        reserved=0x090A,
        start_time=-2,
        duration=0x1112131415161718,
        payload_offset=0x2122232425262728,
        payload_size=0x3132333435363738,
        format_info_size=0x41424344,
    )
    expected = bytes.fromhex(
        "04030201"
        "0605"
        "0000"
        "0807"
        "0a09"
        "feffffffffffffff"
        "1817161514131211"
        "2827262524232221"
        "3837363534333231"
        "44434241"
    )
    packed = pack_descriptor(descriptor)
    assert packed == expected
    assert len(packed) == DESCRIPTOR_FIXED_SIZE_V2
    assert unpack_descriptor(packed) == descriptor


def test_header_boundary_integer_values_round_trip():
    header = V2Header(
        magic=b"\xff\x00\x80\x7f",
        version=0xFFFF,
        header_size=0xFFFF,
        stream_count=0xFFFFFFFF,
        header_flags=0xFFFFFFFF,
        metadata_offset=0xFFFFFFFFFFFFFFFF,
        metadata_size=0xFFFFFFFFFFFFFFFF,
        descriptor_table_offset=0xFFFFFFFFFFFFFFFF,
        descriptor_table_size=0xFFFFFFFFFFFFFFFF,
        reserved_1=0xFFFFFFFF,
        reserved_2=0xFFFFFFFF,
    )
    assert unpack_header(pack_header(header)) == header


@pytest.mark.parametrize("start_time", [-0x8000000000000000, -1, 0, 0x7FFFFFFFFFFFFFFF])
def test_descriptor_signed_start_time_boundary_values_round_trip(start_time):
    descriptor = V2StreamDescriptor(
        stream_id=0xFFFFFFFF,
        role=0xFFFF,
        stream_flags=0xFFFF,
        format_id=0xFFFF,
        reserved=0xFFFF,
        start_time=start_time,
        duration=0xFFFFFFFFFFFFFFFF,
        payload_offset=0xFFFFFFFFFFFFFFFF,
        payload_size=0xFFFFFFFFFFFFFFFF,
        format_info_size=0xFFFFFFFF,
    )
    assert unpack_descriptor(pack_descriptor(descriptor)) == descriptor


def test_wire_layer_preserves_nonzero_reserved_and_flag_values_without_validation():
    header = V2Header(MAGIC, VERSION_V2, 56, 1, 7, 56, 0, 56, 48, 8, 9)
    descriptor = V2StreamDescriptor(1, 0x9999, 3, 0xEEEE, 4, 0, 0, 104, 5, 0)
    assert unpack_header(pack_header(header)) == header
    assert unpack_descriptor(pack_descriptor(descriptor)) == descriptor


@pytest.mark.parametrize(
    ("unpacker", "size", "label"),
    [
        (unpack_header, HEADER_SIZE_V2, "header"),
        (unpack_descriptor, DESCRIPTOR_FIXED_SIZE_V2, "descriptor"),
    ],
)
def test_truncated_fixed_wire_data_is_rejected(unpacker, size, label):
    with pytest.raises(V2WireError, match=f"truncated V2 {label}"):
        unpacker(b"\x00" * (size - 1))


def test_fixed_wire_structures_can_be_read_at_a_nonzero_offset():
    header = V2Header(MAGIC, 2, 56, 0, 0, 56, 0, 56, 0, 0, 0)
    descriptor = V2StreamDescriptor(1, 0, 0, 0, 0, -1, 0, 104, 0, 3)
    assert unpack_header(b"prefix" + pack_header(header), len(b"prefix")) == header
    assert unpack_descriptor(b"x" + pack_descriptor(descriptor), 1) == descriptor
