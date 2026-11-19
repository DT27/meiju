# -*- coding: utf-8 -*-
"""Offline checks for command / template / customizes."""

from .ac import AcState
from .command import ApplianceResponse, BaseCommand, ControlCommand, SetCommand
from .customizes import get_customizes
from .packet import PacketBuilder
from .security import MeijuSecurity, get_udpid
from .template import render_template


def test_template_bitwise():
    data = [0] * 30
    data[21] = 0x04
    data[26] = 0x0A
    assert render_template('{{ value|bitwise_and(0x04) > 0 }}', 0x04, data) is True
    assert render_template('{{ value|bitwise_and(0x02) > 0 }}', 0x04, data) is False
    assert render_template('{{ value+bytes[16]+bytes[22] > 0 }}', 1, data) is True
    attrs = render_template(
        "{{ {'preheat': bytes[26]|bitwise_and(0x02) > 0, 'cooling': bytes[26]|bitwise_and(0x08) > 0} }}",
        0, data,
    )
    assert attrs['preheat'] is True
    assert attrs['cooling'] is True


def test_customizes():
    b3 = get_customizes('b3')
    assert 'power' in b3['switches']
    assert b3['get_extra'][10] == 0x31
    db = get_customizes('0xDB')
    assert db.get('switches', {}).get('power', {}).get('byte') == 11
    ac = get_customizes('AC')
    assert ac.get('protocol') == 'ac'
    assert 'mode' in ac['selects']
    unknown = get_customizes('FF')
    assert unknown == {}


def test_commands():
    cmd = ControlCommand(0xB3)
    cmd.from_dict({10: 0x21, 11: 0x01, 16: 0x01, 22: 0x01})
    assert cmd.data[0x09] == 0x02
    assert cmd.data[10] == 0x21
    assert cmd.data[11] == 0x01
    assert cmd.data[16] == 0x01
    q = BaseCommand(0xB3)
    q.from_dict({10: 0x31})
    assert q.data[2] == 0xB3
    assert q.data[10] == 0x31


def test_packet_and_crypto():
    cmd = BaseCommand(0xB3)
    cmd.from_dict({10: 0x31})
    pkt = PacketBuilder(160123456789001).set_command(cmd, add_crc8=False).finalize(encrypt=True)
    assert pkt[:2] == b'\x5a\x5a'
    assert len(pkt) > 40
    sec = MeijuSecurity(use_china_server=True)
    sign = sec.new_sign('{}', '1')
    assert len(sign) == 64
    pwd = sec.encrypt_iam_password('id', 'secret')
    assert len(pwd) == 32
    udpid = get_udpid((160123456789001).to_bytes(6, 'big'))
    assert len(udpid) == 32


def test_ac_set_command():
    cmd = SetCommand(0xAC)
    cmd.prompt_tone = False
    cmd.power_state = True
    cmd.target_temperature = 24.5
    cmd.operational_mode = 2
    cmd.fan_speed = 80
    cmd.swing_mode = 0x0C
    cmd.eco_mode = True
    cmd.turbo_mode = False
    assert cmd.data[0x09] == 0x02
    assert cmd.data[0x0a] == 0x40
    assert cmd.data[0x0b] & 0x01
    assert cmd.operational_mode == 2
    assert cmd.fan_speed == 80
    assert cmd.eco_mode is True
    raw = cmd.finalize()
    assert raw[0] == 0xaa
    assert raw[2] == 0xAC
    assert len(raw) > 35


def test_ac_response_and_state():
    frame = bytearray(40)
    frame[0] = 0xaa
    frame[2] = 0xac
    frame[9] = 0x03
    frame[0x0a] = 0xc0
    frame[0x0b] = 0x01  # power on
    frame[0x0c] = 0x48  # cool + 24C (8+16)
    frame[0x0d] = 80
    frame[0x11] = 0x0C
    frame[0x13] = 0x10  # eco
    frame[0x14] = 0x00
    frame[0x15] = 102  # indoor ~26C
    frame[0x16] = 90   # outdoor 20C
    resp = ApplianceResponse(frame)
    assert resp.power_state is True
    assert resp.target_temperature == 24.0
    assert resp.operational_mode == 2
    assert resp.fan_speed == 80
    assert resp.swing_mode == 0x0C
    assert resp.eco_mode is True
    assert resp.indoor_temperature == 26
    assert resp.outdoor_temperature == 20.0

    state = AcState()
    assert state.update_from_frame(frame) is True
    assert state.ready is True
    assert state.power is True
    assert state.target_temp == 24.0
    assert state.mode == 2
    assert state.fan == 80
    assert state.indoor_temp == 26
    state.set_field('target_temp', 26)
    state.set_field('power', False)
    set_cmd = state.build_set_command()
    assert set_cmd.power_state == 0
    assert set_cmd.operational_mode == 2


if __name__ == '__main__':
    test_template_bitwise()
    test_customizes()
    test_commands()
    test_packet_and_crypto()
    test_ac_set_command()
    test_ac_response_and_state()
    print('ok')
