# -*- coding: utf-8 -*-
"""Midea Meiju protocol library for the Domoticz plugin."""

from .cloud import MeijuCloud
from .const import DEFAULT_PORT, DEFAULT_SCAN_INTERVAL, DEFAULT_SERVER, VERSION
from .customizes import DEVICE_CUSTOMIZES, get_customizes
from .device import MeijuDevice
from .security import get_udpid

__all__ = [
    'MeijuCloud',
    'MeijuDevice',
    'DEVICE_CUSTOMIZES',
    'get_customizes',
    'get_udpid',
    'DEFAULT_PORT',
    'DEFAULT_SCAN_INTERVAL',
    'DEFAULT_SERVER',
    'VERSION',
]
