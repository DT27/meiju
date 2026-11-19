# -*- coding: utf-8 -*-
"""Local / cloud device control, based on hasscc/meiju BaseDevice."""

import logging

from .ac import AcState
from .command import BaseCommand, ControlCommand
from .const import CMD_TYPE_QUERY, CMD_TYPE_REPORT, DEFAULT_PORT
from .customizes import DEFAULT_CUSTOMIZES, get_customizes
from .lan import LanService
from .packet import PacketBuilder
from .security import MeijuSecurity
from .template import render_template

_LOGGER = logging.getLogger(__name__)


class DeviceStatus(object):
    def __init__(self, data):
        self.data = bytearray(data) if data else bytearray()
        self.type = self.get(0x09)
        self.update = self.type in (CMD_TYPE_QUERY, CMD_TYPE_REPORT)

    def get(self, index, default=None):
        try:
            index = int(index)
        except (TypeError, ValueError):
            return default
        if 0 <= index < len(self.data):
            return self.data[index]
        return default

    def __str__(self):
        return str(list(self.data))


class LanDevice(object):
    """Minimal msmart device.base replacement."""

    def __init__(self, device_type, device_id, host, port=DEFAULT_PORT, security=None):
        self._type = int(device_type)
        self._id = int(device_id)
        self._ip = host
        self._port = int(port or DEFAULT_PORT)
        self.security = security or MeijuSecurity()
        self._lan_service = LanService(self._ip, self._id, self._port, security=self.security)
        self._protocol_version = 2
        self._token = None
        self._key = None
        self._status = None
        self._active = False
        self._support = False
        self._online = False
        self._last_responses = []

    @property
    def id(self):
        return self._id

    @property
    def type(self):
        return self._type

    @property
    def status(self):
        return self._status

    def authenticate(self, key, token):
        if not key or not token:
            return False
        self._protocol_version = 3
        self._token = bytearray.fromhex(token)
        self._key = bytearray.fromhex(key)
        return self._lan_service.authenticate(self._token, self._key)

    def refresh(self, extra=None):
        cmd = BaseCommand(self.type)
        cmd.from_dict(extra)
        return self.send_command(cmd)

    def control_command(self, extra=None):
        cmd = ControlCommand(self.type)
        cmd.from_dict(extra)
        _LOGGER.debug('control_command: %s', cmd.data.hex())
        return cmd

    def command_packet(self, cmd, encrypt=True, add_crc8=None):
        if add_crc8 is None:
            add_crc8 = self._type == 0xAC
        builder = PacketBuilder(self.id, security=self.security)
        builder.set_command(cmd, add_crc8=add_crc8)
        return builder.finalize(encrypt=encrypt)

    def send_command(self, cmd):
        data = self.command_packet(cmd)
        if self._protocol_version == 3:
            responses = self._lan_service.appliance_transparent_send_8370(data)
        else:
            responses = self._lan_service.appliance_transparent_send(data)
        if not responses:
            self._active = False
            self._support = False
            return False
        try:
            responses.sort()
        except TypeError:
            pass
        self._last_responses = responses
        for response in responses:
            self.process_response(response)
        return responses[0] if responses else None

    def process_response(self, data):
        if not data:
            return
        self._online = True
        self._active = True
        if data == b'ERROR':
            self._support = False
            return
        response = DeviceStatus(data)
        self._support = True
        if response.update:
            self._status = response


