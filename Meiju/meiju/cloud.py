# -*- coding: utf-8 -*-
"""Midea Meiju cloud client (China / global), based on hasscc/meiju."""

import json
import logging
import time
import uuid
import hashlib
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .const import CLOUD_SERVERS, DEFAULT_SERVER
from .security import MeijuSecurity, get_udpid

_LOGGER = logging.getLogger(__name__)


def _http_post(url, body, headers, timeout=20):
    data = body.encode('utf-8') if isinstance(body, str) else body
    req = Request(url, data=data, headers=headers, method='POST')
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8', 'replace')
    except HTTPError as exc:
        raw = exc.read().decode('utf-8', 'replace') if exc.fp else ''
        _LOGGER.error('HTTP %s %s: %s', exc.code, url, raw[:300])
        if not raw:
            return {}
    except URLError as exc:
        _LOGGER.error('URL error %s: %s', url, exc)
        return {}
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        _LOGGER.error('Invalid JSON from %s: %s', url, raw[:300])
        return {}


def encode_bytes(data):
    normalized = []
    for b in data:
        if b >= 128:
            b = b - 256
        normalized.append(str(b))
    return bytearray(','.join(normalized).encode('ascii'))


def decode_bytes(data):
    if isinstance(data, str):
        data = data.encode('ascii')
    values = [int(a) for a in data.decode('ascii').split(',') if a != '']
    for i in range(len(values)):
        if values[i] < 0:
            values[i] += 256
    return bytearray(values)


