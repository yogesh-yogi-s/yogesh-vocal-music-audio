import hashlib

import pytest

from vma.models import VMAError
from vma.v2.extractor import extract_all_v2, extract_stream_v2
from vma.v2.format_info import FormatInfoTLV
from vma.v2.reader import read_vma_v2
from vma.v2.writer import V2StreamInput, create_vma_v2


def _source(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _container(tmp_path, streams):
    return create_vma_v2(streams, tmp_path / "opaque.vma")


def test_extract_one_payload_is_byte_for_byte_and_hash_equal_after_writer_reader_round_trip(tmp_path):
    source_bytes = b"\0\xff\x01opaque\0" + bytes(range(256))
    source = _source(tmp_path, "source.bin", source_bytes)
    container = _container(tmp_path, [V2StreamInput(1, source)])
    assert read_vma_v2(container).streams[0].descriptor.payload_size == len(source_bytes)

    extracted = extract_stream_v2(container, 1, tmp_path / "output.bin")
    assert extracted.read_bytes() == source_bytes
    assert hashlib.sha256(extracted.read_bytes()).digest() == hashlib.sha256(source_bytes).digest()


def test_extract_all_handles_multiple_adjacent_payloads_at_different_file_locations(tmp_path):
    first = b"first"
    second = bytes(range(64))
    third = b"last\0\xff"
    container = _container(
        tmp_path,
        [
            V2StreamInput(8, _source(tmp_path, "first.bin", first)),
            V2StreamInput(2, _source(tmp_path, "second.bin", second)),
            V2StreamInput(6, _source(tmp_path, "third.bin", third)),
        ],
    )
    parsed = read_vma_v2(container)
    ranges = [(stream.descriptor.payload_offset, stream.descriptor.payload_size) for stream in parsed.streams]
    assert ranges[2][0] < ranges[0][0]  # descriptors sorted; payloads retain caller order
    assert sorted(offset + size for offset, size in ranges)[:-1] == sorted(offset for offset, _ in ranges)[1:]

    outputs = {8: tmp_path / "eight.out", 2: tmp_path / "two.out", 6: tmp_path / "six.out"}
    result = extract_all_v2(container, outputs)
    assert result == (outputs[2], outputs[6], outputs[8])
    assert outputs[8].read_bytes() == first
    assert outputs[2].read_bytes() == second
    assert outputs[6].read_bytes() == third


def test_unknown_format_role_and_critical_format_info_do_not_prevent_extraction(tmp_path):
    source_bytes = b"opaque private stream"
    source = _source(tmp_path, "private.bin", source_bytes)
    container = _container(
        tmp_path,
        [
            V2StreamInput(
                1,
                source,
                role=0xFFFE,
                format_id=0xF000,
                duration=0,
                format_info=(FormatInfoTLV(0x81, b"source.bin"),),
            )
        ],
    )
    assert extract_stream_v2(container, 1, tmp_path / "private.out").read_bytes() == source_bytes


def test_invalid_stream_selection_and_extract_all_path_set_are_rejected(tmp_path):
    container = _container(tmp_path, [V2StreamInput(1, _source(tmp_path, "one.bin", b"one"))])
    with pytest.raises(VMAError, match="does not contain stream ID"):
        extract_stream_v2(container, 2, tmp_path / "missing.out")
    with pytest.raises(VMAError, match="output paths must specify"):
        extract_all_v2(container, {})


def test_invalid_and_truncated_containers_are_rejected_before_extraction(tmp_path):
    container = _container(tmp_path, [V2StreamInput(1, _source(tmp_path, "payload.bin", b"payload"))])
    raw = container.read_bytes()

    truncated = tmp_path / "truncated.vma"
    truncated.write_bytes(raw[:-1])
    with pytest.raises(VMAError, match="payload range is outside"):
        extract_stream_v2(truncated, 1, tmp_path / "truncated.out")

    invalid_range = tmp_path / "invalid-range.vma"
    invalid_range.write_bytes(raw[:-1])
    with pytest.raises(VMAError, match="payload range is outside"):
        extract_stream_v2(invalid_range, 1, tmp_path / "invalid.out")


def test_extractor_detects_a_container_truncated_after_structural_read(tmp_path, monkeypatch):
    source = _source(tmp_path, "race.bin", b"content")
    container = _container(tmp_path, [V2StreamInput(1, source)])

    from vma.v2 import extractor

    original_read = extractor.read_vma_v2

    def read_then_truncate(path):
        parsed = original_read(path)
        Path(path).write_bytes(Path(path).read_bytes()[:-1])
        return parsed

    from pathlib import Path

    monkeypatch.setattr(extractor, "read_vma_v2", read_then_truncate)
    with pytest.raises(VMAError, match="ended unexpectedly"):
        extractor.extract_stream_v2(container, 1, tmp_path / "race.out")
