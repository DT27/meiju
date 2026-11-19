# -*- coding: utf-8 -*-
"""Minimal Home Assistant Jinja subset used by device_customizes.yaml."""

import re

_BITWISE_RE = re.compile(r'([A-Za-z0-9_\[\]\.]+)\|bitwise_and\(([^)]+)\)')
_BRACES_RE = re.compile(r'^\s*\{\{(.*)\}\}\s*$', re.DOTALL)


class ByteList(list):
    def __getitem__(self, index):
        try:
            return list.__getitem__(self, index)
        except (IndexError, TypeError):
            return 0


def _to_python(expr):
    while True:
        replaced = _BITWISE_RE.sub(r'(\1 & \2)', expr)
        if replaced == expr:
            break
        expr = replaced
    return expr


def render_template(tpl, value, data):
    if not tpl:
        return value
    tpl = str(tpl).strip()
    match = _BRACES_RE.match(tpl)
    expr = match.group(1).strip() if match else tpl
    expr = _to_python(expr)
    env = {
        'value': 0 if value is None else value,
        'bytes': ByteList(data or []),
    }
    try:
        return eval(expr, {'__builtins__': {}}, env)  # noqa: S307  # intentional tiny template eval
    except Exception:
        return value
