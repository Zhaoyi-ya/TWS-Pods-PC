"""
Moondrop（水月雨）移植的单元测试 —— 纯标准库 unittest。

运行：``python test_moondrop.py``
覆盖：编解码常量、握手/查询/设置/电量字节（与 MOONDROP-Protocol.txt 逐字节对齐）、
三态解析、models 家族识别、SimulatedTransport 往返、session 状态机与乐观更新。
"""

from __future__ import annotations

import unittest

from moondrop_protocol import (
    MOONDROP_SPP_UUID,
    MOONDROP_VENDOR,
    GAIA_VENDOR,
    HANDSHAKE,
    HANDSHAKE_RESPONSE,
    QUERY_NOISE_MODE,
    REPORT_NOISE_MODE,
    SET_NOISE_MODE,
    QUERY_BATTERY,
    REPORT_BATTERY,
    MoondropNoiseMode,
    Decoder,
    frame,
    handshake,
    query_noise_mode,
    set_noise_mode,
    query_battery,
    parse_noise_state,
    parse_battery_state,
    parse_handshake_state,
    query_byte,
    set_byte,
    from_query_byte,
    from_set_byte,
    hexlify,
)
import moondrop_models as models
from moondrop_models import is_family_name, find_model, canonical_for
from transport import SimulatedTransport, WinSockRfcommTransport, list_paired_devices
from session import EarbudSession, Stage


def hx(data: bytes) -> str:
    return hexlify(data).replace(" ", "").lower()


class TestConstants(unittest.TestCase):
    def test_vendor_and_uuid(self):
        self.assertEqual(MOONDROP_VENDOR, 0x001D)
        self.assertEqual(GAIA_VENDOR, 0x000A)
        self.assertEqual(MOONDROP_SPP_UUID, "00001101-0000-1000-8000-00805F9B34FB")

    def test_command_codes(self):
        self.assertEqual(HANDSHAKE, 0x0300)
        self.assertEqual(HANDSHAKE_RESPONSE, 0x8300)
        self.assertEqual(QUERY_NOISE_MODE, 0x1003)
        self.assertEqual(REPORT_NOISE_MODE, 0x1103)
        self.assertEqual(SET_NOISE_MODE, 0x1004)
        self.assertEqual(QUERY_BATTERY, 0x1A01)
        self.assertEqual(REPORT_BATTERY, 0x1B01)


class TestEncoders(unittest.TestCase):
    def test_handshake(self):
        self.assertEqual(hx(handshake()), "ff010000000a0300")

    def test_query_noise_mode(self):
        self.assertEqual(hx(query_noise_mode()), "ff040000001d1003")

    def test_query_battery(self):
        self.assertEqual(hx(query_battery()), "ff040000001d1a01")

    def test_set_noise_all_modes(self):
        self.assertEqual(hx(set_noise_mode(MoondropNoiseMode.OFF)), "ff040001001d100401")
        self.assertEqual(hx(set_noise_mode(MoondropNoiseMode.ANC)), "ff040001001d100402")
        self.assertEqual(hx(set_noise_mode(MoondropNoiseMode.TRANSPARENCY)), "ff040001001d100404")


class TestModeMapping(unittest.TestCase):
    def test_query_set_byte_roundtrip(self):
        for mode in MoondropNoiseMode:
            self.assertEqual(from_query_byte(query_byte(mode)), mode)
            self.assertEqual(from_set_byte(set_byte(mode)), mode)

    def test_set_byte_values(self):
        self.assertEqual(set_byte(MoondropNoiseMode.OFF), 0x01)
        self.assertEqual(set_byte(MoondropNoiseMode.ANC), 0x02)
        self.assertEqual(set_byte(MoondropNoiseMode.TRANSPARENCY), 0x04)

    def test_query_byte_values(self):
        self.assertEqual(query_byte(MoondropNoiseMode.OFF), 0x00)
        self.assertEqual(query_byte(MoondropNoiseMode.ANC), 0x01)
        self.assertEqual(query_byte(MoondropNoiseMode.TRANSPARENCY), 0x02)


class TestParsers(unittest.TestCase):
    def test_handshake_response(self):
        fr = Decoder().offer(bytes.fromhex("ff040004000a830000040301"))[0]
        hs = parse_handshake_state(fr)
        self.assertIsNotNone(hs)
        self.assertTrue(hs.accepted)

    def test_noise_report_modes(self):
        off = parse_noise_state(Decoder().offer(bytes.fromhex("ff040004001d110300010000"))[0])
        anc = parse_noise_state(Decoder().offer(bytes.fromhex("ff040004001d110301010000"))[0])
        tr = parse_noise_state(Decoder().offer(bytes.fromhex("ff040004001d110302010000"))[0])
        self.assertEqual(off.mode, MoondropNoiseMode.OFF)
        self.assertEqual(anc.mode, MoondropNoiseMode.ANC)
        self.assertEqual(tr.mode, MoondropNoiseMode.TRANSPARENCY)
        self.assertTrue(anc.acknowledged)

    def test_noise_wrong_vendor_ignored(self):
        fr = Decoder().offer(bytes.fromhex("ff040004001d110301010000"))[0]
        # 篡改 vendor 后应无法解析
        bad = frame(version=4, vendor=0x9999, command=REPORT_NOISE_MODE,
                    payload=bytes([1, 1, 0, 0]))
        bad_frame = Decoder().offer(bad)[0]
        self.assertIsNone(parse_noise_state(bad_frame))

    def test_battery_report(self):
        batt = parse_battery_state(Decoder().offer(bytes.fromhex("ff040004001d1b01" + "012e022c"))[0])
        self.assertIsNotNone(batt)
        self.assertEqual(batt.left_percent, 0x2E)
        self.assertEqual(batt.right_percent, 0x2C)

    def test_battery_robust_leading_bytes(self):
        # 真机回包可能带前导字节，电量信息在末 4 字节
        payload = "aabb" + "012e022c"  # payloadLen=06
        batt = parse_battery_state(Decoder().offer(bytes.fromhex("ff040006001d1b01" + payload))[0])
        self.assertIsNotNone(batt)
        self.assertEqual(batt.left_percent, 0x2E)
        self.assertEqual(batt.right_percent, 0x2C)

    def test_battery_no_markers_rejected(self):
        # 末 4 字节 marker 不对 → 不应误判
        batt = parse_battery_state(Decoder().offer(bytes.fromhex("ff040004001d1b01" + "00000000"))[0])
        self.assertIsNone(batt)


