import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from eara import i18n

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from eara import gui
except (ImportError, ValueError):
    gui = None


class PowerOffOnExitTests(unittest.TestCase):
    def test_power_off_on_exit_is_opt_in(self):
        with TemporaryDirectory() as tmp, patch.object(i18n, "_CONFIG", Path(tmp) / "config.json"):
            self.assertFalse(i18n.power_off_on_exit())

    def test_power_off_on_exit_setting_persists(self):
        with TemporaryDirectory() as tmp, patch.object(i18n, "_CONFIG", Path(tmp) / "eara" / "config.json"):
            i18n.set_power_off_on_exit(True)
            self.assertTrue(i18n.power_off_on_exit())
            i18n.set_power_off_on_exit(False)
            self.assertFalse(i18n.power_off_on_exit())


@unittest.skipIf(gui is None, "GTK 4 / libadwaita not available")
class CloseWindowTests(unittest.TestCase):
    def _close(self, power_off: bool):
        device = MagicMock()
        window = SimpleNamespace(_shutting_down=False, device=device)
        with patch.object(gui, "power_off_on_exit", return_value=power_off), patch.object(
            gui.bluez, "power_off"
        ) as adapter_off:
            gui.EarAWindow._shutdown_bluetooth(window)
        return device, adapter_off

    def test_close_leaves_bluetooth_alone_by_default(self):
        device, adapter_off = self._close(power_off=False)
        device.close_control.assert_called_once()
        device.shutdown.assert_not_called()
        adapter_off.assert_not_called()

    def test_close_powers_off_when_enabled(self):
        device, _adapter_off = self._close(power_off=True)
        device.shutdown.assert_called_once_with(power_off=True)


if __name__ == "__main__":
    unittest.main()
