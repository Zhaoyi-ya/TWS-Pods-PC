"""
vivo 协议移植验证 —— 对齐 Kotlin 测试向量

对应 protocol/src/test/.../vivo/VivoTwsProtocolTest.kt 的逐条断言。
运行：python test_vivo.py
"""

import unittest

from session import Stage
from vivo_protocol import (
    ACK_NOISE_MODE,
    AIR3_PRO_CAPTURED,
    BatteryState,
    Decoder,
    FAMILY_DEFAULT_V4,
    NoiseMode,
    NoiseState,
    REPORT_BATTERY,
    REPORT_NOISE_MODE,
    TWS_3E_V3,
    frame,
    handshake,
    parse_battery_state,
    parse_handshake_state,
    parse_noise_state,
    query_battery,
    query_noise_mode,
    set_noise_mode,
)


def hx(text: str) -> bytes:
    compact = "".join(c for c in text if c.isalnum())
    return bytes.fromhex(compact)


class TestEncode(unittest.TestCase):
    def test_set_noise_variants(self):
        self.assertEqual(
            hx("FF 03 00 03 00 1B 01 30 00 04 00"),
            set_noise_mode(NoiseMode.ANC, AIR3_PRO_CAPTURED),
        )
        self.assertEqual(
            hx("FF 04 00 03 00 1B 01 30 02 03 01"),
            set_noise_mode(NoiseMode.TRANSPARENCY, FAMILY_DEFAULT_V4),
        )
        self.assertEqual(
            hx("FF 03 00 02 00 1B 01 30 01 03"),
            set_noise_mode(NoiseMode.OFF, TWS_3E_V3),
        )

    def test_readonly_probe_packets(self):
        self.assertEqual(hx("FF 04 00 00 00 0A 03 00"), handshake())
        self.assertEqual(
            hx("FF 03 00 00 00 1B 02 30"),
            query_noise_mode(AIR3_PRO_CAPTURED),
        )
        self.assertEqual(
            hx("FF 04 00 01 00 1B 02 30 00"),
            query_noise_mode(FAMILY_DEFAULT_V4),
        )
        self.assertEqual(hx("FF 04 00 00 00 1B 02 07"), query_battery())


class TestDecoder(unittest.TestCase):
    def test_resync_and_split_noise_report(self):
        dec = Decoder()
        self.assertEqual(dec.offer(hx("11 22 FF 03 00 04 00 1B")).__len__(), 0)
        frame_ = dec.offer(hx("82 30 00 02 04 00")).pop()
        state = parse_noise_state(frame_)
        self.assertEqual(NoiseMode.TRANSPARENCY, state.mode)
        self.assertEqual(4, state.noise_effect)
        self.assertEqual(0, state.transparency_effect)
        self.assertFalse(state.acknowledged)

    def test_short_family_noise_without_optional_effects(self):
        frame_ = Decoder().offer(hx("FF 03 00 03 00 1B 81 30 00 02 03")).pop()
        state = parse_noise_state(frame_)
        self.assertEqual(NoiseMode.TRANSPARENCY, state.mode)
        self.assertEqual(3, state.noise_effect)
        self.assertIsNone(state.transparency_effect)
        self.assertTrue(state.acknowledged)

    def test_battery_and_charging_bitmap(self):
        frame_ = Decoder().offer(hx("FF 03 00 05 00 1B 82 07 00 5C 59 48 05")).pop()
        b = parse_battery_state(frame_)
        self.assertEqual(92, b.left_percent)
        self.assertEqual(89, b.right_percent)
        self.assertEqual(72, b.case_percent)
        self.assertTrue(b.left_charging)
        self.assertFalse(b.right_charging)
        self.assertTrue(b.case_charging)

    def test_air3pro_responses_captured_on_device(self):
        dec = Decoder()
        hs = dec.offer(hx("FF 03 00 04 00 0A 83 00 00 03 03 01")).pop()
        noise = dec.offer(hx("FF 03 00 04 00 1B 82 30 00 01 04 00")).pop()
        batt = dec.offer(hx("FF 03 00 05 00 1B 82 07 00 53 52 5F 00")).pop()
        ack = dec.offer(hx("FF 03 00 04 00 1B 81 30 00 02 04 00")).pop()

        self.assertTrue(parse_handshake_state(hs).accepted)
        self.assertEqual(3, parse_handshake_state(hs).version)

        self.assertEqual(NoiseMode.OFF, parse_noise_state(noise).mode)
        self.assertFalse(parse_noise_state(noise).acknowledged)

        self.assertEqual(83, parse_battery_state(batt).left_percent)
        self.assertEqual(82, parse_battery_state(batt).right_percent)
        self.assertEqual(95, parse_battery_state(batt).case_percent)

        self.assertEqual(NoiseMode.TRANSPARENCY, parse_noise_state(ack).mode)
        self.assertTrue(parse_noise_state(ack).acknowledged)

    def test_concatenated_reports(self):
        frames = Decoder().offer(
            hx(
                "FF 03 00 04 00 1B 82 30 00 01 04 00 "
                "FF 03 00 05 00 1B 82 07 00 53 52 FF 00 "
                "FF 03 00 02 00 1B 82 0D 00 04"
            )
        )
        self.assertEqual(3, len(frames))
        self.assertEqual(REPORT_NOISE_MODE, frames[0].command)
        self.assertEqual(REPORT_BATTERY, frames[1].command)
        self.assertIsNone(parse_battery_state(frames[1]).case_percent)
        self.assertEqual(0x820D, frames[2].command)

    def test_rejects_failed_or_unrelated(self):
        failed = Decoder().offer(hx("FF 03 00 04 00 1B 82 30 03 02 04 00")).pop()
        unrelated = Decoder().offer(hx("FF 03 00 01 00 1B 82 55 00")).pop()
        self.assertIsNone(parse_noise_state(failed))
        self.assertIsNone(parse_battery_state(unrelated))


