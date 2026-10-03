import json

import pytest

from vma.models import VMAError
from vma.v2.constants import (
    HEADER_SIZE_V2,
    MAGIC,
    MAX_FORMAT_INFO_BYTES_V2,
    MAX_METADATA_BYTES_V2,
    MAX_STREAMS_V2,
    VERSION_V2,
)
from vma.v2.models import V2Header, V2StreamDescriptor
from vma.v2.reader import read_vma_v2
from vma.v2.wire import pack_descriptor, pack_header


def _write_v2(path, stream_specs=(), *, metadata=None, payload_order=None, header_updates=None):
    metadata_bytes = b"" if metadata is None else (
        metadata if isinstance(metadata, bytes) else json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    )
    descriptor_table_offset = HEADER_SIZE_V2 + len(metadata_bytes)
    info_by_id = {spec["stream_id"]: spec.get("format_info", b"") for spec in stream_specs}
    table_size = sum(48 + len(info_by_id[spec["stream_id"]]) for spec in stream_specs)
    payload_order = payload_order or [spec["stream_id"] for spec in stream_specs]
    payload_by_id = {spec["stream_id"]: spec.get("payload", b"") for spec in stream_specs}
    cursor = descriptor_table_offset + table_size
    offsets = {}
    payload_bytes = bytearray()
    for stream_id in payload_order:
        offsets[stream_id] = cursor
        payload = payload_by_id[stream_id]
        payload_bytes.extend(payload)
        cursor += len(payload)

    descriptors = []
    for spec in stream_specs:
        stream_id = spec["stream_id"]
        payload = payload_by_id[stream_id]
        descriptors.append(
            V2StreamDescriptor(
                stream_id=stream_id,
                role=spec.get("role", 0),
                stream_flags=spec.get("stream_flags", 0),
                format_id=spec.get("format_id", 0),
                reserved=spec.get("reserved", 0),
                start_time=spec.get("start_time", 0),
                duration=spec.get("duration", 0),
                payload_offset=spec.get("payload_offset", offsets[stream_id]),
                payload_size=spec.get("payload_size", len(payload)),
                format_info_size=spec.get("format_info_size", len(info_by_id[stream_id])),
            )
        )
    table = b"".join(pack_descriptor(descriptor) + info_by_id[descriptor.stream_id] for descriptor in descriptors)
    header_values = dict(
        magic=MAGIC,
        version=VERSION_V2,
        header_size=HEADER_SIZE_V2,
        stream_count=len(stream_specs),
        header_flags=0,
        metadata_offset=HEADER_SIZE_V2,
        metadata_size=len(metadata_bytes),
        descriptor_table_offset=descriptor_table_offset,
        descriptor_table_size=len(table),
        reserved_1=0,
        reserved_2=0,
    )
    header_values.update(header_updates or {})
    path.write_bytes(pack_header(V2Header(**header_values)) + metadata_bytes + table + payload_bytes)
    return path


def _stream(stream_id, payload=b"data", **updates):
    return {"stream_id": stream_id, "payload": payload, **updates}


def test_reader_accepts_valid_minimal_v2_container(tmp_path):
    result = read_vma_v2(_write_v2(tmp_path / "minimal.vma"))
    assert result.header.version == VERSION_V2
    assert result.metadata is None
    assert result.streams == ()


def test_reader_accepts_multiple_opaque_streams_and_exact_metadata(tmp_path):
    metadata = {"schema_version": 1, "title": "Test"}
    result = read_vma_v2(
        _write_v2(tmp_path / "multiple.vma", [_stream(7, b"one"), _stream(2, b"two")], metadata=metadata)
    )
    assert result.metadata == metadata
    assert [stream.descriptor.stream_id for stream in result.streams] == [7, 2]
    assert [stream.format_info for stream in result.streams] == [b"", b""]


@pytest.mark.parametrize("metadata", [b"not json", b"[]", b"{}", b'{"schema_version":2}', b'{"schema_version":true}'])
def test_reader_rejects_invalid_present_metadata(tmp_path, metadata):
    path = _write_v2(tmp_path / "bad-metadata.vma", metadata=metadata)
    with pytest.raises(VMAError, match="V2 metadata"):
        read_vma_v2(path)


