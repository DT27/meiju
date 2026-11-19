# -*- coding: utf-8 -*-
#
#   美的美居 (Midea Meiju) Python Plugin for Domoticz
#
#   参考 BroadlinkSPMini 插件结构（Zackr，https://www.domoticz.cn/forum/viewtopic.php?t=43）
#   协议移植自 https://github.com/hasscc/meiju  (Home Assistant)
#
#   依赖: pycryptodome (Crypto.Cipher.AES)
#

"""
<plugin key="Meiju" name="Midea Meiju (美的美居)" author="hasscc/meiju" version="1.1.0">
    <description>
        <h2>美的美居</h2>
        <p>使用美的美居账号登录，通过局域网或云端控制设备。</p>
        <p>一台硬件对应一台设备。可先不填「设备 ID (applianceCode)」：日志会打印 applianceCode=一串数字，把该数字填回去即可。账号只有一台设备时会自动选用。</p>
        <ul>
            <li>内置类型: AC 空调 / B0 微波炉 / B3 消毒柜 / DB 洗衣机 / E3 热水器 / EA 电饭煲</li>
            <li>未知类型会创建通用电源开关与状态传感器（字节 11）</li>
        </ul>
    </description>
    <params>
        <param field="Username" label="美居账号" width="180px" required="true"/>
        <param field="Password" label="密码" width="180px" required="true" password="true"/>
        <param field="Address" label="设备 IP" width="140px" required="false" default=""/>
        <param field="Port" label="端口" width="50px" required="true" default="6444"/>
        <param field="Mode1" label="设备 ID (applianceCode)" width="180px" required="false" default=""/>
        <param field="Mode2" label="检测间隔(秒)" width="50px" required="true" default="25"/>
        <param field="Mode3" label="云服务" width="120px">
            <options>
                <option label="中国 (china)" value="china" default="true"/>
                <option label="全球 (global)" value="global"/>
            </options>
        </param>
        <param field="Mode4" label="控制方式" width="120px">
            <options>
                <option label="自动 (局域网优先)" value="auto" default="true"/>
                <option label="仅局域网" value="lan"/>
                <option label="仅云端" value="cloud"/>
            </options>
        </param>
        <param field="Mode5" label="设备类型(可选, 如 B3)" width="80px" required="false" default=""/>
        <param field="Mode6" label="调试" width="75px">
            <options>
                <option label="否" value="0" default="true"/>
                <option label="是" value="1"/>
            </options>
        </param>
    </params>
</plugin>
"""

from __future__ import print_function

import json
import logging
import os
import sys
import time

import Domoticz

if sys.platform.startswith('linux'):
    sys.path.append(os.path.dirname(os.__file__) + '/dist-packages')
elif sys.platform.startswith('darwin'):
    sys.path.append(os.path.dirname(os.__file__) + '/site-packages')
elif sys.platform.startswith('win32'):
    sys.path.append(os.path.dirname(os.__file__) + '\\site-packages')
sys.path.append('/usr/lib/python3/dist-packages')

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

try:
    from meiju import MeijuCloud, MeijuDevice  # noqa: E402
    _IMPORT_ERROR = None
except Exception as exc:  # Crypto 缺失时仍能加载插件并给出明确日志
    MeijuCloud = None
    MeijuDevice = None
    _IMPORT_ERROR = exc

LABELS = {
    'info': '信息',
    'power': '电源',
    'lock': '锁定',
    'status': '状态',
    'temperature': '温度',
    'water_volume': '水量',
    'upstair_status': '上层状态',
    'downstair_status': '下层状态',
    'upstair_temp': '上层温度',
    'downstair_temp': '下层温度',
    'upstair_mode': '上层模式',
    'downstair_mode': '下层模式',
    'upstair_door': '上层门',
    'downstair_door': '下层门',
    'mode': '模式',
    'fan': '风速',
    'swing': '扫风',
    'target_temp': '设定温度',
    'indoor_temp': '室内温度',
    'outdoor_temp': '室外温度',
    'eco': '节能',
    'turbo': '强力',
}


class DomoticzLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        try:
            if record.levelno >= logging.ERROR:
                Domoticz.Error(msg)
            elif record.levelno <= logging.DEBUG:
                Domoticz.Debug(msg)
            else:
                Domoticz.Log(msg)
        except Exception:
            pass