class MeijuCloud(object):
    CLIENT_TYPE = 1
    FORMAT = 2

    def __init__(self, username, password, server=DEFAULT_SERVER):
        self.login_account = username
        self.password = password
        self.server = (server or DEFAULT_SERVER).lower()
        self.use_china = self.server == 'china'
        self.SERVER_URL = CLOUD_SERVERS.get(self.server) or CLOUD_SERVERS[DEFAULT_SERVER]
        if self.use_china:
            self.LANGUAGE = 'zh_CN'
            self.APP_ID = '900'
            self.SRC = '900'
            self.APP_KEY = '46579c15'
        else:
            self.LANGUAGE = 'en_US'
            self.APP_ID = '1010'
            self.SRC = '1010'
            self.APP_KEY = 'ac21b9f9cbfe4ca5a88562ef25e2b768'
        self.login_id = None
        self.session = {}
        self.home_groups = []
        self.accessToken = ''
        self.device_id = '86%s' % int(time.time() * 1000)
        self.security = MeijuSecurity(use_china_server=self.use_china)

    @property
    def uid(self):
        return (self.session or {}).get('uid')

    @property
    def data_key(self):
        key = (self.session or {}).get('key', '')
        if not key:
            return None
        try:
            return self.security.decrypt_with_key(key)
        except Exception as exc:
            _LOGGER.warning('decrypt data_key failed: %s', exc)
            return None

    def decrypt_with_key(self, data):
        key = self.data_key
        if not key:
            return data
        try:
            return self.security.decrypt_with_key(data, key)
        except Exception as exc:
            _LOGGER.debug('decrypt_with_key failed: %s', exc)
            return data

    def encrypt_with_key(self, data):
        key = self.data_key
        if not key:
            return self.security.encrypt_with_key(data)
        return self.security.encrypt_with_key(data, key)

    @staticmethod
    def build_params(dat):
        dat = dict(dat or {})
        dat['reqId'] = hashlib.md5(uuid.uuid1().bytes).hexdigest()
        dat['stamp'] = time.strftime('%Y%m%d%H%M%S')
        return dat

    def load_session(self, session, device_id=None):
        session = session or {}
        token = (session.get('mdata') or {}).get('accessToken')
        if not token:
            return False
        self.session = session
        self.accessToken = token
        if device_id:
            self.device_id = device_id
        return True

    def export_session(self):
        return {
            'username': self.login_account,
            'session': self.session,
            'device_id': self.device_id,
            'server': self.server,
            'update_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }

    def _api_url(self, api):
        if api.startswith('http://') or api.startswith('https://'):
            return api
        return '%s%s' % (self.SERVER_URL, api)

    def api_request(self, endpoint, args=None, data=None):
        """msmart-style request used by login / getToken."""
        args = args or {}
        if data is None:
            data = {
                'appId': self.APP_ID,
                'format': self.FORMAT,
                'clientType': self.CLIENT_TYPE,
                'language': self.LANGUAGE,
                'src': self.SRC,
                'stamp': time.strftime('%Y%m%d%H%M%S'),
            }
        data.update(args)
        if not data.get('reqId'):
            data['reqId'] = uuid.uuid4().hex
        url = self._api_url(endpoint)
        payload = json.dumps(data)
        random = str(int(time.time()))
        headers = {
            'Content-Type': 'application/json',
            'secretVersion': '1',
            'sign': self.security.new_sign(payload, random),
            'random': random,
            'accessToken': self.accessToken or '',
        }
        response = _http_post(url, payload, headers)
        if not response:
            return {}
        code = response.get('code')
        try:
            code_i = int(code)
        except (TypeError, ValueError):
            code_i = 0
        if code_i != 0:
            _LOGGER.warning('api_request %s failed: %s', endpoint, response)
            return response.get('data') or {}
        return response.get('data') or {}

    def request(self, api, params=None, _retried=False):
        """hasscc/meiju async_request equivalent (device list, transparent send)."""
        params = params or {}
        if self.use_china:
            if api[:3] not in ('/v1', 'v1/'):
                api = '/v1/%s' % api.lstrip('/')
            url = self._api_url(api)
            payload_obj = self.build_params(params)
            payload = json.dumps(payload_obj, separators=(',', ':'))
            random = str(int(time.time() * 1000))
            headers = {
                'Content-Type': 'application/json; charset=utf-8',
                'User-Agent': 'meiju/7.8.0 (Android;Victoria7.1.1)',
                'sign': self.security.new_sign(payload, random),
                'random': random,
                'accessToken': self.accessToken or '',
                'secretVersion': '1',
                'platform': '0',
            }
            dat = _http_post(url, payload, headers) or {}
            dat = dat.get('data') or dat
        else:
            dat = self.api_request(api, params) or {}
        code = dat.get('code')
        if code:
            _LOGGER.warning('request api %s: %s', api, dat)
        if code in (1008, 40002, '1008', '40002') and not _retried:
            self.session = {}
            self.accessToken = ''
            if self.login():
                return self.request(api, params, _retried=True)
        return dat

    def get_login_id(self):
        response = self.api_request('/v1/user/login/id/get', {
            'loginAccount': self.login_account,
        })
        self.login_id = (response or {}).get('loginId')
        return self.login_id

    def login(self):
        if self.session and self.accessToken:
            return True
        self.login_id = None
        self.session = {}
        self.accessToken = ''
        if not self.get_login_id():
            _LOGGER.error('get_login_id failed for %s', self.login_account)
            return False
        dat = {
            'iotData': self.build_params({
                'clientType': 1,
                'iampwd': self.security.encrypt_iam_password(self.login_id, self.password),
                'iotAppId': self.APP_ID,
                'loginAccount': self.login_account,
                'password': self.security.encryptPassword(self.login_id, self.password),
            }),
            'data': {
                'appKey': self.APP_KEY,
                'deviceId': self.device_id,
                'platform': 2,
            },
        }
        self.session = self.api_request('/mj/user/login', data=dat) or {}
        self.accessToken = (self.session.get('mdata') or {}).get('accessToken')
        if not self.accessToken:
            _LOGGER.error('Login failed for %s: %s', self.login_account, self.session)
            return False
        _LOGGER.info('Login success uid=%s', self.uid)
        return True

    def get_homegroups(self, force_update=False):
        if not self.home_groups or force_update:
            rsp = self.request('homegroup/list/get') or {}
            self.home_groups = rsp.get('homeList', rsp.get('list', [])) or []
        return self.home_groups or []

    def get_devices(self):
        devices = {}
        for home in self.get_homegroups(force_update=True):
            hgi = home.get('homegroupId') or home.get('id')
            try:
                count = int(home.get('applianceCount', -1))
            except (TypeError, ValueError):
                count = -1
            if not hgi or count == 0:
                continue
            rsp = self.request('appliance/home/list/get', {
                'homegroupId': hgi,
                'uiTemplate': '1',
            }) or {}
            for house in rsp.get('homeList') or []:
                for room in house.get('roomList') or []:
                    for appliance in room.get('applianceList') or []:
                        did = appliance.get('applianceCode')
                        if did:
                            devices[str(did)] = appliance
        return devices

    def gettoken(self, udpid):
        response = self.api_request('/v1/iot/secure/getToken', {'udpid': udpid}) or {}
        for token in response.get('tokenlist') or []:
            if token.get('udpId') == udpid:
                return token.get('token'), token.get('key')
        return None, None

    def get_lan_token(self, appliance_id):
        appliance_id = int(appliance_id)
        for byteorder in ('big', 'little'):
            udpid = get_udpid(appliance_id.to_bytes(6, byteorder))
            token, key = self.gettoken(udpid)
            if token and key:
                return token, key, byteorder
        return None, None, None