class MeijuDevice(object):
    def __init__(self, info, config, cloud):
        self.cloud = cloud
        self.info = info or {}
        self.config = config or {}
        self.status = None
        self.ac = AcState()
        self.lan_key = self.config.get('lan_key') or ''
        self.lan_token = self.config.get('lan_token') or ''
        self.lan_device = None
        host = self.host
        if host:
            try:
                self.lan_device = LanDevice(self.type, self.did, host, self.port, security=cloud.security)
            except Exception as exc:
                _LOGGER.error('Create LAN device failed: %s', exc)
                self.lan_device = None

    @property
    def did(self):
        raw = self.info.get('applianceCode') or self.config.get('device_id') or 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    @property
    def name(self):
        return self.info.get('name') or ('Meiju %s' % self.sn8)

    @property
    def type(self):
        raw = self.info.get('type') if self.info.get('type') not in (None, '') else self.config.get('type')
        if isinstance(raw, int):
            return raw
        try:
            return int(str(raw or '0'), 16)
        except (TypeError, ValueError):
            return 0

    @property
    def type_hex(self):
        return '%02X' % (self.type & 0xff)

    @property
    def type_str(self):
        return '0x%s' % self.type_hex

    @property
    def sn(self):
        sn = self.info.get('sn', '')
        if sn:
            try:
                sn = self.cloud.decrypt_with_key(sn)
            except Exception:
                pass
        return sn

    @property
    def sn8(self):
        sn8 = self.info.get('sn8') or ''
        return str(sn8).upper() if sn8 else '00000000'

    @property
    def model(self):
        return self.info.get('productModel') or self.sn8

    @property
    def host(self):
        return (self.config.get('host') or '').strip()

    @property
    def port(self):
        try:
            return int(self.config.get('port') or DEFAULT_PORT)
        except (TypeError, ValueError):
            return DEFAULT_PORT

    @property
    def is_ac(self):
        return self.type == 0xAC or (self.customizes or {}).get('protocol') == 'ac'

    @property
    def customizes(self):
        cus = get_customizes(self.type_hex, self.sn8)
        if not cus:
            cus = dict(DEFAULT_CUSTOMIZES)
        return cus

    @property
    def online(self):
        if self.lan_device:
            return bool(self.lan_device._online)
        return bool(self.status)

    def auth(self):
        if not self.lan_device:
            return False
        if self.lan_key and self.lan_token:
            try:
                if self.lan_device.authenticate(self.lan_key, self.lan_token):
                    return True
            except Exception as exc:
                _LOGGER.warning('%s: auth with saved key/token failed: %s', self.name, exc)
        token, key, byteorder = self.cloud.get_lan_token(self.did)
        if not token or not key:
            _LOGGER.error('%s: cloud getToken failed', self.name)
            return False
        try:
            ok = self.lan_device.authenticate(key, token)
        except Exception as exc:
            _LOGGER.error('%s: LAN authenticate failed: %s', self.name, exc)
            return False
        if ok:
            self.lan_key = key
            self.lan_token = token
            _LOGGER.info('%s: LAN auth success (%s)', self.name, byteorder)
        else:
            _LOGGER.error('%s: LAN auth rejected', self.name)
        return ok

    def refresh(self, via_cloud=False):
        if self.is_ac:
            return self._refresh_ac(via_cloud)
        extra = self.customizes.get('get_extra') or {}
        if via_cloud or not self.lan_device:
            cmd = BaseCommand(self.type)
            cmd.from_dict(extra)
            rsp = self._send_cloud(cmd)
            if isinstance(rsp, (bytes, bytearray)) and rsp:
                status = DeviceStatus(rsp)
                if status.update:
                    self.status = status
                return self.status
            return None
        try:
            self.lan_device.refresh(extra)
        except Exception as exc:
            _LOGGER.error('%s: refresh failed: %s', self.name, exc)
            return None
        status = self.lan_device.status
        if status:
            self.status = status
        return self.status

    def control(self, cmd_dict, via_cloud=False):
        if not self.lan_device and not via_cloud:
            via_cloud = True
        extra = {}
        extra.update(self.customizes.get('set_extra') or {})
        extra.update(cmd_dict or {})
        cmd = self.lan_device.control_command(extra) if self.lan_device else ControlCommand(self.type).from_dict(extra)
        if via_cloud:
            rsp = self._send_cloud(cmd)
        else:
            try:
                rsp = self.lan_device.send_command(cmd)
            except Exception as exc:
                _LOGGER.error('%s: LAN control failed: %s', self.name, exc)
                rsp = None
        if isinstance(rsp, (bytes, bytearray)):
            rsp = bytes(rsp).hex()
        _LOGGER.info('%s: control %s -> %s', self.name, extra, rsp)
        return rsp

    def ac_control(self, key, value, via_cloud=False):
        """Apply one AC field while sending the full msmart set frame."""
        if not self.is_ac:
            raise ValueError('not an AC device')
        self.ac.set_field(key, value)
        cmd = self.ac.build_set_command(self.type or 0xAC)
        rsp = self._send_ac(cmd, via_cloud)
        _LOGGER.info('%s: AC %s=%s ready=%s', self.name, key, value, self.ac.ready)
        return rsp

    def _refresh_ac(self, via_cloud=False):
        cmd = self.ac.build_query(self.type or 0xAC)
        rsp = self._send_ac(cmd, via_cloud)
        if not self.ac.ready:
            _LOGGER.warning('%s: AC status not parsed', self.name)
        return self.status if self.status else rsp

    def _send_ac(self, cmd, via_cloud=False):
        if via_cloud or not self.lan_device:
            rsp = self._send_cloud(cmd, add_crc8=True)
            self._apply_ac_responses(rsp)
            return rsp
        try:
            rsp = self.lan_device.send_command(cmd)
        except Exception as exc:
            _LOGGER.error('%s: AC LAN send failed: %s', self.name, exc)
            return None
        if not rsp:
            return None
        self._apply_ac_responses(self.lan_device._last_responses)
        if self.lan_device.status:
            self.status = self.lan_device.status
        return rsp

    def _apply_ac_responses(self, frames):
        if not frames:
            return
        if isinstance(frames, (bytes, bytearray)):
            frames = [frames]
        parsed = False
        for frame in frames:
            if not isinstance(frame, (bytes, bytearray)) or not frame:
                continue
            self.status = DeviceStatus(frame)
            if self.ac.update_from_frame(frame):
                parsed = True
        if parsed:
            _LOGGER.debug(
                '%s: AC power=%s mode=%s fan=%s temp=%s indoor=%s',
                self.name, self.ac.power, self.ac.mode, self.ac.fan,
                self.ac.target_temp, self.ac.indoor_temp,
            )

    def _send_cloud(self, cmd, add_crc8=False):
        builder = PacketBuilder(self.did, security=self.cloud.security)
        builder.set_command(cmd, add_crc8=add_crc8)
        pkt = builder.finalize(encrypt=False)
        order = self.cloud.encrypt_with_key(encode_maybe(pkt)).hex()
        rdt = self.cloud.request('/appliance/transparent/send', {
            'applianceCode': str(self.did),
            'order': order,
            'timestamp': 'true',
        }) or {}
        reply = rdt.get('reply')
        if not reply:
            _LOGGER.warning('%s: cloud control failed: %s', self.name, rdt)
            return None
        try:
            decoded = self.cloud.decrypt_with_key(reply)
            if isinstance(decoded, str):
                raw = decode_maybe(decoded)
            else:
                raw = decode_maybe(decoded)
            if len(raw) > 56:
                return bytes(raw[40:-16])
            return bytes(raw)
        except Exception as exc:
            _LOGGER.warning('%s: decode cloud reply failed: %s', self.name, exc)
            return None

    def read_entity(self, cfg, key=None):
        if self.is_ac:
            return self.ac.get(key or cfg.get('attr'))
        status = self.status
        if not status:
            return None
        idx = cfg.get('byte')
        val = status.get(idx) if idx is not None else None
        if cfg.get('state_template'):
            val = render_template(cfg.get('state_template'), val, status.data)
        elif val is None:
            pass
        elif 'dict' in cfg:
            mapping = cfg.get('dict') or {}
            if isinstance(mapping, dict):
                val = mapping.get(val, mapping.get(str(val), val))
            elif isinstance(mapping, (list, tuple)):
                try:
                    val = mapping[int(val)]
                except (TypeError, ValueError, IndexError):
                    pass
        return val

    def read_attrs(self, cfg):
        status = self.status
        if not status or not cfg.get('attrs_template'):
            return None
        return render_template(cfg.get('attrs_template'), status.get(cfg.get('byte')), status.data)


def encode_maybe(pkt):
    from .cloud import encode_bytes
    return encode_bytes(pkt)


def decode_maybe(text):
    from .cloud import decode_bytes
    if isinstance(text, str):
        return decode_bytes(text.encode('ascii'))
    return decode_bytes(text)
