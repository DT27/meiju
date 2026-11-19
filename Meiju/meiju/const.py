# -*- coding: utf-8 -*-
"""Constants for the Midea Meiju protocol."""

VERSION = '1.0.0'

DEFAULT_PORT = 6444
DEFAULT_SERVER = 'china'
DEFAULT_SCAN_INTERVAL = 25

CLOUD_SERVERS = {
    'china': 'https://mp-prod.smartmidea.net/mas/v5/app/proxy?alias=',
    'global': 'https://mp-prod.appsmb.com/mas/v5/app/proxy?alias=',
}

MSGTYPE_HANDSHAKE_REQUEST = 0x0
MSGTYPE_HANDSHAKE_RESPONSE = 0x1
MSGTYPE_ENCRYPTED_RESPONSE = 0x3
MSGTYPE_ENCRYPTED_REQUEST = 0x6
MSGTYPE_TRANSPARENT = 0xf

CMD_TYPE_CONTROL = 0x02
CMD_TYPE_QUERY = 0x03
CMD_TYPE_REPORT = 0x04
CMD_TYPE_ABNL_REPORT = 0x06

# Keep the original spelling used by msmart
CMD_TYPE_QUERRY = CMD_TYPE_QUERY