class TestModels(unittest.TestCase):
    def test_is_family_name(self):
        self.assertTrue(is_family_name("Moondrop Space Travel"))
        self.assertTrue(is_family_name("moondrop robin"))
        self.assertTrue(is_family_name("水月雨 xxx"))
        self.assertFalse(is_family_name("vivo TWS 3e"))
        self.assertFalse(is_family_name("HUAWEI FreeBuds 3"))
        self.assertFalse(is_family_name(None))

    def test_find_model(self):
        self.assertEqual(find_model("Moondrop Space Travel"), "Moondrop Space Travel")
        self.assertIsNone(find_model("Unknown Earbud"))

    def test_canonical_for(self):
        self.assertEqual(canonical_for("aa:bb:cc:00:11:22", "Moondrop Space Travel"),
                         "Moondrop Space Travel")
        self.assertEqual(canonical_for("aa:bb:cc:00:11:22", "moondrop xxx"), "Moondrop TWS（家族）")
        self.assertEqual(canonical_for("aa:bb:cc:00:11:22", None), "未知蓝牙设备")


class TestSimulatedTransport(unittest.TestCase):
    def _session_and_transport(self):
        addr, name = "AA:BB:CC:00:11:22", "Moondrop Space Travel"
        session = EarbudSession(addr, name)
        t = SimulatedTransport(address=addr, device_name=name)
        t.connect()
        return session, t

    def test_handshake_roundtrip(self):
        session, t = self._session_and_transport()
        t.send(handshake())
        resp = t.recv()
        self.assertTrue(resp)
        session.offer(resp)
        self.assertTrue(session.handshake_ok)
        self.assertGreaterEqual(session.stage, Stage.PROTOCOL)

    def test_noise_query_roundtrip(self):
        session, t = self._session_and_transport()
        t.send(query_noise_mode())
        resp = t.recv()
        session.offer(resp)
        self.assertIsNotNone(session.noise)
        self.assertEqual(session.noise.mode, MoondropNoiseMode.ANC)  # 默认

    def test_battery_query_roundtrip(self):
        session, t = self._session_and_transport()
        t.send(query_battery())
        resp = t.recv()
        session.offer(resp)
        self.assertIsNotNone(session.battery)
        self.assertEqual(session.battery.left_percent, 60)
        self.assertEqual(session.battery.right_percent, 58)

    def test_set_no_ack_but_state_changes(self):
        session, t = self._session_and_transport()
        # 默认 ANC；切到 OFF
        t.send(set_noise_mode(MoondropNoiseMode.OFF))
        resp = t.recv()
        self.assertEqual(resp, b"")  # 真机无 ACK
        # 随后的 query 应反映 OFF
        t.send(query_noise_mode())
        session.offer(t.recv())
        self.assertEqual(session.noise.mode, MoondropNoiseMode.OFF)

    def test_full_initial_sequence(self):
        session, t = self._session_and_transport()
        for cmd in session.initial_read_commands():
            t.send(cmd)
            resp = t.recv()
            if resp:
                session.offer(resp)
        self.assertTrue(session.handshake_ok)
        self.assertIsNotNone(session.battery)
        self.assertIsNotNone(session.noise)
        self.assertGreaterEqual(session.stage, Stage.PUBLISHED)


class TestSessionStateMachine(unittest.TestCase):
    def test_initial_read_commands(self):
        s = EarbudSession("aa:bb:cc:00:11:22", "Moondrop Space Travel")
        cmds = s.initial_read_commands()
        self.assertEqual(len(cmds), 3)
        self.assertEqual(hx(cmds[0]), hx(handshake()))
        self.assertEqual(hx(cmds[1]), hx(query_noise_mode()))
        self.assertEqual(hx(cmds[2]), hx(query_battery()))

    def test_optimistic_set_noise(self):
        s = EarbudSession("aa:bb:cc:00:11:22", "Moondrop Space Travel")
        s.apply_set_noise(MoondropNoiseMode.TRANSPARENCY)
        self.assertEqual(s.noise.mode, MoondropNoiseMode.TRANSPARENCY)
        self.assertFalse(s.noise.acknowledged)

    def test_summary_no_battery(self):
        s = EarbudSession("aa:bb:cc:00:11:22", "Moondrop Space Travel")
        self.assertIn("电量未知", s.summary())


class TestWinSockImports(unittest.TestCase):
    def test_import_winsock_class(self):
        # 仅验证类可构造（不真正连接）
        t = WinSockRfcommTransport("00:11:22:33:44:55")
        self.assertFalse(t.connected)
        self.assertEqual(t.uuid, MOONDROP_SPP_UUID)

    def test_list_paired_devices_callable(self):
        # 注册表枚举返回列表（可能为空，取决于本机配对状态）
        result = list_paired_devices()
        self.assertIsInstance(result, list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
