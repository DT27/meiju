# -*- coding: utf-8 -*-
"""0xAC air conditioner state, based on msmart 0.2.3."""

import logging

from .command import ApplianceResponse, BaseCommand, SetCommand

_LOGGER = logging.getLogger(__name__)

FAN_SPEEDS = {
    102: '自动',
    100: '满速',
    80: '高',
    60: '中',
    40: '低',
    20: '静音',
}

OPERATIONAL_MODES = {
    1: '自动',
    2: '制冷',
    3: '除湿',
    4: '制热',
    5: '送风',
}

SWING_MODES = {
    0x0: '关闭',
    0xC: '上下',
    0x3: '左右',
    0xF: '全方位',
}


def _closest_choice(value, choices, default):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    if value in choices:
        return value
    best = default
    best_diff = None
    for item in choices:
        diff = abs(item - value)
        if best_diff is None or diff < best_diff:
            best = item
            best_diff = diff
    return best


class AcState(object):
    def __init__(self):
        self.ready = False
        self.prompt_tone = False
        self.power = False
        self.target_temp = 24.0
        self.mode = 1
        self.fan = 102
        self.swing = 0
        self.eco = False
        self.turbo = False
        self.fahrenheit = False
        self.indoor_temp = None
        self.outdoor_temp = None

    def get(self, key):
        if key == 'power':
            return self.power
        if key == 'eco':
            return self.eco
        if key == 'turbo':
            return self.turbo
        if key == 'mode':
            return self.mode
        if key == 'fan':
            return self.fan
        if key == 'swing':
            return self.swing
        if key == 'target_temp':
            return self.target_temp
        if key == 'indoor_temp':
            return self.indoor_temp
        if key == 'outdoor_temp':
            return self.outdoor_temp
        return None

    def set_field(self, key, value):
        if key == 'power':
            self.power = bool(value)
        elif key == 'eco':
            self.eco = bool(value)
        elif key == 'turbo':
            self.turbo = bool(value)
        elif key == 'mode':
            self.mode = _closest_choice(value, OPERATIONAL_MODES, self.mode)
        elif key == 'fan':
            self.fan = _closest_choice(value, FAN_SPEEDS, self.fan)
        elif key == 'swing':
            self.swing = _closest_choice(value, SWING_MODES, self.swing)
        elif key == 'target_temp':
            try:
                temp = float(value)
            except (TypeError, ValueError):
                return
            if temp < 16:
                temp = 16
            if temp > 30:
                temp = 30
            self.target_temp = round(temp * 2.0) / 2.0
        else:
            raise ValueError('unknown AC field: %s' % key)

    def update_from_frame(self, data):
        if not data or len(data) <= 0x0a:
            return False
        marker = data[0x0a]
        resp = ApplianceResponse(data)
        if marker == 0xc0:
            self.update(resp)
            return True
        if marker in (0xa0, 0xa1):
            self.update_temps(resp)
            return True
        return False

    def update(self, resp):
        self.power = bool(resp.power_state)
        self.target_temp = float(resp.target_temperature)
        self.mode = _closest_choice(resp.operational_mode, OPERATIONAL_MODES, 5)
        self.fan = _closest_choice(resp.fan_speed, FAN_SPEEDS, 102)
        self.swing = _closest_choice(resp.swing_mode, SWING_MODES, 0)
        self.eco = bool(resp.eco_mode)
        self.turbo = bool(resp.turbo_mode)
        self.update_temps(resp)
        self.ready = True

    def update_temps(self, resp):
        indoor = resp.indoor_temperature
        if indoor != 0xff and indoor is not None:
            self.indoor_temp = indoor
        outdoor = resp.outdoor_temperature
        if outdoor != 0xff and outdoor is not None and -20 <= outdoor <= 60:
            self.outdoor_temp = outdoor

    def build_query(self, device_type=0xAC):
        return BaseCommand(device_type)

    def build_set_command(self, device_type=0xAC):
        cmd = SetCommand(device_type)
        cmd.prompt_tone = self.prompt_tone
        cmd.power_state = self.power
        cmd.target_temperature = self.target_temp
        cmd.operational_mode = self.mode
        cmd.fan_speed = self.fan
        cmd.swing_mode = self.swing
        cmd.eco_mode = self.eco
        cmd.turbo_mode = self.turbo
        cmd.fahrenheit = self.fahrenheit
        _LOGGER.debug('AC set_command: %s', cmd.data.hex())
        return cmd
