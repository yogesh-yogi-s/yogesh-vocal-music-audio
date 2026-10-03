from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any


class VMAError(ValueError):
    """Raised when a VMA or source WAV violates the v0.1 specification."""


class StreamType(IntEnum):
    VOCAL = 1
    MUSIC = 2


class Codec(IntEnum):
    PCM_WAV_LE = 1


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int
    channels: int
    bit_depth: int
    sample_count: int

    @property
    def bytes_per_sample(self) -> int:
        return self.bit_depth // 8

    @property
    def data_size(self) -> int:
        return self.sample_count * self.channels * self.bytes_per_sample

    @property
    def duration_seconds(self) -> float:
        return self.sample_count / self.sample_rate


@dataclass(frozen=True)
class StreamInfo:
    stream_id: int
    stream_type: StreamType
    codec: Codec
    audio: AudioFormat
    start_sample: int
    data_offset: int
    data_size: int

    @property
    def start_seconds(self) -> float:
        return self.start_sample / self.audio.sample_rate

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + self.audio.duration_seconds

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["stream_type"] = self.stream_type.name.lower()
        value["codec"] = self.codec.name
        value["duration_seconds"] = self.audio.duration_seconds
        value["start_seconds"] = self.start_seconds
        return value


@dataclass(frozen=True)
class VMAFile:
    path: Path
    version: int
    metadata: dict[str, Any]
    streams: tuple[StreamInfo, ...]

    @property
    def duration_seconds(self) -> float:
        return max((stream.end_seconds for stream in self.streams), default=0.0)

    def stream_for(self, stream_type: StreamType) -> StreamInfo:
        for stream in self.streams:
            if stream.stream_type == stream_type:
                return stream
        raise VMAError(f"VMA does not contain a {stream_type.name.lower()} stream")
