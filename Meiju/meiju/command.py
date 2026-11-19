# -*- coding: utf-8 -*-
"""Appliance command frames, based on msmart + hasscc/meiju."""

import datetime
import logging

from . import crc8

_LOGGER = logging.getLogger(__name__)


def _checksum(data):
    return (~sum(data) + 1) & 0xff


class BaseCommand(object):
    def __init__(self, device_type=0xAC):
        self.data = bytearray([
            0xaa,  # 0 header
            0x20,  # 1 command length
            0xac,  # 2 device type
            0x00,  # 3 frame syn checksum
            0x00, 0x00,  # 4-5 reserved
            0x00,  # 6 message id
            0x00,  # 7 frame protocol version
            0x00,  # 8 device protocol version
            0x03,  # 9 message type: 0x03 query / 0x02 set
            0x41, 0x81, 0x00, 0xff, 0x03, 0xff, 0x00, 0x02,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
            0x00,
        ])
        self.data[-1] = datetime.datetime.now().second
        self.data[0x02] = device_type & 0xff

    def finalize(self, add_crc8=True, checksum=True):
        if add_crc8:
            self.data.append(crc8.calculate(self.data[10:]))
        if checksum:
            self.data.append(_checksum(self.data[1:]))
        _LOGGER.debug('Finalize request data: %s', self.data.hex())
        return self.data

    def from_dict(self, dic):
        if not dic:
            return self
        for key, value in dic.items():
            idx = int(key)
            while len(self.data) <= idx:
                self.data.append(0xFF)
            self.data[idx] = int(value) & 0xff
        self.data[0x01] = len(self.data)
        return self


class ControlCommand(BaseCommand):
    def __init__(self, device_type):
        super(ControlCommand, self).__init__(device_type)
        self.data[0x09] = 0x02
        self.data = self.data[:-1]
        for n in range(11, len(self.data)):
            self.data[n] = 0xFF


class SetCommand(BaseCommand):
    """msmart 0.2.3 set_command for 0xAC air conditioners."""

    def __init__(self, device_type=0xAC):
        super(SetCommand, self).__init__(device_type)
        self.data[0x01] = 0x23
        self.data[0x09] = 0x02
        self.data[0x0a] = 0x40
        self.data[0x0b] = 0x40
        self.data.extend(bytearray([0x00, 0x00, 0x00]))

    @property
    def prompt_tone(self):
        return self.data[0x0b] & 0x42

    @prompt_tone.setter
    def prompt_tone(self, enabled):
        self.data[0x0b] &= ~0x42
        self.data[0x0b] |= 0x42 if enabled else 0

    @property
    def power_state(self):
        return self.data[0x0b] & 0x01

    @power_state.setter
    def power_state(self, state):
        self.data[0x0b] &= ~0x01
        self.data[0x0b] |= 0x01 if state else 0

    @property
    def target_temperature(self):
        return self.data[0x0c] & 0x1f

    @target_temperature.setter
    def target_temperature(self, temperature_celsius):
        self.data[0x0c] &= ~0x0f
        self.data[0x0c] |= int(temperature_celsius) & 0x0f
        self.temperature_dot5 = int(round(float(temperature_celsius) * 2)) % 2 != 0

    @property
    def operational_mode(self):
        return (self.data[0x0c] & 0xe0) >> 5

    @operational_mode.setter
    def operational_mode(self, mode):
        self.data[0x0c] &= ~0xe0
        self.data[0x0c] |= (int(mode) << 5) & 0xe0

    @property
    def fan_speed(self):
        return self.data[0x0d]

    @fan_speed.setter
    def fan_speed(self, speed):
        self.data[0x0d] = int(speed) & 0xff

    @property
    def eco_mode(self):
        return self.data[0x13] > 0

    @eco_mode.setter
    def eco_mode(self, enabled):
        self.data[0x13] = 0xFF if enabled else 0

    @property
    def swing_mode(self):
        return self.data[0x11]

    @swing_mode.setter
    def swing_mode(self, mode):
        self.data[0x11] = 0x30
        self.data[0x11] |= int(mode) & 0x3f

    @property
    def turbo_mode(self):
        return self.data[0x14] > 0

    @turbo_mode.setter
    def turbo_mode(self, enabled):
        if enabled:
            self.data[0x14] |= 0x02
        else:
            self.data[0x14] &= ~0x02

    @property
    def temperature_dot5(self):
        return self.data[0x0c] & 0x10 > 0

    @temperature_dot5.setter
    def temperature_dot5(self, enabled):
        if enabled:
            self.data[0x0c] |= 0x10
        else:
            self.data[0x0c] &= ~0x10

    @property
    def fahrenheit(self):
        return self.data[0x14] & 0x04 > 0

    @fahrenheit.setter
    def fahrenheit(self, enabled):
        if enabled:
            self.data[0x14] |= 0x04
        else:
            self.data[0x14] &= ~0x04