def _metadata_bytes_of_size(size):
    prefix = b'{"schema_version":1,"padding":"'
    suffix = b'"}'
    return prefix + b"x" * (size - len(prefix) - len(suffix)) + suffix


def _unknown_format_info_of_size(size):
    parts = []
    remaining = size
    while remaining:
        value_size = min(0xFFFF, remaining - 3)
        if value_size < 0:
            raise ValueError("FORMAT_INFO size cannot encode a TLV")
        parts.append(b"\x7f" + value_size.to_bytes(2, "little") + b"x" * value_size)
        remaining -= 3 + value_size
    return b"".join(parts)


def test_reader_enforces_metadata_limit_before_reading_and_accepts_the_exact_limit(tmp_path):
    accepted = _write_v2(tmp_path / "metadata-at-limit.vma", metadata=_metadata_bytes_of_size(MAX_METADATA_BYTES_V2))
    assert read_vma_v2(accepted).metadata["schema_version"] == 1

    rejected = _write_v2(tmp_path / "metadata-over-limit.vma", metadata=_metadata_bytes_of_size(MAX_METADATA_BYTES_V2 + 1))
    with pytest.raises(VMAError, match="metadata exceeds"):
        read_vma_v2(rejected)


def test_reader_enforces_individual_format_info_limit_and_accepts_the_exact_limit(tmp_path):
    at_limit = _unknown_format_info_of_size(MAX_FORMAT_INFO_BYTES_V2)
    accepted = _write_v2(tmp_path / "info-at-limit.vma", [_stream(1, format_info=at_limit)])
    assert read_vma_v2(accepted).streams[0].format_info == at_limit

    over_limit = _unknown_format_info_of_size(MAX_FORMAT_INFO_BYTES_V2 + 1)
    rejected = _write_v2(tmp_path / "info-over-limit.vma", [_stream(1, format_info=over_limit)])
    with pytest.raises(VMAError, match="FORMAT_INFO exceeds.*reference implementation limit"):
        read_vma_v2(rejected)


def test_reader_accepts_stream_count_64_and_rejects_65_before_descriptor_reads(tmp_path):
    valid = _write_v2(tmp_path / "64.vma", [_stream(index + 1, b"") for index in range(MAX_STREAMS_V2)])
    assert len(read_vma_v2(valid).streams) == MAX_STREAMS_V2

    too_many = tmp_path / "65.vma"
    header = V2Header(MAGIC, 2, 56, 65, 0, 56, 0, 56, 0, 0, 0)
    too_many.write_bytes(pack_header(header))
    with pytest.raises(VMAError, match="stream count exceeds"):
        read_vma_v2(too_many)


@pytest.mark.parametrize(
    "streams, message",
    [
        ([_stream(0)], "stream ID must be non-zero"),
        ([_stream(1), _stream(1)], "stream IDs must be unique"),
        ([_stream(1, stream_flags=1)], "stream flags and reserved"),
        ([_stream(1, reserved=1)], "stream flags and reserved"),
    ],
)
def test_reader_rejects_invalid_stream_identification_or_reserved_fields(tmp_path, streams, message):
    with pytest.raises(VMAError, match=message):
        read_vma_v2(_write_v2(tmp_path / "bad-stream.vma", streams))


@pytest.mark.parametrize("format_id", [0x0000, 0x2000, 0xF000, 0xFFFF])
def test_reader_preserves_unknown_reserved_and_private_format_ids(tmp_path, format_id):
    result = read_vma_v2(_write_v2(tmp_path / "opaque-format.vma", [_stream(1, format_id=format_id)]))
    assert result.streams[0].descriptor.format_id == format_id


def test_reader_preserves_unknown_role_and_zero_duration(tmp_path):
    result = read_vma_v2(_write_v2(tmp_path / "opaque-role.vma", [_stream(1, role=0xFFFE, duration=0)]))
    descriptor = result.streams[0].descriptor
    assert descriptor.role == 0xFFFE
    assert descriptor.duration == 0


