# -*- coding: utf-8 -*-
"""LAN packet builder, based on msmart + hasscc/meiju."""

import datetime
import logging

from .security import MeijuSecurity

_LOGGER = logging.getLogger(__name__)


class PacketBuilder(object):
    def __init__(self, device_id, security=None):
        self.command = None
        self.security = security or MeijuSecurity()
        self.packet = bytearray([
            0x5a, 0x5a,  # static header
            0x01, 0x11,  # message type
            0x00, 0x00,  # packet length
            0x20, 0x00,
            0x00, 0x00, 0x00, 0x00,  # message id
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  # date & time
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  # device id
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        ])
        self.packet[12:20] = self.packet_time()
        self.packet[20:28] = int(device_id).to_bytes(8, 'little')

    def set_command(self, command, add_crc8=True, checksum=True):
        self.command = command.finalize(add_crc8=add_crc8, checksum=checksum)
        return self

    def finalize(self, encrypt=True):
        cmd = self.command
        if encrypt:
            cmd = self.security.aes_encrypt(self.command)[:48]
        else:
            self.packet[0x03] = 0x10
        self.packet.extend(cmd)
        self.packet[4:6] = (len(self.packet) + 16).to_bytes(2, 'little')
        self.packet.extend(self.security.encode32_data(self.packet))
        _LOGGER.debug('packet finalize encrypt=%s cmd=%s', encrypt, bytes(cmd).hex())
        return self.packet

    @staticmethod
    def packet_time():
        text = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')[:16]
        out = bytearray()
        for i in range(0, len(text), 2):
            out.insert(0, int(text[i:i + 2]))
        return out
