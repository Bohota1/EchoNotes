"""Audio capture sources and the LLM abstraction."""

from __future__ import annotations

import pytest

from app.capture.sources import (
    SOURCES,
    AudioCaptureSource,
    CapturedAudio,
    DummyCaptureSource,
    MicrophoneCaptureSource,
    UploadCaptureSource,
    describe_wav,
    get_capture_source,
    register_source,
)
from app.core.errors import AudioCaptureError


class TestDummySource:
    def test_reports_available_when_the_fixture_exists(self, fixture_wav):
        available, _ = DummyCaptureSource(fixture_wav).is_available()
        assert available

    def test_reports_unavailable_with_an_actionable_reason(self, tmp_path):
        available, reason = DummyCaptureSource(tmp_path / "missing.wav").is_available()
        assert not available
        assert "missing.wav" in reason

    def test_capture_returns_a_described_recording(self, fixture_wav):
        captured = DummyCaptureSource(fixture_wav).capture()
        assert isinstance(captured, CapturedAudio)
        assert captured.path.exists()
        assert captured.duration_seconds == pytest.approx(1.0, abs=0.05)
        assert captured.source == "dummy"

    def test_capture_copies_rather_than_moves_the_fixture(self, fixture_wav):
        DummyCaptureSource(fixture_wav).capture()
        assert fixture_wav.exists(), "the fixture must survive being captured"

    def test_each_capture_gets_its_own_id_and_file(self, fixture_wav):
        source = DummyCaptureSource(fixture_wav)
        first, second = source.capture(), source.capture()
        assert first.capture_id != second.capture_id
        assert first.path != second.path

    def test_missing_fixture_raises(self, tmp_path):
        with pytest.raises(AudioCaptureError):
            DummyCaptureSource(tmp_path / "nope.wav").capture()


class TestMicrophoneSource:
    def test_missing_dependency_is_reported_not_raised(self):
        # A machine with no PortAudio should get an explanation, not a crash.
        available, reason = MicrophoneCaptureSource().is_available()
        assert isinstance(available, bool)
        if not available:
            assert "sounddevice" in reason


class TestUploadSource:
    def test_writes_supplied_bytes(self, fixture_wav):
        captured = UploadCaptureSource(fixture_wav.read_bytes()).capture()
        assert captured.path.exists()
        assert captured.source == "upload"

    def test_empty_payload_raises(self):
        with pytest.raises(AudioCaptureError):
            UploadCaptureSource(b"").capture()


class TestRegistry:
    def test_ships_dummy_and_microphone(self):
        assert {"dummy", "microphone"} <= set(SOURCES)

    def test_unknown_source_raises_with_the_known_names(self):
        with pytest.raises(AudioCaptureError) as excinfo:
            get_capture_source("gpio-button")
        assert "dummy" in str(excinfo.value)

    def test_hardware_source_can_be_registered_later(self):
        # The whole point of the interface: a GPIO/serial source plugs in
        # without the pipeline changing.
        class FakeGPIOSource(AudioCaptureSource):
            name = "test-gpio"

            def capture(self, max_seconds=None):
                raise NotImplementedError

        try:
            register_source(FakeGPIOSource)
            assert isinstance(get_capture_source("test-gpio"), FakeGPIOSource)
        finally:
            SOURCES.pop("test-gpio", None)


class TestWavDescription:
    def test_reads_header(self, fixture_wav):
        duration, rate, channels = describe_wav(fixture_wav)
        assert rate == 16_000 and channels == 1
        assert duration == pytest.approx(1.0, abs=0.05)

    def test_non_wav_raises(self, tmp_path):
        bogus = tmp_path / "bogus.wav"
        bogus.write_bytes(b"not a wav file")
        with pytest.raises(AudioCaptureError):
            describe_wav(bogus)


class TestLLMAbstraction:
    def test_factory_always_returns_a_client(self):
        from app.llm import get_llm_client

        assert get_llm_client() is not None

    def test_unconfigured_client_reports_unavailable(self):
        from app.llm import get_llm_client

        assert get_llm_client().available is False

    def test_calling_an_unavailable_client_raises_the_typed_error(self):
        from app.llm import LLMUnavailableError, NullLLMClient

        with pytest.raises(LLMUnavailableError):
            NullLLMClient().complete("hello")

    @pytest.mark.parametrize(
        "raw",
        [
            '{"a": 1}',
            'Sure!\n```json\n{"a": 1}\n```',
            'noise before {"a": 1} noise after',
        ],
    )
    def test_json_is_recovered_from_wrapped_responses(self, raw):
        # Models wrap JSON in prose and code fences even when told not to.
        from app.llm import parse_json_response

        assert parse_json_response(raw) == {"a": 1}

    def test_unparseable_response_raises(self):
        from app.llm import LLMError, parse_json_response

        with pytest.raises(LLMError):
            parse_json_response("no json here at all")

    def test_fallbacks_return_none_when_no_provider(self):
        # Never the reason a capture fails.
        from app.understanding.llm_extract import classify_with_llm, extract_with_llm

        assert classify_with_llm("text") is None
        assert extract_with_llm("text") is None