@pytest.mark.parametrize(
    "header_updates, message",
    [
        ({"magic": b"NOPE"}, "magic"),
        ({"version": 1}, "version"),
        ({"header_size": 55}, "header size"),
        ({"header_flags": 1}, "flags and reserved"),
        ({"reserved_1": 1}, "flags and reserved"),
        ({"reserved_2": 1}, "flags and reserved"),
        ({"metadata_offset": 57}, "metadata offset"),
        ({"descriptor_table_offset": 57}, "descriptor table offset"),
    ],
)
def test_reader_rejects_invalid_header_fields(tmp_path, header_updates, message):
    with pytest.raises(VMAError, match=message):
        read_vma_v2(_write_v2(tmp_path / "bad-header.vma", header_updates=header_updates))


def test_reader_rejects_truncated_header_and_descriptor(tmp_path):
    header_path = tmp_path / "truncated-header.vma"
    header_path.write_bytes(b"VMAF\x02\x00")
    with pytest.raises(VMAError, match="fixed header"):
        read_vma_v2(header_path)

    descriptor_path = tmp_path / "truncated-descriptor.vma"
    header = V2Header(MAGIC, 2, 56, 1, 0, 56, 0, 56, 48, 0, 0)
    descriptor_path.write_bytes(pack_header(header) + b"\0" * 47)
    with pytest.raises(VMAError, match="descriptor table range"):
        read_vma_v2(descriptor_path)


def test_reader_rejects_truncated_format_info_and_malformed_tlv_boundary(tmp_path):
    truncated = _write_v2(
        tmp_path / "truncated-info.vma", [_stream(1, format_info=b"", format_info_size=1)]
    )
    with pytest.raises(VMAError, match="FORMAT_INFO exceeds"):
        read_vma_v2(truncated)

    malformed = _write_v2(tmp_path / "malformed-info.vma", [_stream(1, format_info=b"\x7f\x02\x00x")])
    with pytest.raises(VMAError, match="invalid V2 FORMAT_INFO"):
        read_vma_v2(malformed)


def test_reader_rejects_payload_outside_file_and_overlapping_payloads(tmp_path):
    outside = _write_v2(tmp_path / "outside.vma", [_stream(1, payload=b"", payload_size=1)])
    with pytest.raises(VMAError, match="payload range is outside"):
        read_vma_v2(outside)

    overlap = _write_v2(
        tmp_path / "overlap.vma",
        [_stream(1, b"abcd"), _stream(2, b"efgh", payload_offset=56 + 96 + 2)],
    )
    with pytest.raises(VMAError, match="payload regions overlap"):
        read_vma_v2(overlap)


@pytest.mark.parametrize(
    "payload_offset, message",
    [
        (0, "overlaps a container region"),
        (56, "overlaps a container region"),
    ],
)
def test_reader_rejects_payload_overlap_with_header_or_descriptor_table(tmp_path, payload_offset, message):
    path = _write_v2(tmp_path / "protected-overlap.vma", [_stream(1, payload_offset=payload_offset)])
    with pytest.raises(VMAError, match=message):
        read_vma_v2(path)


def test_reader_rejects_descriptor_table_size_with_extra_unconsumed_byte(tmp_path):
    path = _write_v2(tmp_path / "extra-table-byte.vma", [_stream(1)], header_updates={"descriptor_table_size": 49})
    with pytest.raises(VMAError, match="descriptor table size is inconsistent"):
        read_vma_v2(path)


def test_reader_accepts_adjacent_payloads_and_descriptor_order_different_from_payload_order(tmp_path):
    result = read_vma_v2(
        _write_v2(
            tmp_path / "ordered-differently.vma",
            [_stream(2, b"second"), _stream(1, b"first")],
            payload_order=[1, 2],
        )
    )
    assert [stream.descriptor.stream_id for stream in result.streams] == [2, 1]
    assert result.streams[0].descriptor.payload_offset > result.streams[1].descriptor.payload_offset


def test_reader_keeps_unknown_critical_format_info_opaque_and_readable(tmp_path):
    raw_info = b"\xff\x03\x00xyz"
    result = read_vma_v2(_write_v2(tmp_path / "critical.vma", [_stream(1, format_info=raw_info)]))
    assert result.streams[0].format_info == raw_info
