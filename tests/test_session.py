import socket
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from eara import audio, bluez
from eara.models import model_from_name, model_from_serial
from eara.protocol import CMD_CUSTOM_EQ_SET, CMD_EQ_SET, CMD_LISTENING_GET, CMD_LISTENING_SET, DIR_SET, parse_cmf_eq
from eara.session import Device


def _fake_session(device):
    ctx = patch.object(device, "_session")
    session = ctx.start()
    session.return_value.__enter__ = MagicMock(return_value=device)
    session.return_value.__exit__ = MagicMock(return_value=False)
    return ctx


class SessionTests(unittest.TestCase):
    def test_resolve_model_prefers_serial_when_name_unknown(self):
        named = model_from_name("Bluetooth Audio")
        serial_model = model_from_serial("63123456")
        picked = Device._resolve_model("63123456", named)
        self.assertEqual(picked.base, serial_model.base)

    def test_resolve_model_sh_serial_keeps_name_when_known(self):
        named = model_from_name("Nothing Ear (a)")
        picked = Device._resolve_model("SH63ABCDEF", named)
        self.assertEqual(picked.base, "B162")

    def test_set_custom_eq_requires_response(self):
        device = Device("AA:BB:CC:DD:EE:FF", "Nothing Ear (a)")
        with patch.object(device, "_session") as session_ctx:
            session_ctx.return_value.__enter__ = MagicMock(return_value=device)
            session_ctx.return_value.__exit__ = MagicMock(return_value=False)
            device._sock = MagicMock(spec=socket.socket)
            device._sock.recv.side_effect = socket.timeout()
            with patch.object(device, "_send", return_value=9):
                with self.assertRaises(RuntimeError):
                    device.set_custom_eq(0.0, 0.0, 0.0)

    def test_ring_both_uses_distinct_side_byte(self):
        device = Device("AA:BB:CC:DD:EE:FF", "Nothing Ear (a)")
        with patch.object(device, "_session") as session_ctx:
            session_ctx.return_value.__enter__ = MagicMock(return_value=device)
            session_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch.object(device, "_request", return_value=b"\x00") as req:
                device.ring("both")
                req.assert_called_with(0x02, 0xF0, bytes([0x01, 0x01]))

    def test_request_tracks_sequence(self):
        device = Device("AA:BB:CC:DD:EE:FF", "Nothing Ear (a)")
        device._sock = MagicMock(spec=socket.socket)
        device._sock.recv.side_effect = socket.timeout()
        with patch.object(device, "_send", return_value=42) as send:
            with patch.object(device, "_recv_for", return_value=b"ok") as recv:
                out = device._request(0x07, require=False)
        send.assert_called_once()
        recv.assert_called_once()
        self.assertEqual(recv.call_args.kwargs.get("seq"), 42)
        self.assertEqual(out, b"ok")

    def test_shutdown_disconnects_and_powers_off(self):
        device = Device("AA:BB:CC:DD:EE:FF", "Nothing Ear (a)")
        with patch.object(device, "close_control") as close_ctl:
            with patch.object(bluez, "disconnect") as disconnect:
                with patch.object(bluez, "power_off") as power_off:
                    device.shutdown()
        close_ctl.assert_called_once()
        disconnect.assert_called_once_with("AA:BB:CC:DD:EE:FF")
        power_off.assert_called_once()

    def test_shutdown_skips_power_off_when_disabled(self):
        device = Device("AA:BB:CC:DD:EE:FF", "Nothing Ear (a)")
        with patch.object(device, "close_control"):
            with patch.object(bluez, "disconnect") as disconnect:
                with patch.object(bluez, "power_off") as power_off:
                    device.shutdown(power_off=False)
        disconnect.assert_called_once_with("AA:BB:CC:DD:EE:FF")
        power_off.assert_not_called()


class CmfEqTests(unittest.TestCase):
    def _device(self, name):
        device = Device("AA:BB:CC:DD:EE:FF", name)
        self.addCleanup(_fake_session(device).stop)
        return device

    def test_cmf_buds_2_has_its_own_model(self):
        self.assertEqual(model_from_name("CMF Buds 2").base, "B179")
        self.assertTrue(model_from_name("CMF Buds 2").cmf_eq)
        self.assertFalse(model_from_name("Nothing Ear (a)").cmf_eq)

    def test_untested_cmf_models_keep_listening_mode(self):
        for name, base in (("CMF Buds", "B168"), ("CMF Buds Pro 2", "B172")):
            model = model_from_name(name)
            self.assertEqual(model.base, base)
            self.assertFalse(model.cmf_eq)
            self.assertTrue(model.listening_mode)

    def test_cmf_preset_uses_listening_command(self):
        device = self._device("CMF Buds 2")
        with patch.object(device, "_request", return_value=b"") as req:
            device.set_eq("rock")
        req.assert_called_once_with(CMD_LISTENING_SET, DIR_SET, bytes([1, 0]), require=True)

    def test_nothing_preset_uses_eq_command(self):
        device = self._device("Nothing Ear (a)")
        with patch.object(device, "_request", return_value=b"") as req:
            device.set_eq("voice")
        req.assert_called_once_with(CMD_EQ_SET, DIR_SET, bytes([3, 0]), require=True)

    def test_presets_of_the_other_family_are_rejected(self):
        with self.assertRaises(ValueError):
            self._device("CMF Buds 2").set_eq("more_bass")
        with self.assertRaises(ValueError):
            self._device("Nothing Ear (a)").set_eq("rock")

    def test_cmf_custom_bands_select_custom_preset_first(self):
        device = self._device("CMF Buds 2")
        with patch.object(device, "_request", return_value=b"") as req:
            device.set_graphic_eq([0.0] * 8)
        self.assertEqual(req.call_args_list[0].args, (CMD_LISTENING_SET, DIR_SET, bytes([6, 0])))
        self.assertEqual(req.call_args_list[1].args[0], CMD_CUSTOM_EQ_SET)

    def test_status_reads_cmf_preset_from_listening_command(self):
        device = Device("AA:BB:CC:DD:EE:FF", "CMF Buds 2")
        replies = {CMD_LISTENING_GET: b"\x03"}
        with patch.object(Device, "connected", new_callable=PropertyMock, return_value=True), patch.object(
            device, "open_control"
        ), patch.object(device, "close_control"), patch.object(
            device, "_request", side_effect=lambda cmd, *a, **k: replies.get(cmd)
        ), patch.multiple(
            audio,
            find_sink=MagicMock(return_value=None),
            find_source=MagicMock(return_value=None),
            active_profile=MagicMock(return_value=""),
            active_codec=MagicMock(return_value=""),
            list_a2dp_codecs=MagicMock(return_value=[]),
        ):
            status = device.status()
        self.assertEqual(status["eq"], "pop")

    def test_parse_cmf_eq(self):
        self.assertEqual(parse_cmf_eq(b"\x04"), "enhance_vocals")
        self.assertEqual(parse_cmf_eq(b"\x09"), "unknown-9")
        self.assertIsNone(parse_cmf_eq(b""))


if __name__ == "__main__":
    unittest.main()
