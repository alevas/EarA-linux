import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from eara import audio


class AudioTests(unittest.TestCase):
    def test_reload_skipped_without_force(self):
        with patch("eara.audio.subprocess.run") as run:
            audio.reload_bluetooth_modules(force=False)
            run.assert_not_called()

    def test_pulse_override_appends_existing_config(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            pulse_dir = home / ".config" / "pulse"
            pulse_dir.mkdir(parents=True)
            target = pulse_dir / "default.pa"
            target.write_text("load-module module-null-sink\n", encoding="utf-8")
            with patch.object(audio.Path, "home", return_value=home):
                audio._write_pulse_override()
                text = target.read_text(encoding="utf-8")
            self.assertIn("module-null-sink", text)
            self.assertIn("eara: keep A2DP", text)

    def test_find_sink_matches_pipewire_names(self):
        sinks = "718\tbluez_output.3C:B0:ED:F4:B6:C3\tPipeWire\tfloat32le 2ch 48000Hz\tSUSPENDED\n"
        with patch.object(audio, "_pactl", return_value=sinks):
            self.assertEqual(audio.find_sink("3C:B0:ED:F4:B6:C3"), "bluez_output.3C:B0:ED:F4:B6:C3")

    def test_find_sink_matches_pulseaudio_names(self):
        sinks = "3\tbluez_sink.3C_B0_ED_F4_B6_C3.a2dp_sink\tmodule-bluez5-device.c\ts16le 2ch 44100Hz\tRUNNING\n"
        with patch.object(audio, "_pactl", return_value=sinks):
            self.assertEqual(audio.find_sink("3C:B0:ED:F4:B6:C3"), "bluez_sink.3C_B0_ED_F4_B6_C3.a2dp_sink")

    def test_find_sink_ignores_other_devices(self):
        sinks = "718\tbluez_output.AA:BB:CC:DD:EE:FF\tPipeWire\tfloat32le 2ch 48000Hz\tRUNNING\n"
        with patch.object(audio, "_pactl", return_value=sinks):
            self.assertIsNone(audio.find_sink("3C:B0:ED:F4:B6:C3"))

    def test_find_source_skips_monitor_on_pipewire(self):
        sources = (
            "1\tbluez_output.3C:B0:ED:F4:B6:C3.monitor\tPipeWire\tfloat32le 2ch 48000Hz\tSUSPENDED\n"
            "2\tbluez_input.3C:B0:ED:F4:B6:C3\tPipeWire\tfloat32le 1ch 16000Hz\tSUSPENDED\n"
        )
        with patch.object(audio, "_pactl", return_value=sources):
            self.assertEqual(audio.find_source("3C:B0:ED:F4:B6:C3"), "bluez_input.3C:B0:ED:F4:B6:C3")


if __name__ == "__main__":
    unittest.main()
