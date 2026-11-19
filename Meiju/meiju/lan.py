# -*- coding: utf-8 -*-
"""Local TCP transport for Midea appliances (protocol 2 / 3)."""

import logging
import socket
import time

from .const import MSGTYPE_ENCRYPTED_REQUEST, MSGTYPE_HANDSHAKE_REQUEST
from .security import MeijuSecurity

_LOGGER = logging.getLogger(__name__)


class LanService(object):
    def __init__(self, device_ip, device_id, device_port=6444, security=None):
        self.device_ip = device_ip
        self.device_id = device_id
        self.device_port = int(device_port)
        self.security = security or MeijuSecurity()
        self._retries = 0
        self._socket = None
        self._token = None
        self._key = None
        self._timestamp = time.time()
        self._tcp_key = None
        self._local = None
        self._remote = '%s:%s' % (device_ip, device_port)
        self._buffer = b''

    def _connect(self):
        if self._socket is not None:
            return
        self._disconnect()
        _LOGGER.debug('Connecting to %s', self._remote)
        self._buffer = b''
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            sock.connect((self.device_ip, self.device_port))
            self._socket = sock
            self._timestamp = time.time()
            self._local = '%s:%s' % sock.getsockname()[:2]
        except Exception as error:
            _LOGGER.error('Connect error %s: %s', self._remote, error)
            try:
                sock.close()
            except Exception:
                pass
            self._socket = None

    def _disconnect(self):
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
        self._socket = None
        self._tcp_key = None

    def request(self, message):
        self._connect()
        if self._socket is None:
            return bytearray(0), False
        try:
            _LOGGER.debug('Sending %s: %s', self._remote, bytes(message).hex())
            self._socket.sendall(message)
        except Exception as error:
            _LOGGER.error('Send %s error: %s', self._remote, error)
            self._disconnect()
            self._retries += 1
            return bytearray(0), True
        try:
            response = self._socket.recv(1024)
        except socket.timeout:
            _LOGGER.debug('Recv %s timed out', self._remote)
            self._retries += 1
            return bytearray(0), True
        except socket.error as error:
            _LOGGER.debug('Recv %s error: %s', self._remote, error)
            self._disconnect()
            self._retries += 1
            return bytearray(0), True
        if not response:
            _LOGGER.debug('Recv %s server closed socket', self._remote)
            self._disconnect()
            self._retries += 1
            return bytearray(0), True
        self._retries = 0
        _LOGGER.debug('Recv %s: %s', self._remote, response.hex())
        return response, True

    def authenticate(self, token, key):
        self._token, self._key = token, key
        if not self._token or not self._key:
            raise Exception('missing token key pair')
        request = self.security.encode_8370(self._token, MSGTYPE_HANDSHAKE_REQUEST)
        response, _ = self.request(request)
        response = response[8:72]
        tcp_key, success = self.security.tcp_key(response, self._key)
        if success:
            self._tcp_key = tcp_key.hex()
            _LOGGER.info('Got TCP key for %s', self._remote)
            time.sleep(1)
        else:
            _LOGGER.error('Authentication failed for %s', self._remote)
        return success

    def appliance_transparent_send_8370(self, data, msgtype=MSGTYPE_ENCRYPTED_REQUEST):
        if self._socket is None or self._tcp_key is None:
            self._disconnect()
            if not self._token or not self._key:
                return []
            if not self.authenticate(self._token, self._key):
                return []
        original = bytearray(data)
        packed = self.security.encode_8370(data, msgtype)
        time.sleep(self._retries)
        responses, retryable = self.request(packed)
        if responses[8:13] == b'ERROR':
            self._disconnect()
            return [b'ERROR']
        if responses == bytearray(0) and self._retries < 2 and retryable:
            packets = self.appliance_transparent_send_8370(original, msgtype)
            self._retries = 0
            return packets
        responses, self._buffer = self.security.decode_8370(self._buffer + responses)
        packets = []
        for response in responses:
            if len(response) > 40 + 16:
                response = self.security.aes_decrypt(response[40:-16])
            if len(response) > 10:
                packets.append(response)
        return packets

    def appliance_transparent_send(self, data):
        time.sleep(self._retries)
        responses, retryable = self.request(data)
        if responses == bytearray(0) and self._retries < 2 and retryable:
            packets = self.appliance_transparent_send(data)
            self._retries = 0
            return packets
        packets = []
        if not responses:
            return packets
        dlen = len(responses)
        if responses[:2] == b'\x5a\x5a' and dlen > 5:
            i = 0
            while i < dlen:
                size = responses[i + 4]
                data = self.security.aes_decrypt(responses[i:i + size][40:-16])
                if len(data) > 10:
                    packets.append(data)
                i += size
        elif responses[0] == 0xaa and dlen > 2:
            i = 0
            while i < dlen:
                size = responses[i + 1]
                data = responses[i:i + size + 1]
                if len(data) > 10:
                    packets.append(data)
                i += size + 1
        else:
            _LOGGER.error('Unknown responses %s', responses.hex())
        return packets