def _get_bit(p_byte, p_index):
    return (p_byte >> p_index) & 0x01


def _get_bits(p_bytes, p_index, p_start, p_end):
    if p_start > p_end:
        p_start, p_end = p_end, p_start
    temp_val = 0
    i = p_start
    while i <= p_end:
        temp_val |= _get_bit(p_bytes[p_index], i) << (i - p_start)
        i += 1
    return temp_val


class ApplianceResponse(object):
    """msmart 0.2.3 appliance_response for 0xAC air conditioners."""

    def __init__(self, data):
        self.data = bytearray(data[0x0a:]) if data else bytearray()
        _LOGGER.debug('Appliance response data: %s', self.data.hex())

    def _get(self, index, default=0):
        if 0 <= index < len(self.data):
            return self.data[index]
        return default

    @property
    def power_state(self):
        return (self._get(0x01) & 0x1) > 0

    @property
    def target_temperature(self):
        raw = self._get(0x02)
        return (raw & 0x0f) + 16.0 + (0.5 if raw & 0x10 else 0.0)

    @property
    def operational_mode(self):
        return (self._get(0x02) & 0xe0) >> 5

    @property
    def fan_speed(self):
        return self._get(0x03) & 0x7f

    @property
    def swing_mode(self):
        return self._get(0x07) & 0x0f

    @property
    def eco_mode(self):
        return (self._get(0x09) & 0x10) > 0

    @property
    def turbo_mode(self):
        return (self._get(0x0a) & 0x02) > 0

    @property
    def indoor_temperature(self):
        data = self.data
        if not data:
            return 0xff
        try:
            if data[0] == 0xc0:
                if len(data) <= 11:
                    return 0xff
                indoor_int = int((data[11] - 50) / 2)
                if indoor_int < -19 or indoor_int > 50:
                    return 0xff
                indoor_dec = 0.0
                if len(data) > 15:
                    indoor_dec = _get_bits(data, 15, 0, 3) * 0.1
                if data[11] > 49:
                    return indoor_int + indoor_dec
                return indoor_int - indoor_dec
            if data[0] in (0xa0, 0xa1):
                if data[0] == 0xa0:
                    if (data[1] >> 2) - 4 == 0:
                        indoor_int = -1
                    else:
                        indoor_int = (data[1] >> 2) + 12
                    indoor_dec = 0.5 if (data[1] >> 1) & 0x01 else 0
                    return indoor_int + indoor_dec
                if len(data) <= 13:
                    return 0xff
                indoor_int = int((data[13] - 50) / 2)
                if indoor_int < -19 or indoor_int > 50:
                    return 0xff
                indoor_dec = (data[18] & 0x0f) * 0.1 if len(data) > 18 else 0.0
                if int(data[13]) > 49:
                    return indoor_int + indoor_dec
                return indoor_int - indoor_dec
        except (IndexError, TypeError, ValueError):
            return 0xff
        return 0xff

    @property
    def outdoor_temperature(self):
        if len(self.data) <= 0x0c:
            return 0xff
        return (self.data[0x0c] - 50) / 2.0
