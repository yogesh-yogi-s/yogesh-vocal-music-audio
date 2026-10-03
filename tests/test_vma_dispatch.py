from io import BytesIO

import pytest

from vma import create_vma, read_vma
from vma.dispatch import read_vma_any
from vma.models import VMAError, VMAFile
from vma.v2.models import V2File
from vma.v2.writer import V2StreamInput, create_vma_v2


def _v2_file(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"opaque")
    return create_vma_v2([V2StreamInput(1, source)], tmp_path / "v2.vma")


def test_v2_dispatches_valid_v1_to_the_frozen_v1_reader_and_preserves_result(tmp_path, wav_pair):
    vocal, music, _, _ = wav_pair
    path = create_vma(vocal, music, tmp_path / "v1.vma")
    assert isinstance(read_vma_any(path), VMAFile)
    assert read_vma_any(path) == read_vma(path)


def test_v2_dispatches_valid_v2_to_v2_reader(tmp_path):
    assert isinstance(read_vma_any(_v2_file(tmp_path)), V2File)


@pytest.mark.parametrize(
    "payload, message",
    [
        (b"NOPE\x01\x00", "magic"),
        (b"VMAF", "too small"),
        (b"VMAF\x03\x00", "version 3"),
    ],
)
def test_v2_dispatch_rejects_invalid_or_unsupported_prefixes(tmp_path, payload, message):
    path = tmp_path / "invalid.vma"
    path.write_bytes(payload)
    with pytest.raises(VMAError, match=message):
        read_vma_any(path)


def test_v2_dispatch_interprets_version_as_little_endian(tmp_path):
    path = tmp_path / "big-endian-looking.vma"
    path.write_bytes(b"VMAF\x00\x01")
    with pytest.raises(VMAError, match="version 256"):
        read_vma_any(path)


def test_v2_dispatch_delegates_without_duplicating_reader_validation(tmp_path, monkeypatch):
    from vma import dispatch

    v1 = tmp_path / "v1-prefix.vma"
    v2 = tmp_path / "v2-prefix.vma"
    v1.write_bytes(b"VMAF\x01\x00")
    v2.write_bytes(b"VMAF\x02\x00")
    v1_result, v2_result = object(), object()
    calls = []

    monkeypatch.setattr(dispatch, "read_vma", lambda path: calls.append(("v1", path)) or v1_result)
    monkeypatch.setattr(dispatch, "read_vma_v2", lambda path: calls.append(("v2", path)) or v2_result)
    assert dispatch.read_vma_any(v1) is v1_result
    assert dispatch.read_vma_any(v2) is v2_result
    assert calls == [("v1", v1), ("v2", v2)]


def test_v2_dispatch_reads_only_six_bytes_before_routing(monkeypatch):
    from vma import dispatch

    reads = []

    class TrackingSource(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    class FakePath:
        def open(self, mode):
            assert mode == "rb"
            return TrackingSource(b"VMAF\x02\x00unread bytes")

    fake_path = FakePath()
    result = object()
    monkeypatch.setattr(dispatch, "Path", lambda value: fake_path)
    monkeypatch.setattr(dispatch, "read_vma_v2", lambda path: result)
    assert dispatch.read_vma_any("ignored") is result
    assert reads == [6]