class BasePlugin(object):
    def __init__(self):
        self.cloud = None
        self.device = None
        self.units = {}
        self.lan_ok = False
        self.via_cloud = False
        self.debug = False
        self.beat = 0
        self.poll_every = 1
        self.control_mode = 'auto'

    def onStart(self):
        self.debug = Parameters.get('Mode6') == '1'
        if self.debug:
            Domoticz.Debugging(1)
        self._setup_logging()

        username = (Parameters.get('Username') or '').strip()
        password = Parameters.get('Password') or ''
        host = (Parameters.get('Address') or '').strip()
        port = Parameters.get('Port') or '6444'
        device_id = (Parameters.get('Mode1') or '').strip()
        server = (Parameters.get('Mode3') or 'china').strip() or 'china'
        self.control_mode = (Parameters.get('Mode4') or 'auto').strip() or 'auto'
        type_override = (Parameters.get('Mode5') or '').strip()

        try:
            interval = int(Parameters.get('Mode2') or 25)
        except ValueError:
            interval = 25
        if interval < 5:
            interval = 5
        heartbeat = interval if interval <= 30 else 10
        Domoticz.Heartbeat(heartbeat)
        self.poll_every = max(1, int(round(float(interval) / float(heartbeat))))
        self.beat = 0

        if _IMPORT_ERROR is not None:
            Domoticz.Error('加载 meiju 库失败: %s（需要安装 pycryptodome）' % _IMPORT_ERROR)
            return
        if not username or not password:
            Domoticz.Error('请填写美居账号和密码')
            return

        self.cloud = MeijuCloud(username, password, server=server)
        self._restore_session()
        if not self.cloud.accessToken:
            if not self.cloud.login():
                Domoticz.Error('美居登录失败，请检查账号密码 / 云服务区域')
                return
            self._save_session()
        else:
            try:
                self.cloud.get_homegroups(force_update=True)
            except Exception:
                if not self.cloud.login():
                    Domoticz.Error('美居登录已过期且重新登录失败')
                    return
                self._save_session()

        devices = {}
        try:
            devices = self.cloud.get_devices() or {}
        except Exception as exc:
            Domoticz.Error('获取设备列表失败: %s' % exc)

        self._log_account_devices(devices)

        if not device_id:
            if len(devices) == 1:
                device_id = next(iter(devices))
                hint = self._format_device_hint(device_id, devices.get(device_id) or {})
                Domoticz.Log('未填写「设备 ID (applianceCode)」，账号下仅一台设备，自动使用：%s' % hint)
                Domoticz.Log('建议把 applianceCode=%s 填进硬件设置「设备 ID (applianceCode)」，以免以后增加设备时选错。' % device_id)
            else:
                self._ensure_text_unit(1, '美居设备列表', self._format_device_list(devices))
                self._log_need_appliance_code(devices)
                return

        info = devices.get(str(device_id)) or devices.get(device_id)
        if not info:
            Domoticz.Log('云端列表中未找到设备 %s，将使用本地配置继续' % device_id)
            info = {'applianceCode': device_id, 'name': 'Meiju %s' % device_id[-6:]}
        if type_override:
            info = dict(info)
            if not str(type_override).lower().startswith('0x'):
                info['type'] = '0x%s' % type_override
            else:
                info['type'] = type_override

        config = {
            'host': host,
            'port': port,
            'device_id': device_id,
            'type': info.get('type') or type_override,
        }
        saved = self._load_lan_secret(device_id)
        if saved:
            config['lan_key'] = saved.get('key') or ''
            config['lan_token'] = saved.get('token') or ''

        self.device = MeijuDevice(info, config, self.cloud)
        Domoticz.Log('设备: %s id=%s type=%s sn8=%s ip=%s' % (
            self.device.name, self.device.did, self.device.type_str, self.device.sn8, host or '-',
        ))

        want_lan = self.control_mode in ('auto', 'lan') and bool(host)
        self.via_cloud = self.control_mode == 'cloud' or not host
        if want_lan:
            try:
                self.lan_ok = bool(self.device.auth())
            except Exception as exc:
                Domoticz.Error('局域网认证失败: %s' % exc)
                self.lan_ok = False
            if self.lan_ok:
                self._save_lan_secret(device_id, self.device.lan_key, self.device.lan_token)
                self.via_cloud = self.control_mode == 'cloud'
            elif self.control_mode == 'lan':
                Domoticz.Error('局域网认证失败，且当前为仅局域网模式')
            else:
                Domoticz.Log('局域网不可用，控制将走云端透明传输')
                self.via_cloud = True

        self._create_units()
        self.poll()
        return True

    def onStop(self):
        Domoticz.Log('onStop called')
        return True

    def onConnect(self, Connection, Status, Description):
        return True

    def onMessage(self, Connection, Data):
        return True

    def onCommand(self, Unit, Command, Level, Hue):
        if not self.device:
            Domoticz.Error('设备未初始化')
            return False
        spec = self.units.get(int(Unit))
        if not spec:
            Domoticz.Error('未知 Unit %s' % Unit)
            return False
        kind = spec['kind']
        cfg = spec.get('cfg') or {}
        extra = {}
        value = None
        cmd = str(Command)
        try:
            if kind == 'switch':
                turning_on = cmd.lower() in ('on', '1', 'true')
                if self.device.is_ac:
                    value = turning_on
                elif turning_on:
                    value = int(cfg.get('on_value', 0x01))
                    extra = dict(cfg.get('on_extra') or {})
                else:
                    value = int(cfg.get('off_value', 0x00))
                    extra = dict(cfg.get('off_extra') or {})
            elif kind == 'select':
                options = spec.get('options') or []
                idx = int(round(float(Level) / 10.0))
                if idx < 0 or idx >= len(options):
                    Domoticz.Error('选择档位无效: Level=%s' % Level)
                    return False
                opt = options[idx]
                value = int(opt['value'])
                extra = dict(opt.get('extra') or {})
            elif kind == 'number':
                value = float(Level)
                if cfg.get('min') is not None:
                    value = max(float(cfg['min']), value)
                if cfg.get('max') is not None:
                    value = min(float(cfg['max']), value)
                if not self.device.is_ac:
                    value = int(round(value))
            else:
                Domoticz.Error('该设备不可控制: %s' % spec.get('key'))
                return False
            if self.device.is_ac:
                rsp = self.device.ac_control(spec.get('key'), value, via_cloud=self._use_cloud())
            else:
                extra.update(cfg.get('set_extra') or {})
                if cfg.get('byte') is not None:
                    extra[int(cfg['byte'])] = value
                rsp = self.device.control(extra, via_cloud=self._use_cloud())
            if not rsp:
                Domoticz.Error('控制失败 %s' % spec.get('key'))
            else:
                Domoticz.Log('控制 %s = %s' % (spec.get('label'), value))
        except Exception as exc:
            Domoticz.Error('onCommand 异常: %s' % exc)
        time.sleep(1)
        self.poll()
        return True

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        return

    def onDisconnect(self, Connection):
        return

    def onHeartbeat(self):
        self.beat += 1
        if self.beat < self.poll_every:
            return True
        self.beat = 0
        if self.device:
            self.poll()
        return True

    def poll(self):
        if not self.device:
            return
        try:
            status = self.device.refresh(via_cloud=self._use_cloud())
        except Exception as exc:
            Domoticz.Error('刷新状态失败: %s' % exc)
            return
        if self.debug and status and getattr(status, 'data', None):
            Domoticz.Log('status bytes: %s' % bytes(status.data).hex())
        if self.debug and self.device.is_ac:
            ac = self.device.ac
            Domoticz.Log('AC power=%s mode=%s fan=%s swing=%s set=%s in=%s out=%s' % (
                ac.power, ac.mode, ac.fan, ac.swing, ac.target_temp, ac.indoor_temp, ac.outdoor_temp,
            ))
        self._update_units()

    def _use_cloud(self):
        if self.control_mode == 'cloud':
            return True
        if self.control_mode == 'lan':
            return False
        return (not self.lan_ok) or self.via_cloud

    def _create_units(self):
        self.units = {}
        unit = 1
        cus = self.device.customizes
        unit = self._add_unit(unit, 'sensor', 'info', {}, TypeName='Text')
        for key, cfg in (cus.get('switches') or {}).items():
            unit = self._add_unit(unit, 'switch', key, cfg, TypeName='Switch')
        for key, cfg in (cus.get('selects') or {}).items():
            options = _parse_select_options(cfg)
            names = [o['name'] for o in options] or ['Off']
            opts = {
                'LevelActions': '|'.join([''] * len(names)),
                'LevelNames': '|'.join(names),
                'LevelOffHidden': 'false',
                'SelectorStyle': '1',
            }
            unit = self._add_unit(unit, 'select', key, cfg, TypeName='Selector Switch', Options=opts, extra={'options': options})
        for key, cfg in (cus.get('numbers') or {}).items():
            unit = self._add_unit(unit, 'number', key, cfg, TypeName='Setpoint')
        for key, cfg in (cus.get('sensors') or {}).items():
            type_name = _sensor_typename(key, cfg)
            options = None
            if type_name == 'Custom':
                options = {'Custom': '1;'}
            unit = self._add_unit(unit, 'sensor', key, cfg, TypeName=type_name, Options=options)
        for key, cfg in (cus.get('binary_sensors') or {}).items():
            unit = self._add_unit(unit, 'binary', key, cfg, TypeName='Switch', Switchtype=2)

    def _add_unit(self, unit, kind, key, cfg, TypeName='Switch', Options=None, Switchtype=None, extra=None):
        name = '%s %s' % (self.device.name, LABELS.get(key, key))
        if unit not in Devices:
            kwargs = {
                'Name': name,
                'Unit': unit,
                'TypeName': TypeName,
                'Used': 1,
            }
            if Options is not None:
                kwargs['Options'] = Options
            if Switchtype is not None:
                kwargs['Switchtype'] = Switchtype
            try:
                Domoticz.Device(**kwargs).Create()
            except Exception as exc:
                Domoticz.Error('创建设备失败 Unit=%s %s: %s' % (unit, name, exc))
        spec = {
            'kind': kind,
            'key': key,
            'cfg': cfg or {},
            'label': LABELS.get(key, key),
        }
        if extra:
            spec.update(extra)
        self.units[unit] = spec
        return unit + 1

    def _update_units(self):
        device = self.device
        for unit, spec in self.units.items():
            kind = spec['kind']
            key = spec['key']
            cfg = spec.get('cfg') or {}
            if kind == 'sensor' and key == 'info':
                online = '在线' if device.status else '离线'
                text = '%s | %s | %s | %s' % (online, device.type_str, device.sn8, device.did)
                desc = json.dumps({
                    'name': device.name,
                    'type': device.type_str,
                    'sn8': device.sn8,
                    'model': device.model,
                    'host': device.host,
                    'cloud': self._use_cloud(),
                }, ensure_ascii=False)
                UpdateDevice(unit, 0, text, desc)
                continue
            val = device.read_entity(cfg, key=key)
            attrs = device.read_attrs(cfg)
            desc = json.dumps(attrs, ensure_ascii=False) if isinstance(attrs, dict) else None
            if kind == 'switch':
                on = bool(val)
                UpdateDevice(unit, 1 if on else 0, 'On' if on else 'Off', desc)
            elif kind == 'binary':
                on = bool(val)
                UpdateDevice(unit, 1 if on else 0, 'Open' if on else 'Closed', desc)
            elif kind == 'select':
                options = spec.get('options') or []
                level = 0
                for idx, opt in enumerate(options):
                    if _same_value(opt.get('value'), val) or opt.get('name') == val:
                        level = idx * 10
                        break
                nvalue = 1 if level > 0 else 0
                UpdateDevice(unit, nvalue, str(level), desc)
            elif kind == 'number':
                if val is None:
                    continue
                UpdateDevice(unit, 0, str(val), desc)
            elif kind == 'sensor':
                if val is None:
                    continue
                if _sensor_typename(key, cfg) == 'Temperature':
                    UpdateDevice(unit, 0, str(val), desc)
                else:
                    UpdateDevice(unit, 0, str(val), desc)

    def _ensure_text_unit(self, unit, name, text):
        if unit not in Devices:
            Domoticz.Device(Name=name, Unit=unit, TypeName='Text', Used=1).Create()
        UpdateDevice(unit, 0, text)

    def _format_device_hint(self, did, info=None):
        info = info or {}
        return 'applianceCode=%s  名称=%s  类型=%s  sn8=%s' % (
            did,
            info.get('name') or '',
            info.get('type') or '',
            info.get('sn8') or '',
        )

    def _format_device_list(self, devices):
        if not devices:
            return '未找到设备，请检查美居账号'
        lines = []
        for did, info in devices.items():
            lines.append('applianceCode=%s(%s %s)' % (
                did,
                info.get('name') or '',
                info.get('type') or '',
            ))
        text = '填到硬件「设备 ID (applianceCode)」: ' + ' ; '.join(lines)
        return text[:200]

    def _log_need_appliance_code(self, devices):
        if not devices:
            Domoticz.Log('未填写「设备 ID (applianceCode)」，且账号下没有设备。')
            return
        Domoticz.Log(
            '未填写「设备 ID (applianceCode)」。请把下面某一行的 applianceCode 整串数字'
            '复制到硬件设置「设备 ID (applianceCode)」后重启：'
        )
        for did, info in devices.items():
            Domoticz.Log('  %s' % self._format_device_hint(did, info))

    def _log_account_devices(self, devices):
        if not devices:
            Domoticz.Log('账号下没有设备')
            return
        Domoticz.Log('账号设备 %s 台（applianceCode 即硬件设置里的「设备 ID」）:' % len(devices))
        for did, info in devices.items():
            Domoticz.Log('  %s' % self._format_device_hint(did, info))

    def _setup_logging(self):
        logger = logging.getLogger('meiju')
        logger.handlers = []
        handler = DomoticzLogHandler()
        handler.setFormatter(logging.Formatter('%(name)s: %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG if self.debug else logging.INFO)
        logger.propagate = False

    def _auth_path(self):
        folder = os.path.join(PLUGIN_DIR, 'data')
        if not os.path.isdir(folder):
            try:
                os.makedirs(folder)
            except OSError:
                pass
        username = (Parameters.get('Username') or 'default').strip()
        safe = ''.join(ch if ch.isalnum() else '_' for ch in username)
        return os.path.join(folder, 'auth_%s.json' % safe)

    def _restore_session(self):
        path = self._auth_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, 'r') as fp:
                data = json.load(fp)
            self.cloud.load_session(data.get('session') or {}, data.get('device_id'))
            Domoticz.Log('已加载缓存登录会话')
        except Exception as exc:
            Domoticz.Log('读取登录缓存失败: %s' % exc)

    def _save_session(self):
        try:
            with open(self._auth_path(), 'w') as fp:
                json.dump(self.cloud.export_session(), fp)
        except Exception as exc:
            Domoticz.Log('保存登录缓存失败: %s' % exc)

    def _load_lan_secret(self, device_id):
        path = self._auth_path()
        if not os.path.isfile(path):
            return None
        try:
            with open(path, 'r') as fp:
                data = json.load(fp)
            return (data.get('lan') or {}).get(str(device_id))
        except Exception:
            return None

    def _save_lan_secret(self, device_id, key, token):
        path = self._auth_path()
        data = {}
        if os.path.isfile(path):
            try:
                with open(path, 'r') as fp:
                    data = json.load(fp) or {}
            except Exception:
                data = {}
        data.update(self.cloud.export_session())
        lan = data.get('lan') or {}
        lan[str(device_id)] = {'key': key, 'token': token}
        data['lan'] = lan
        try:
            with open(path, 'w') as fp:
                json.dump(data, fp)
        except Exception as exc:
            Domoticz.Log('保存 LAN key/token 失败: %s' % exc)


def _parse_select_options(cfg):
    raw = (cfg or {}).get('options') or {}
    items = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                num = int(key)
            except (TypeError, ValueError):
                num = key
            if isinstance(value, dict):
                items.append({
                    'value': num,
                    'name': value.get('name', str(key)),
                    'extra': value.get('extra') or {},
                })
            else:
                items.append({'value': num, 'name': str(value), 'extra': {}})
    return items


def _sensor_typename(key, cfg):
    unit = str((cfg or {}).get('unit') or '')
    key_l = str(key).lower()
    if 'temp' in key_l or unit in ('°C', 'C', '℃'):
        return 'Temperature'
    if isinstance((cfg or {}).get('dict'), (list, dict)):
        return 'Text'
    if 'status' in key_l:
        return 'Text'
    return 'Custom'


def _same_value(a, b):
    if a == b:
        return True
    try:
        return int(a) == int(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def UpdateDevice(Unit, nValue, sValue, Description=None):
    if Unit not in Devices:
        return
    device = Devices[Unit]
    sValue = str(sValue)
    changed = device.nValue != nValue or str(device.sValue) != sValue
    if Description is not None and str(device.Description) != str(Description):
        changed = True
    if not changed:
        return
    try:
        if Description is not None:
            device.Update(nValue=nValue, sValue=sValue, Description=str(Description))
        else:
            device.Update(nValue=nValue, sValue=sValue)
    except TypeError:
        device.Update(nValue=nValue, sValue=sValue)
    Domoticz.Log("Update %s:'%s' (%s)" % (nValue, sValue, device.Name))


_plugin = BasePlugin()


def onStart():
    return _plugin.onStart()


def onStop():
    return _plugin.onStop()


def onConnect(Connection, Status, Description):
    return _plugin.onConnect(Connection, Status, Description)


def onMessage(Connection, Data):
    return _plugin.onMessage(Connection, Data)


def onCommand(Unit, Command, Level, Hue):
    return _plugin.onCommand(Unit, Command, Level, Hue)


def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    return _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)


def onDisconnect(Connection):
    return _plugin.onDisconnect(Connection)


def onHeartbeat():
    return _plugin.onHeartbeat()
