import pytest

from vma.models import VMAError
from vma.v2 import validator
from vma.v2.models import V2Header
from vma.v2.wire import pack_header

from test_vma_v2_reader import _stream, _write_v2


def test_validator_returns_the_reader_result_for_valid_minimal_and_multi_stream_containers(tmp_path):
    minimal = _write_v2(tmp_path / "minimal.vma")
    assert validator.validate_vma_v2(minimal).streams == ()

    multiple = _write_v2(tmp_path / "multiple.vma", [_stream(2), _stream(1)])
    assert [stream.descriptor.stream_id for stream in validator.validate_vma_v2(multiple).streams] == [2, 1]


@pytest.mark.parametrize(
    "streams",
    [
        [_stream(1, format_id=0xF000)],
        [_stream(1, role=0xFFFE)],
        [_stream(1, format_info=b"\x7f\x01\x00x")],
        [_stream(1, format_info=b"\xff\x01\x00x")],
    ],
)
def test_validator_accepts_structurally_valid_unknown_values(tmp_path, streams):
    assert len(validator.validate_vma_v2(_write_v2(tmp_path / "opaque.vma", streams)).streams) == 1


@pytest.mark.parametrize(
    "streams, metadata, header_updates, message",
    [
        ((), None, {"header_flags": 1}, "flags and reserved"),
        ((), b"not-json", None, "metadata"),
        ([_stream(0)], None, None, "stream ID"),
        ([_stream(1), _stream(1)], None, None, "stream IDs"),
        ([_stream(1, stream_flags=1)], None, None, "stream flags"),
        ([_stream(1, payload=b"", payload_size=1)], None, None, "payload range"),
        ([_stream(1, b"abcd"), _stream(2, b"efgh", payload_offset=154)], None, None, "payload regions overlap"),
        ([_stream(1, format_info=b"\x7f\x02\x00x")], None, None, "FORMAT_INFO"),
    ],
)
def test_validator_delegates_all_structural_rejections(tmp_path, streams, metadata, header_updates, message):
    path = _write_v2(
        tmp_path / "invalid.vma", streams, metadata=metadata, header_updates=header_updates,
    )
    with pytest.raises(VMAError, match=message):
        validator.validate_vma_v2(path)


def test_validator_rejects_truncated_container(tmp_path):
    path = tmp_path / "truncated.vma"
    path.write_bytes(pack_header(V2Header(b"VMAF", 2, 56, 1, 0, 56, 0, 56, 48, 0, 0)))
    with pytest.raises(VMAError, match="descriptor table range"):
        validator.validate_vma_v2(path)


def test_validator_facade_delegates_to_v2_reader(monkeypatch, tmp_path):
    expected = object()
    observed = []

    def fake_reader(path):
        observed.append(path)
        return expected

    monkeypatch.setattr(validator, "read_vma_v2", fake_reader)
    path = tmp_path / "delegated.vma"
    assert validator.validate_vma_v2(path) is expected
    assert observed == [path]
