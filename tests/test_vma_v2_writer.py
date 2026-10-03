import hashlib

import pytest

from vma.models import VMAError
from vma.v2.constants import DESCRIPTOR_FIXED_SIZE_V2, HEADER_SIZE_V2, MAX_STREAMS_V2
from vma.v2.format_info import FILE_EXTENSION, MEDIA_TYPE, SOURCE_FILENAME, FormatInfoTLV
from vma.v2.reader import read_vma_v2
from vma.v2.wire import unpack_descriptor, unpack_header
from vma.v2.writer import V2StreamInput, create_vma_v2, write_vma_v2


def _source(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _stream(tmp_path, stream_id, data=b"payload", **updates):
    return V2StreamInput(stream_id=stream_id, source_path=_source(tmp_path, f"{stream_id}.bin", data), **updates)


def _payload_bytes(container_path, descriptor):
    raw = container_path.read_bytes()
    return raw[descriptor.payload_offset : descriptor.payload_offset + descriptor.payload_size]


def test_writer_creates_a_minimal_valid_v2_file(tmp_path):
    output = create_vma_v2([], tmp_path / "minimal.vma")
    result = read_vma_v2(output)
    assert output.exists()
    assert output.stat().st_size == HEADER_SIZE_V2
    assert result.metadata is None
    assert result.streams == ()


def test_writer_multiple_streams_preserves_arbitrary_binary_payloads_and_semantic_round_trip(tmp_path):
    first = _stream(tmp_path, 7, b"\x00\xff\x10binary\x00", role=0xFFFE, format_id=0xF000, start_time=42, duration=0)
    second = _stream(tmp_path, 2, bytes(range(256)), role=0x0001, format_id=0x2000, duration=99)
    metadata = {"schema_version": 1, "title": "Opaque"}
    output = create_vma_v2([first, second], tmp_path / "multiple.vma", metadata=metadata)
    result = read_vma_v2(output)

    assert result.metadata == metadata
    assert [stream.descriptor.stream_id for stream in result.streams] == [2, 7]
    expected = {7: first.source_path.read_bytes(), 2: second.source_path.read_bytes()}
    for stream in result.streams:
        descriptor = stream.descriptor
        assert hashlib.sha256(_payload_bytes(output, descriptor)).digest() == hashlib.sha256(expected[descriptor.stream_id]).digest()
    assert result.streams[0].descriptor.format_id == 0x2000
    assert result.streams[1].descriptor.role == 0xFFFE
    assert result.streams[1].descriptor.start_time == 42
    assert result.streams[1].descriptor.duration == 0


def test_writer_sorts_descriptors_but_keeps_caller_payload_order(tmp_path):
    high = _stream(tmp_path, 9, b"high")
    low = _stream(tmp_path, 1, b"low")
    output = create_vma_v2([high, low], tmp_path / "ordered.vma")
    raw = output.read_bytes()
    header = unpack_header(raw)
    first_descriptor = unpack_descriptor(raw, header.descriptor_table_offset)
    second_descriptor = unpack_descriptor(raw, header.descriptor_table_offset + DESCRIPTOR_FIXED_SIZE_V2)
    assert [first_descriptor.stream_id, second_descriptor.stream_id] == [1, 9]
    assert _payload_bytes(output, second_descriptor) == b"high"
    assert _payload_bytes(output, first_descriptor) == b"low"
    assert second_descriptor.payload_offset < first_descriptor.payload_offset


def test_writer_integrates_format_info_and_zero_flags_reserved_fields(tmp_path):
    stream = _stream(
        tmp_path,
        1,
        b"opaque",
        format_info=(
            FormatInfoTLV(SOURCE_FILENAME, b"source.bin"),
            FormatInfoTLV(MEDIA_TYPE, b"application/octet-stream"),
            FormatInfoTLV(FILE_EXTENSION, b"bin"),
        ),
    )
    output = write_vma_v2([stream], tmp_path / "info.vma")
    result = read_vma_v2(output)
    descriptor = result.streams[0].descriptor
    assert descriptor.stream_flags == descriptor.reserved == 0
    assert result.streams[0].format_info == (
        b"\x01\x0a\x00source.bin"
        b"\x02\x18\x00application/octet-stream"
        b"\x03\x03\x00bin"
    )


def test_writer_accepts_maximum_64_streams(tmp_path):
    streams = [_stream(tmp_path, index + 1, b"") for index in range(MAX_STREAMS_V2)]
    result = read_vma_v2(create_vma_v2(streams, tmp_path / "64.vma"))
    assert len(result.streams) == MAX_STREAMS_V2


def test_writer_rejects_more_than_64_streams(tmp_path):
    streams = [_stream(tmp_path, index + 1, b"") for index in range(MAX_STREAMS_V2 + 1)]
    with pytest.raises(VMAError, match="stream count exceeds"):
        create_vma_v2(streams, tmp_path / "65.vma")


@pytest.mark.parametrize(
    "stream, message",
    [
        (lambda tmp: _stream(tmp, 0), "stream ID"),
        (lambda tmp: _stream(tmp, 1, stream_flags=1), "flags and reserved"),
        (lambda tmp: _stream(tmp, 1, reserved=1), "flags and reserved"),
        (lambda tmp: _stream(tmp, 1, role=0x10000), "role"),
        (lambda tmp: _stream(tmp, 1, format_id=0x10000), "format ID"),
        (lambda tmp: _stream(tmp, 1, start_time=-1), "non-negative start"),
        (lambda tmp: _stream(tmp, 1, format_info=(FormatInfoTLV(0x04, b"x"),)), "FORMAT_INFO"),
    ],
)
def test_writer_rejects_invalid_stream_inputs(tmp_path, stream, message):
    with pytest.raises(VMAError, match=message):
        create_vma_v2([stream(tmp_path)], tmp_path / "invalid.vma")


def test_writer_rejects_duplicate_stream_ids(tmp_path):
    with pytest.raises(VMAError, match="stream IDs must be unique"):
        create_vma_v2([_stream(tmp_path, 1, b"first"), _stream(tmp_path, 1, b"second")], tmp_path / "duplicate.vma")


@pytest.mark.parametrize(
    "metadata, message",
    [
        ({}, "schema_version"),
        ({"schema_version": 2}, "schema_version"),
        ({"schema_version": True}, "schema_version"),
    ],
)
def test_writer_rejects_invalid_metadata(tmp_path, metadata, message):
    with pytest.raises(VMAError, match=message):
        create_vma_v2([], tmp_path / "bad-metadata.vma", metadata=metadata)


def test_writer_output_has_exact_header_and_descriptor_sizes(tmp_path):
    output = create_vma_v2([_stream(tmp_path, 1, b"x")], tmp_path / "sizes.vma")
    raw = output.read_bytes()
    header = unpack_header(raw)
    assert header.header_size == HEADER_SIZE_V2
    assert header.descriptor_table_size == DESCRIPTOR_FIXED_SIZE_V2
    assert header.descriptor_table_offset == HEADER_SIZE_V2
