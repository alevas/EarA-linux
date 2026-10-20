import unittest
from unittest.mock import MagicMock, patch

from eara import bluez
from eara.protocol import NT_LINK_UUID, RFCOMM_CHANNEL

# One SDP record whose ProtocolDescriptorList is L2CAP + RFCOMM channel 16,
# as CMF Buds 2 publish it for the Nothing control UUID.
_PROTOCOLS = bytes.fromhex("350c" "3503190100" "35051900030810")
_RECORD = bytes.fromhex("3511" "090004") + _PROTOCOLS
_LISTS = bytes.fromhex("3513") + _RECORD


def _sdp_response(lists: bytes, continuation: bytes = b"") -> bytes:
    params = len(lists).to_bytes(2, "big") + lists + bytes([len(continuation)]) + continuation
    return b"\x07\x00\x01" + len(params).to_bytes(2, "big") + params


class _FakeSdpSocket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self.address = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def settimeout(self, _timeout):
        pass

    def connect(self, address):
        self.address = address

    def send(self, data):
        self.sent.append(data)

    def recv(self, _size):
        return self.responses.pop(0)


class BluezTests(unittest.TestCase):
    def setUp(self):
        bluez._channel_cache.clear()

    def test_find_nothing_rejects_unpaired_mac(self):
        with patch.object(bluez, "paired_devices", return_value=[]):
            self.assertIsNone(bluez.find_nothing_device("AA:BB:CC:DD:EE:FF"))

    def test_find_nothing_accepts_paired_mac(self):
        paired = [{"address": "AA:BB:CC:DD:EE:FF", "name": "Nothing Ear (a)"}]
        with patch.object(bluez, "paired_devices", return_value=paired):
            found = bluez.find_nothing_device("AA:BB:CC:DD:EE:FF")
        self.assertIsNotNone(found)
        self.assertEqual(found["address"], "AA:BB:CC:DD:EE:FF")

    def test_trust_and_connect_requires_pairing(self):
        with patch.object(bluez, "_is_paired", return_value=False):
            with self.assertRaises(RuntimeError):
                bluez.trust_and_connect("AA:BB:CC:DD:EE:FF", timeout=1, scan=False, max_rounds=1)

    def test_power_off_skips_when_already_off(self):
        with patch.object(bluez, "_ctl", return_value="Powered: no") as ctl:
            bluez.power_off()
        ctl.assert_called_once_with("show")

    def test_power_off_when_on(self):
        with patch.object(bluez, "_ctl", side_effect=["Powered: yes", ""]):
            bluez.power_off()

    def test_rfcomm_channel_read_from_sdp(self):
        fake = _FakeSdpSocket([_sdp_response(_LISTS)])
        with patch.object(bluez.socket, "socket", return_value=fake):
            self.assertEqual(bluez.rfcomm_channel("3C:B0:ED:F4:B6:C3"), 16)
        self.assertEqual(fake.address, ("3C:B0:ED:F4:B6:C3", bluez.SDP_PSM))
        self.assertEqual(fake.sent[0][0], 0x06)  # ServiceSearchAttributeRequest
        self.assertIn(bytes.fromhex(NT_LINK_UUID.replace("-", "")), fake.sent[0])

    def test_rfcomm_channel_follows_continuation(self):
        fake = _FakeSdpSocket([_sdp_response(_LISTS[:9], b"\xaa"), _sdp_response(_LISTS[9:])])
        with patch.object(bluez.socket, "socket", return_value=fake):
            self.assertEqual(bluez.rfcomm_channel("3C:B0:ED:F4:B6:C3"), 16)
        self.assertTrue(fake.sent[1].endswith(b"\x01\xaa"))

    def test_rfcomm_channel_is_cached(self):
        fake = _FakeSdpSocket([_sdp_response(_LISTS)])
        with patch.object(bluez.socket, "socket", return_value=fake) as factory:
            bluez.rfcomm_channel("3C:B0:ED:F4:B6:C3")
            self.assertEqual(bluez.rfcomm_channel("3c:b0:ed:f4:b6:c3"), 16)
        factory.assert_called_once()

    def test_rfcomm_channel_none_without_record(self):
        fake = _FakeSdpSocket([_sdp_response(b"\x35\x00")])
        with patch.object(bluez.socket, "socket", return_value=fake):
            self.assertIsNone(bluez.rfcomm_channel("3C:B0:ED:F4:B6:C3"))

    def test_rfcomm_channel_none_when_lookup_fails(self):
        with patch.object(bluez.socket, "socket", side_effect=OSError(111, "Connection refused")):
            self.assertIsNone(bluez.rfcomm_channel("3C:B0:ED:F4:B6:C3"))

    def test_open_rfcomm_uses_published_channel(self):
        sock = MagicMock()
        with patch.object(bluez, "rfcomm_channel", return_value=16), patch.object(
            bluez.socket, "socket", return_value=sock
        ):
            bluez.open_rfcomm("3C:B0:ED:F4:B6:C3")
        sock.connect.assert_called_once_with(("3C:B0:ED:F4:B6:C3", 16))

    def test_open_rfcomm_falls_back_to_default_channel(self):
        sock = MagicMock()
        with patch.object(bluez, "rfcomm_channel", return_value=None), patch.object(
            bluez.socket, "socket", return_value=sock
        ):
            bluez.open_rfcomm("AA:BB:CC:DD:EE:FF")
        sock.connect.assert_called_once_with(("AA:BB:CC:DD:EE:FF", RFCOMM_CHANNEL))


if __name__ == "__main__":
    unittest.main()
