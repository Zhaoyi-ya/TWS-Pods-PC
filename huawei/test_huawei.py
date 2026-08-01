"""
Huawei FreeBuds 协议移植验证

对齐 HuaweiPods-main（Kotlin）的逐字节常量与解析逻辑。
运行：python test_huawei.py
"""

import unittest

from huawei_models import (
    FAMILY_DEFAULT,
    FREEBUDS3_VALIDATED,
    canonical_for,
    find_model,
    is_family_name,
    select_profile,
)
from huawei_protocol import (
    ANC_LEVEL_MAX,
    AncMode,
    GESTURE_LEFT,
    GestureAction,
    HuaweiBatteryParser,
    anc_level,
    anc_off,
    anc_on,
    crc16_xmodem,
    gesture_double_tap,
)
from session import EarbudSession, Stage


def hx(text: str) -> bytes:
    compact = "".join(c for c in text if c.isalnum())
    return bytes.fromhex(compact)


class TestCrcAndFrames(unittest.TestCase):
    def test_crc16_xmodem_known(self):
        # 与 Kotlin crc16Xmodem(0x5A 00 06 00 2B 04 01 01 01) == 0x7800 对齐
        self.assertEqual(0x7800, crc16_xmodem(hx("5A0006002B04010101")))
        self.assertEqual(0x6821, crc16_xmodem(hx("5A0006002B04010100")))

    def test_anc_on_off_match_kotlin(self):
        self.assertEqual(hx("5A 00 06 00 2B 04 01 01 01 78 00"), anc_on())
        self.assertEqual(hx("5A 00 06 00 2B 04 01 01 00 68 21"), anc_off())

    def test_anc_level_packets_match_kotlin(self):
        expected = [
            "5A0006002B080101002713",
            "5A0006002B080101013732",
            "5A0006002B080101020751",
            "5A0006002B080101031770",
            "5A0006002B080101046797",
            "5A0006002B0801010577B6",
            "5A0006002B0801010647D5",
            "5A0006002B0801010757F4",
            "5A0006002B08010108A61B",
        ]
        for i, hexstr in enumerate(expected):
            self.assertEqual(hx(hexstr), anc_level(i), msg=f"level {i}")

    def test_anc_level_clamps(self):
        self.assertEqual(anc_level(-3), anc_level(0))
        self.assertEqual(anc_level(99), anc_level(ANC_LEVEL_MAX))

    def test_gesture_packet(self):
        # group=0x01 cmd=0x1F, left(0x01), p2=0x01, play_pause(0x01)
        pkt = gesture_double_tap(GESTURE_LEFT, GestureAction.PLAY_PAUSE)
        self.assertEqual(hx("5A000600011F01010133A2"), pkt)


class TestBatteryParser(unittest.TestCase):
    def test_parse_full(self):
        text = "+HUAWEIBATTERY: 6,2,83,3,0,4,82,5,0,6,95,7,0"
        b = HuaweiBatteryParser.parse(text)
        self.assertIsNotNone(b)
        self.assertEqual(83, b.left_percent)
        self.assertEqual(82, b.right_percent)
        self.assertEqual(95, b.case_percent)
        self.assertFalse(b.left_charging)
        self.assertFalse(b.right_charging)
        self.assertFalse(b.case_charging)

    def test_parse_charging_bits(self):
        text = "+HUAWEIBATTERY: 6,2,80,3,1,4,75,5,0,6,90,7,1"
        b = HuaweiBatteryParser.parse(text)
        self.assertTrue(b.left_charging)
        self.assertFalse(b.right_charging)
        self.assertTrue(b.case_charging)

    def test_parse_with_at_prefix_and_crlf(self):
        text = "AT+HUAWEIBATTERY= 6,2,50,3,0,4,60,5,1,6,70,7,0\r\n"
        b = HuaweiBatteryParser.parse(text)
        self.assertIsNotNone(b)
        self.assertEqual(50, b.left_percent)
        self.assertEqual(60, b.right_percent)
        self.assertEqual(70, b.case_percent)
        self.assertTrue(b.right_charging)

    def test_parse_invalid(self):
        self.assertIsNone(HuaweiBatteryParser.parse(""))
        self.assertIsNone(HuaweiBatteryParser.parse("+HUAWEIBATTERY:"))
        self.assertIsNone(HuaweiBatteryParser.parse("some other AT command"))


class TestModels(unittest.TestCase):
    def test_is_family_name(self):
        self.assertTrue(is_family_name("HUAWEI FreeBuds 3"))
        self.assertTrue(is_family_name("honor Earbuds 3 Pro"))
        self.assertFalse(is_family_name("vivo TWS 3e"))
        self.assertFalse(is_family_name(None))

    def test_find_model(self):
        self.assertEqual("HUAWEI FreeBuds 3", find_model("HUAWEI FreeBuds 3"))
        self.assertIsNone(find_model("Unknown Device"))

    def test_select_profile_validated(self):
        self.assertIs(select_profile("HUAWEI FreeBuds 3"), FREEBUDS3_VALIDATED)
        self.assertIs(select_profile("honor Earbuds"), FAMILY_DEFAULT)

    def test_canonical_for(self):
        self.assertEqual("HUAWEI FreeBuds 3", canonical_for("00:11:22:33:44:55", "HUAWEI FreeBuds 3"))
        self.assertEqual("未知蓝牙设备", canonical_for("00:11:22:33:44:55", None))


class TestSessionPipeline(unittest.TestCase):
    """端到端：用 SimulatedTransport 跑通 编码→发送→解码→状态。"""

    def test_simulated_battery_roundtrip(self):
        from transport import SimulatedTransport

        session = EarbudSession("AA:BB:CC:00:11:22", "HUAWEI FreeBuds 3")
        transport = SimulatedTransport(
            address=session.address, device_name=session.device_name,
            profile=session.profile, battery=(83, 82, 95),
        )
        transport.connect()
        session.stage = Stage.CHANNEL
        for cmd in session.initial_read_commands():
            transport.send(cmd)
            resp = transport.recv()
            self.assertTrue(resp)
            session.offer(resp)

        self.assertEqual(Stage.PUBLISHED, session.stage)
        self.assertEqual(83, session.battery.left_percent)
        self.assertEqual(95, session.battery.case_percent)

    def test_anc_optimistic_update(self):
        session = EarbudSession("AA:BB:CC:00:11:22", "HUAWEI FreeBuds 3")
        session.apply_anc(AncMode.ON, level=3)
        self.assertEqual(AncMode.ON, session.anc_mode)
        self.assertEqual(3, session.anc_level)
        session.apply_anc(AncMode.OFF)
        self.assertEqual(AncMode.OFF, session.anc_mode)

    def test_gesture_apply(self):
        session = EarbudSession("AA:BB:CC:00:11:22", "HUAWEI FreeBuds 3")
        session.apply_gesture(GESTURE_LEFT, GestureAction.PLAY_NEXT)
        self.assertEqual(GestureAction.PLAY_NEXT, session.gesture_left)


class TestTransportImport(unittest.TestCase):
    def test_list_paired_devices_callable(self):
        from transport import list_paired_devices
        # 不强制有设备；只验证函数可调用且返回 list（注册表无权限时返回 []）
        result = list_paired_devices()
        self.assertIsInstance(result, list)

    def test_battery_query_constant(self):
        from huawei_protocol import BATTERY_QUERY
        self.assertEqual(b"AT+HUAWEIBATTERY?\r\n", BATTERY_QUERY)


if __name__ == "__main__":
    unittest.main(verbosity=2)
