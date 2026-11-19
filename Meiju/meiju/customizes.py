# -*- coding: utf-8 -*-
"""Device entity maps, ported from custom_components/meiju/device_customizes.yaml."""

DEVICE_CUSTOMIZES = {
    # 微波炉
    'B0': {
        'get_extra': {10: 0x31},
        'sensors': {
            'status': {
                'byte': 11,
                'dict': ['idle', 'power_on', 'standby', 'working', 'finish', 'order', 'pause', 'pause', 'three'],
            },
        },
    },
    # 消毒柜
    'B3': {
        'get_extra': {10: 0x31},
        'set_extra': {10: 0x21},
        'sensors': {
            'upstair_status': {
                'byte': 11,
                'dict': ['power_off', 'power_on', 'working', 'order', 'finish'],
                'attrs_template': "{{ {'preheat': bytes[26]|bitwise_and(0x02) > 0, 'cooling': bytes[26]|bitwise_and(0x08) > 0} }}",
            },
            'upstair_temp': {'byte': 13},
            'downstair_status': {
                'byte': 16,
                'dict': ['power_off', 'power_on', 'working', 'order', 'finish'],
                'attrs_template': "{{ {'preheat': bytes[26]|bitwise_and(0x01) > 0, 'cooling': bytes[26]|bitwise_and(0x04) > 0} }}",
            },
            'downstair_temp': {'byte': 18},
        },
        'binary_sensors': {
            'upstair_door': {
                'byte': 21,
                'state_template': '{{ value|bitwise_and(0x04) > 0 }}',
            },
            'downstair_door': {
                'byte': 21,
                'state_template': '{{ value|bitwise_and(0x02) > 0 }}',
            },
        },
        'switches': {
            'power': {
                'byte': 11,
                'state_template': '{{ value+bytes[16]+bytes[22] > 0 }}',
                'on_extra': {16: 0x01, 22: 0x01},
                'off_extra': {16: 0x00, 22: 0x00},
            },
            'lock': {'byte': 21},
        },
        'selects': {
            'upstair_mode': {
                'byte': 12,
                'options': {
                    0: {'name': '空闲', 'extra': {11: 0x00}},
                    23: {'name': '保洁(75分钟75℃)', 'extra': {13: 75, 14: 15, 27: 60}},
                    26: {'name': '长效存储(15分钟60℃)', 'extra': {13: 60, 14: 15, 27: 0}},
                },
                'set_extra': {11: 0x02},
            },
            'downstair_mode': {
                'byte': 17,
                'options': {
                    0: {'name': '空闲', 'extra': {16: 0x00}},
                    2: {'name': '烘干(75分钟75℃)', 'extra': {18: 75, 19: 15, 29: 60}},
                    3: {'name': '高温消毒(60分钟125℃)', 'extra': {18: 125, 19: 0, 29: 60}},
                    26: {'name': '长效存储(15分钟95℃)', 'extra': {18: 15, 19: 35, 29: 60}},
                },
                'set_extra': {16: 0x02},
            },
        },
        'numbers': {
            'upstair_temp': {'byte': 13, 'step': 5, 'min': 60, 'max': 125},
            'downstair_temp': {'byte': 18, 'step': 5, 'min': 60, 'max': 125},
        },
    },
    # 洗衣机
    'DB': {
        'get_extra': {10: 0x03},
        'set_extra': {10: 0x02},
        'sensors': {
            'status': {
                'byte': 12,
                'dict': ['idle', 'standby', 'working', 'pause', 'finish', 'fault', 'delay'],
            },
        },
        'switches': {
            'power': {'byte': 11},
        },
    },
    # 热水器
    'E3': {
        'get_extra': {10: 0x03, 11: 0x01, 12: 0x01},
        'sensors': {
            'temperature': {'byte': 17},
            'water_volume': {'byte': 18},
        },
    },
    # 电饭煲
    'EA': {
        'get_extra': {10: 0x03},
        'sensors': {
            'status': {
                'byte': 18,
                'dict': ['idle', 'schedule', 'cooking', 'keep_warn'],
            },
        },
    },
    # 空调（msmart 0xAC，位域协议，不是通用字节映射）
    'AC': {
        'protocol': 'ac',
        'switches': {
            'power': {},
            'eco': {},
            'turbo': {},
        },
        'selects': {
            'mode': {
                'options': {
                    1: '自动',
                    2: '制冷',
                    3: '除湿',
                    4: '制热',
                    5: '送风',
                },
            },
            'fan': {
                'options': {
                    102: '自动',
                    100: '满速',
                    80: '高',
                    60: '中',
                    40: '低',
                    20: '静音',
                },
            },
            'swing': {
                'options': {
                    0: '关闭',
                    12: '上下',
                    3: '左右',
                    15: '全方位',
                },
            },
        },
        'numbers': {
            'target_temp': {'min': 16, 'max': 30, 'step': 1},
        },
        'sensors': {
            'indoor_temp': {'unit': '°C'},
            'outdoor_temp': {'unit': '°C'},
        },
    },
}

DEFAULT_CUSTOMIZES = {
    'switches': {
        'power': {'byte': 11},
    },
    'sensors': {
        'status': {'byte': 11},
    },
}


def get_customizes(type_hex, sn8=None):
    """Merge type-level and sn8-level customizes."""
    cus = {}
    if type_hex:
        key = str(type_hex).replace('0x', '').replace('0X', '')
        found = DEVICE_CUSTOMIZES.get(key.upper()) or DEVICE_CUSTOMIZES.get(key.lower()) or DEVICE_CUSTOMIZES.get(key)
        if found:
            cus.update(found)
    if sn8:
        extra = DEVICE_CUSTOMIZES.get(str(sn8).upper()) or DEVICE_CUSTOMIZES.get(str(sn8))
        if extra:
            cus.update(extra)
    return cus