class TestSessionPipeline(unittest.TestCase):
    """端到端：用 SimulatedTransport 跑通 编码→发送→解码→状态。"""

    def test_simulated_roundtrip(self):
        from session import EarbudSession
        from transport import SimulatedTransport

        session = EarbudSession("AA:BB:CC:00:11:22", "vivo TWS Air3 Pro")
        transport = SimulatedTransport(
            address=session.address, device_name=session.device_name,
            profile=session.profile, battery=(83, 82, 95), noise=NoiseMode.ANC,
        )
        transport.connect()
        session.stage = 1  # CHANNEL
        for cmd in session.initial_read_commands():
            transport.send(cmd)
            resp = transport.recv()
            self.assertTrue(resp)
            session.offer(resp)

        self.assertEqual(Stage.PUBLISHED, session.stage)
        self.assertEqual(83, session.battery.left_percent)
        self.assertEqual(95, session.battery.case_percent)
        self.assertEqual(NoiseMode.ANC, session.noise.mode)

        # 切换到通透
        for cmd in session.encode_set_noise(NoiseMode.TRANSPARENCY):
            transport.send(cmd)
            resp = transport.recv()
            session.offer(resp)
        self.assertEqual(NoiseMode.TRANSPARENCY, session.noise.mode)


class TestHandmadeVivoProtocol(unittest.TestCase):
    """对照独立逆向文档 Pods-Protocol-Reverse-Engineering/handmade/vivo-Protocol.txt。

    该文档与 Kotlin 测试向量相互印证，专门锁定 v4 家族默认 Profile：
    - 查询响应载荷为 ``00 mode 03 01``；
    - 设置包为 ``FF040003001b0130 [mode] 03 01``；
    - 电量 ``00 LL RR MM CC``，CC 的 bit0/1/2 = 左/右/盒充电（组合见文档）。
    """

    def test_handmade_handshake(self):
        self.assertEqual(hx("ff040000000a0300"), handshake())
        self.assertEqual(
            hx("ff030004000a830000030301"),
            Decoder().offer(hx("ff030004000a830000030301")).pop().raw,
        )

    def test_handmade_query_responses_three_modes(self):
        # 期望接受：降噪关 01 / 降噪开 00 / 通透 02
        off = Decoder().offer(hx("ff030004001b823000010301")).pop()
        on = Decoder().offer(hx("ff030004001b823000000301")).pop()
        tp = Decoder().offer(hx("ff030004001b823000020301")).pop()
        self.assertEqual(NoiseMode.OFF, parse_noise_state(off).mode)
        self.assertEqual(NoiseMode.ANC, parse_noise_state(on).mode)
        self.assertEqual(NoiseMode.TRANSPARENCY, parse_noise_state(tp).mode)

    def test_handmade_set_packets_match_v4_profile(self):
        self.assertEqual(
            hx("ff040003001b0130010301"),
            set_noise_mode(NoiseMode.OFF, FAMILY_DEFAULT_V4),
        )
        self.assertEqual(
            hx("ff040003001b0130000301"),
            set_noise_mode(NoiseMode.ANC, FAMILY_DEFAULT_V4),
        )
        self.assertEqual(
            hx("ff040003001b0130020301"),
            set_noise_mode(NoiseMode.TRANSPARENCY, FAMILY_DEFAULT_V4),
        )

    def test_handmade_battery_charging_combos(self):
        # CC 单/组合：01 左, 02 右, 04 盒, 03 左右, 05 左+盒, 06 右+盒, 07 全部
        combos = {
            0x01: (True, False, False),
            0x02: (False, True, False),
            0x04: (False, False, True),
            0x03: (True, True, False),
            0x05: (True, False, True),
            0x06: (False, True, True),
            0x07: (True, True, True),
        }
        for cc, (l, r, c) in combos.items():
            frame_ = Decoder().offer(hx(f"ff030005001b82070053 52 5F {cc:02X}")).pop()
            b = parse_battery_state(frame_)
            self.assertEqual(83, b.left_percent)
            self.assertEqual(82, b.right_percent)
            self.assertEqual(95, b.case_percent)
            self.assertEqual(l, b.left_charging)
            self.assertEqual(r, b.right_charging)
            self.assertEqual(c, b.case_charging)


if __name__ == "__main__":
    unittest.main(verbosity=2)
