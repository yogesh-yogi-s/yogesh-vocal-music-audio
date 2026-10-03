import pytest

from conftest import discover_audio_fixture_cases
from vma import create_vma, extract_music, extract_vocal
from vma_test_support import pcm_payload


CASES = discover_audio_fixture_cases()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_lossless_round_trip_all_fixtures(tmp_path, case):
    """WAV -> VMA -> WAV must preserve the exact original PCM sample bytes."""
    container = create_vma(case.vocal_path, case.music_path, tmp_path / f"{case.name}.vma")
    extracted_vocal = extract_vocal(container, tmp_path / "vocal.wav")
    extracted_music = extract_music(container, tmp_path / "music.wav")
    for original, extracted in ((case.vocal_path, extracted_vocal), (case.music_path, extracted_music)):
        original_audio, original_pcm = pcm_payload(original)
        extracted_audio, extracted_pcm = pcm_payload(extracted)
        assert extracted_audio == original_audio
        assert extracted_pcm == original_pcm


def test_offset_fixture_has_physical_silence_but_not_vma_offset(tmp_path):
    case = next(case for case in CASES if case.name == "08_offset_example")
    audio, samples = pcm_payload(case.vocal_path)
    assert samples[: 2 * audio.sample_rate * audio.channels * audio.bytes_per_sample] == b"\0" * (2 * audio.sample_rate * audio.channels * audio.bytes_per_sample)
    assert create_vma(case.vocal_path, case.music_path, tmp_path / "offset.vma")
