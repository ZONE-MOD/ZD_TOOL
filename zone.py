#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import itertools as it
import math
import struct
import shutil
import zipfile
import os
import sys
import uuid
import hashlib
import platform
import subprocess
import requests
import base64
import zlib
import ctypes
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePath, Path
from typing import List, Dict, Tuple, Optional, Any
import time
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table
from rich import print as rprint
from rich.markup import escape
from rich.text import Text
from rich.align import Align
from rich.console import Group
from rich.live import Live
from rich.segment import Segment
from rich.style import Style
from rich.console import ConsoleOptions


def _live_time_text(expiry_date, now=None):
    now = now or datetime.now()
    total = max(0, int((expiry_date - now).total_seconds()))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    return f"{days}d {hours:02d}h {mins:02d}m {secs:02d}s"

def _render_live_time(expiry_date):
    return Panel(
        Align.center(
            Text(_live_time_text(expiry_date), style="bold #00F5D4"),
            vertical="middle",
        ),
        title="[bold #00F5D4]LIVE TIME KEY[/]",
        border_style="#00F5D4",
        padding=(0, 2),
    )

def show_live_time_key(expiry_date, seconds=1):
    with Live(_render_live_time(expiry_date), refresh_per_second=1,
              transient=False, screen=False) as live:
        while datetime.now() < expiry_date:
            live.update(_render_live_time(expiry_date), refresh=True)
            time.sleep(seconds)
from rich.box import HEAVY_EDGE, ROUNDED, DOUBLE_EDGE
from rich.prompt import Prompt
from rich.layout import Layout
from datetime import datetime, timedelta, timezone
import pytz
import gmalg
from Crypto.Cipher import AES
from Crypto.Cipher.AES import MODE_CBC
from Crypto.Hash import SHA1
from Crypto.Util.Padding import unpad
from zstandard import ZstdDecompressor, ZstdCompressionDict, DICT_TYPE_AUTO, ZstdCompressor

console = Console()


def _enforce_tool_path():
    """Only allow the tool to run from the official Termux path/name."""
    try:
        allowed = (Path.home() / "ZD_TOOL" / "zone.pyc").resolve()
        current = Path(__file__).resolve()
        if current != allowed:
            raise SystemExit(0)
    except Exception:
        raise SystemExit(0)


# ==================== REFERENCE RGB UI ENGINE ====================
# Visual-only layer.  It intentionally uses only Rich/stdlib so it remains
# friendly to Termux.  The border is a smooth, time-shifted neon spectrum;
# content is kept blue to match the supplied reference screens.
import colorsys

_UI_RGB_STOPS = (
    (0, 225, 255),    # electric cyan
    (0, 102, 255),    # electric blue
    (77, 45, 255),    # indigo
    (190, 35, 255),   # violet
    (255, 35, 180),   # pink
    (255, 80, 120),   # rose
    (255, 170, 35),   # warm orange
    (120, 255, 55),   # lime
    (0, 225, 255),    # close the loop
)


def _rgb_mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _rgb_hex(h):
    # Kept for compatibility with the existing UI helpers.
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, 0.95, 1.0)
    return '#%02X%02X%02X' % (int(r * 255), int(g * 255), int(b * 255))


def _ui_rgb_color(position, speed=0.055):
    # Slow, smooth movement: visually closer to the reference than a rapid
    # flashing rainbow while still being unmistakably animated.
    phase = (time.monotonic() * speed + position / 18.0) % 1.0
    scaled = phase * (len(_UI_RGB_STOPS) - 1)
    idx = int(scaled)
    frac = scaled - idx
    rgb = _rgb_mix(_UI_RGB_STOPS[idx], _UI_RGB_STOPS[min(idx + 1, len(_UI_RGB_STOPS) - 1)], frac)
    return '#%02X%02X%02X' % rgb


def _ui_rainbow_style(index=0):
    return Style.parse(_ui_rgb_color(index, 0.035))


def _ui_rainbow_text(text, offset=0, bold=True):
    out = Text()
    for i, ch in enumerate(str(text)):
        style = f'bold {_ui_rgb_color(i + offset, 0.035)}' if bold else _ui_rgb_color(i + offset, 0.035)
        out.append(ch, style=style)
    return out


def _ui_border_color(distance, perimeter, speed=0.16):
    # Continuous clockwise neon wave around the complete frame.
    perimeter = max(1, perimeter)
    phase = (time.monotonic() * speed - (distance / perimeter)) % 1.0
    return _rgb_hex(phase)


class RainbowPanel:
    """Reference-inspired premium terminal frame with a larger animated RGB edge."""
    def __init__(self, body, title='', subtitle='', width=None, padding=2, vertical_padding=0):
        self.body = body
        self.title = str(title or '')
        self.subtitle = str(subtitle or '')
        self.width = width
        self.padding = padding
        self.vertical_padding = max(0, int(vertical_padding))

    def __rich_console__(self, console, options: ConsoleOptions):
        maxw = self.width or options.max_width
        maxw = max(44, min(maxw, options.max_width))
        border_width = maxw - 2
        inner_width = maxw - 2
        body_width = max(12, inner_width - (self.padding * 2))
        body_options = options.update_width(body_width)
        lines = console.render_lines(self.body, body_options, pad=False, new_lines=False) or [[]]

        def fit(line, target):
            try:
                length = Segment.get_line_length(line)
            except Exception:
                length = 0
            if length < target:
                return line + [Segment(' ' * (target - length))]
            if length > target:
                out, used = [], 0
                for seg in line:
                    sl = len(seg.text)
                    if used >= target:
                        break
                    take = min(sl, target - used)
                    if take:
                        out.append(Segment(seg.text[:take], seg.style))
                        used += take
                return out
            return line

        def emit_blank(seed):
            yield Segment('│', style=Style.parse(_ui_border_color(seed, max(1, body_width), 0.16)))
            if self.padding:
                yield Segment(' ' * self.padding)
            yield Segment(' ' * body_width)
            if self.padding:
                yield Segment(' ' * self.padding)
            yield Segment('│', style=Style.parse(_ui_border_color(seed + 20, max(1, body_width), 0.16)))
            yield Segment.line()

        # Larger, more visible frame while preserving the exact square-corner
        # reference language. The RGB edge is smooth and time-shifted rather
        # than flashing, so it stays readable on a phone terminal.
        label = f' {self.title} ' if self.title else ''
        if len(label) > border_width - 4:
            label = label[:max(1, border_width - 7)] + '... ' 
        left = max(1, (border_width - len(label)) // 2)
        right = max(1, border_width - len(label) - left)

        # Continuous clockwise RGB strip. The color wave crosses corners
        # smoothly instead of resetting on each side.
        perimeter = max(4, (border_width * 2) + max(1, len(lines)) + (self.vertical_padding * 2) + 2)
        cursor = 0

        def border_seg(ch):
            nonlocal cursor
            seg = Segment(ch, style=Style.parse(_ui_border_color(cursor, perimeter, 0.16)))
            cursor += len(ch)
            return seg

        yield border_seg('┌')
        for _ in range(left):
            yield border_seg('─')
        if label:
            yield Segment(label, style=Style.parse('bold italic ' + _ui_border_color(cursor, perimeter, 0.16)))
        cursor += len(label)
        for _ in range(right):
            yield border_seg('─')
        yield border_seg('┐')
        yield Segment.line()

        for n in range(self.vertical_padding):
            yield from emit_blank(8 + n * 7)

        for row, line in enumerate(lines):
            line = fit(line, body_width)
            yield Segment('│', style=Style.parse(_ui_border_color(cursor, perimeter, 0.16)))
            cursor += 1
            if self.padding:
                yield Segment(' ' * self.padding)
            yield from line
            if self.padding:
                yield Segment(' ' * self.padding)
            yield Segment('│', style=Style.parse(_ui_border_color(cursor, perimeter, 0.16)))
            cursor += 1
            yield Segment.line()

        if self.subtitle:
            sub = Text(self.subtitle, style='bold italic ' + _ui_border_color(cursor, perimeter, 0.16))
            slines = console.render_lines(sub, options.update_width(body_width), pad=False) or [[]]
            for row, line in enumerate(slines):
                line = fit(line, body_width)
                yield Segment('│', style=Style.parse(_ui_border_color(cursor, perimeter, 0.16)))
                cursor += 1
                if self.padding:
                    yield Segment(' ' * self.padding)
                yield from line
                if self.padding:
                    yield Segment(' ' * self.padding)
                yield Segment('│', style=Style.parse(_ui_border_color(cursor, perimeter, 0.16)))
                cursor += 1
                yield Segment.line()

        for n in range(self.vertical_padding):
            yield from emit_blank(76 + n * 7)

        yield border_seg('└')
        for _ in range(border_width):
            yield border_seg('─')
        yield border_seg('┘')
        yield Segment.line()



# ==================== UNPACK LIVE RGB LOG ====================
_UNPACK_LOGS = []
_UNPACK_UI_ACTIVE = False


def _ui_unpack_log(filename, encryption, compression, status='Extracting'):
    """Store presentation-only extraction history for the animated HUD."""
    global _UNPACK_LOGS
    _UNPACK_LOGS.append((str(filename), str(encryption), str(compression), str(status)))
    if len(_UNPACK_LOGS) > 7:
        _UNPACK_LOGS = _UNPACK_LOGS[-7:]


def _reference_unpack_text(filename, encryption, compression):
    row1 = Text.assemble(
        ('Extracting: ', 'bold italic #00E5FF'),
        (str(filename), 'bold italic #00E5FF'),
    )
    row2 = Text.assemble(
        ('Encryption: ', 'bold italic #00FF44'),
        (str(encryption), 'bold italic #00FF44'),
        (' / ', 'bold italic #FFD400'),
        ('Compression: ', 'bold italic #FF00C8'),
        (str(compression), 'bold italic #FF00C8'),
    )
    return Group(row1, row2)


def _unpack_log_card(filename, encryption, compression, status='Extracting'):
    # One compact reference card: title + two information rows.
    return RainbowPanel(
        _reference_unpack_text(filename, encryption, compression),
        'Extracting',
        width=None, padding=1, vertical_padding=0
    )


def _unpack_complete_card(done, output_path):
    body = Text.assemble(
        ('Extracted ', 'bold italic #00FF44'),
        (str(done), 'bold italic #00FF44'),
        (' file(s) to', 'bold italic #00FF44'),
        ('\n' + str(output_path), 'bold italic #00FF44'),
    )
    return RainbowPanel(body, 'Unpack Complete', width=None, padding=1, vertical_padding=0)


def _unpack_hud_renderable(filename: str, done: int, total: int, final: bool = False, output_path=None):
    """Reference-style vertical extraction train.

    New cards are appended at the bottom. The visible area contains the latest
    seven cards, with no blank placeholder cards in between.
    """
    visible = 7
    logs = list(_UNPACK_LOGS[-visible:])
    cards = [_unpack_log_card(*item) for item in logs]

    if final:
        cards.append(_unpack_complete_card(done, output_path or ''))

    return Group(*cards)



def _repack_log_card(block, filename, status):
    body = Text.assemble(
        ('Repacking: ', 'bold italic #00E5FF'),
        (str(filename), 'bold italic #00E5FF'),
        ('\nBlock: ', 'bold italic #00E5FF'),
        (str(block), 'bold italic #00E5FF'),
        ('  |  ', 'bold #FFD400'),
        (str(status), 'bold italic #00FF44' if 'SKIPPED' not in str(status) else 'bold italic #FF00C8'),
    )
    return RainbowPanel(
        body,
        'Repacking',
        width=None,
        padding=1,
        vertical_padding=0,
    )


class SimpleBlockDisplay:
    """Presentation-only repack log stream; processing state is unchanged."""
    HISTORY_ROWS = 7

    def __init__(self, total_files: int, pak_name: str):
        self.total_files = total_files
        self.pak_name = pak_name
        self.processed_files = 0
        self.current_file = ''
        self.current_file_idx = 0
        self.all_blocks = []
        self.total_fitted = 0
        self.total_skipped = 0
        self.current_blocks = []
        self.current_total_blocks = 0
        self.current_fitted = 0
        self.current_skipped = 0
        self._history = []
        self._live = Live(
            self._render(),
            console=console,
            refresh_per_second=20,
            transient=False,
            screen=False,
        )
        self._live.start(refresh=True)

    def _render(self):
        history = self._history[-self.HISTORY_ROWS:]
        cards = [
            _repack_log_card(h['block'], h['file'], h['status'])
            for h in history
        ]

        # While the first file has not produced a block yet, show one card.
        if not cards:
            cards.append(_repack_log_card(
                '---',
                self.current_file or self.pak_name,
                'Preparing PAK...'
            ))

        return Group(*cards)

    def _update(self):
        if self._live:
            self._live.update(self._render(), refresh=True)

    def start_file(self, file_name, total_blocks):
        self.current_file_idx += 1
        self.current_file = file_name
        self.current_blocks = []
        self.current_total_blocks = total_blocks
        self.current_fitted = 0
        self.current_skipped = 0
        self._update()

    def add_block(self, block_idx, block_size, fitted, compression_ratio=None):
        size_mb = block_size / (1024 * 1024)
        if fitted:
            self.current_fitted += 1
            self.total_fitted += 1
            status = f'OK {compression_ratio:.1%}' if compression_ratio else 'OK'
        else:
            self.current_skipped += 1
            self.total_skipped += 1
            status = 'SKIPPED'

        self.current_blocks.append({'fitted': fitted})
        self._history.append({
            'block': f'{block_idx:03d}',
            'file': self.current_file,
            'status': f'{size_mb:.2f}MB {status}',
        })
        if len(self._history) > self.HISTORY_ROWS:
            self._history = self._history[-self.HISTORY_ROWS:]
        self._update()

    def finish_file(self):
        total_blocks = len(self.current_blocks)
        if total_blocks > 0:
            if self.current_fitted == total_blocks:
                status = f'ALL FITTED {self.current_fitted}/{total_blocks}'
            elif self.current_fitted > 0:
                status = f'{self.current_fitted}/{total_blocks} FITTED'
            else:
                status = 'ALL SKIPPED'
        else:
            status = 'DONE'

        self._history.append({
            'block': 'DONE',
            'file': self.current_file,
            'status': status,
        })
        self.processed_files += 1
        self.all_blocks.append({
            'file': self.current_file,
            'fitted': self.current_fitted,
            'skipped': self.current_skipped,
        })
        if len(self._history) > self.HISTORY_ROWS:
            self._history = self._history[-self.HISTORY_ROWS:]
        self._update()

    def final_summary(self):
        final = Table.grid(expand=True, padding=(0, 1))
        final.add_column(style='bold #00FF44', width=12)
        final.add_column(style='bold #00FF44')
        final.add_row('FILES', f'{self.processed_files} / {self.total_files}')
        final.add_row('FITTED', str(self.total_fitted))
        final.add_row('SKIPPED', str(self.total_skipped))
        final.add_row('PAK', self.pak_name)

        complete = RainbowPanel(
            final,
            'Repack Complete',
            width=None,
            padding=1,
            vertical_padding=0,
        )
        self._live.update(Group(self._render(), complete), refresh=True)
        time.sleep(0.35)
        self._live.stop()
        self._live = None


# ==================== CONSTANTS ====================

ZUC_KEY = bytes.fromhex('01010101010101010101010101010101')
ZUC_IV = bytes.fromhex('FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF')

RSA_MOD_1 = bytes.fromhex('CBE8B9F2504050EF9831B719E9A6249A6D238505ADE909BDE78C180DED6072A0C3347B8AF4780E1F212D952D82D4BF7F233C1ECA499E1F9D9A85B4FAD759F54BABC1666C5DE411EA9E4B2374425DD6C6F54333BBC8F2610FE6063E4D0D6C21A671A8F7C3740555E5DC06D4E1691C456DB4116C0C012BF7B206E8311AAAEC689952BF804EF638F09D5822B4117B114208F14DEB459E80CB770E5B0D7978E21F5E6CED4999D3583108221A7AB28B960277ADB5690A332784019D9C195BE4EA9EA0A09459010F236465DE0D59C3EF7324E954E1118D93EE19F299760C2CDB963CE87973EA5ECC9BBE81C27D4C7C8572AC07E9BCEAC9BD72AB7A56A3C0AD736ABCE4')
RSA_MOD_2 = bytes.fromhex('7F58E8A39A4DA4E87357DDD650EAA16D3B5CE95B213D1030A662566444796A78A84AE9AC3DBFFDE7F41094896696835DAF13B89E6EC2B84963B1B1BAF7151DA245C3FBFAE2A6AE18B2684D03F9229DE2C91440F2A3A3BCDE1E5680C16722A88039C73560D5D43F4B6562C2EEA5B1D926D86B51108A2643C70FB74D6442CE3A08339B8FD8F660AE88129B7AB8C46F2FA58124485CCCB1E987B05A6DA65A01858ED3F89905449AE42BB07290FCB9994BF22E26610BCABB9804783A3B9587917F3D97316EDDA15C5E13F79066407B55A93B291B68A4AC42A98D6E35FED84B14A792D154E62028DDAD20FC301951E5924BE9AD62FB719DD94CC30CAB871BEC4377A8')

SIMPLE1_DECRYPT_KEY = 121
SIMPLE2_DECRYPT_KEY = bytes.fromhex('E55B4ED1')
SIMPLE2_BLOCK_SIZE = 16

SM4_SECRET_4 = 'eb691efea914241317a8'
SM4_SECRET_2 = 'Q0hVTKey$as*1ZFlQCiA'
SM4_SECRET_NEW = [
    'xG2qW5lP7lV2iN5fN5pG', 'xT1cJ6dL5wC0kK1rB4dK', 'qC4jS5bZ6fL5xE6nD4zA',
    'gD4jQ2aL3bS3lC3xT0iW', 'xU1yQ8wE9zY3gZ3bT5aE', 'uQ3cO2dX7xY4xU7gH7iS',
    'gW1fR0jK6wQ4oN0oK1kZ', 'aJ4pV7iZ7pU4wP2aC2cZ', 'cX6jT3cM2oT3vK0kJ1qN',
    'iT2vS0cS6yT6cZ1sE1lO', 'hM1pH9iY8wM9hT4lN5uJ', 'kG6bC8jK0fL0dE4sH4mL',
    'dB6lB3vE0eZ8wM8rI0aC', 'tP7sP7nI9rA2vQ4cV5yQ', 'aT0cL1yN4pT3sZ7eM2vY',
    'uV6fU8fC9zN3mP5dH8mN', 'rT6aQ6oZ1yM0gO5tO1aN', 'jU5bH7lQ0fM9hK2kI0oF',
    'iQ0eM0mJ7uT0kV6kL5zY',
]

EM_SIMPLE1 = 1
EM_SIMPLE2 = 16
EM_SM4_2 = 2
EM_SM4_4 = 4
EM_SM4_NEW_BASE = 31
EM_SM4_NEW_MASK = ~EM_SM4_NEW_BASE

CM_NONE = 0
CM_ZLIB = 1
CM_ZSTD = 6
CM_ZSTD_DICT = 8
CM_MASK = 15

# ==================== UTILITY ====================

def sanitize_path(path) -> Path:
    """Sanitize path and remove invalid characters"""
    try:
        name = str(path)
        name = name.replace('\x00', '')
        name = ''.join(c for c in name if ord(c) >= 32 or c in '/\\:.')
        invalid_chars = '<>:"|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        name = name.strip()
        if not name or name == '.' or name == '..':
            name = "root"
        return Path(name)
    except Exception:
        return Path("root")

def clean_pak_path(path_str: str) -> str:
    """Clean PAK path and remove unsafe parent traversal"""
    if not path_str:
        return ""
    if path_str.startswith('/'):
        path_str = path_str[1:]
    parts = path_str.split('/')
    parts = [p for p in parts if p and p != '..']
    return '/'.join(parts)

class SM4:
    _S_BOX = bytes([
        52, 102, 37, 116, 137, 120, 228, 169, 90, 65, 188, 122, 214, 22, 33, 35,
        77, 97, 218, 148, 155, 223, 19, 60, 105, 58, 49, 10, 95, 215, 153, 149,
        241, 174, 114, 61, 7, 96, 36, 182, 152, 238, 196, 162, 45, 136, 221, 141,
        4, 234, 187, 17, 202, 62, 93, 161, 246, 63, 176, 151, 128, 71, 43, 166,
        230, 247, 217, 177, 89, 192, 124, 190, 84, 40, 183, 126, 79, 248, 67, 110,
        160, 80, 14, 245, 144, 184, 251, 163, 123, 98, 25, 70, 3, 42, 185, 143,
        159, 119, 180, 91, 131, 135, 8, 235, 226, 30, 66, 240, 15, 232, 113, 106,
        117, 173, 85, 31, 181, 171, 51, 250, 127, 21, 189, 133, 216, 6, 104, 179,
        82, 48, 72, 11, 0, 237, 239, 178, 87, 142, 231, 108, 213, 229, 46, 83,
        130, 5, 249, 129, 244, 86, 191, 140, 75, 227, 219, 74, 145, 76, 44, 211,
        64, 41, 78, 32, 20, 54, 121, 9, 111, 209, 55, 224, 57, 12, 138, 146,
        56, 18, 53, 109, 225, 253, 147, 154, 23, 212, 201, 156, 107, 132, 38, 157,
        175, 118, 193, 158, 208, 150, 197, 203, 233, 115, 73, 210, 205, 100, 195, 199,
        1, 125, 243, 172, 252, 222, 164, 68, 50, 27, 194, 186, 28, 2, 198, 39,
        69, 139, 242, 24, 167, 16, 81, 29, 200, 207, 99, 255, 47, 13, 88, 206,
        101, 165, 220, 26, 59, 134, 254, 34, 92, 168, 94, 103, 170, 236, 112, 204
    ])
    _FK = [1184304796, 1270900830, 1493524870, 3164752158]
    _CK = [964907, 973793155, 2654690407, 2916866751, 2071233739, 1226140771, 3348805095, 2045549823, 388349611, 800627875, 612403927, 3721562911, 1195432523, 3150178931, 612053223, 2445162591, 67183755, 1174197155, 1393249511, 3331183455, 3822152747, 1332317203, 1804781383, 1990130463, 1282653851, 3376591251, 2910902311, 925872959, 332098219, 735840931, 396665415, 3588844719]
    
    @staticmethod
    def ROL32(x, n):
        return (x << n) & 0xFFFFFFFF | (x >> (32 - n))
    
    @staticmethod
    def _BS(X):
        return (SM4._S_BOX[X >> 24 & 255] << 24 | 
                SM4._S_BOX[X >> 16 & 255] << 16 | 
                SM4._S_BOX[X >> 8 & 255] << 8 | 
                SM4._S_BOX[X & 255])
    
    @staticmethod
    def _T0(X):
        X = SM4._BS(X)
        return X ^ SM4.ROL32(X, 2) ^ SM4.ROL32(X, 10) ^ SM4.ROL32(X, 18) ^ SM4.ROL32(X, 24)
    
    @staticmethod
    def _T1(X):
        X = SM4._BS(X)
        return X ^ SM4.ROL32(X, 13) ^ SM4.ROL32(X, 23)
    
    @staticmethod
    def _key_expand(key: bytes, rkey: list):
        K0 = int.from_bytes(key[0:4], 'big') ^ SM4._FK[0]
        K1 = int.from_bytes(key[4:8], 'big') ^ SM4._FK[1]
        K2 = int.from_bytes(key[8:12], 'big') ^ SM4._FK[2]
        K3 = int.from_bytes(key[12:16], 'big') ^ SM4._FK[3]
        for i in range(0, 32, 4):
            K0 = K0 ^ SM4._T1(K1 ^ K2 ^ K3 ^ SM4._CK[i])
            rkey[i] = K0
            K1 = K1 ^ SM4._T1(K2 ^ K3 ^ K0 ^ SM4._CK[i + 1])
            rkey[i + 1] = K1
            K2 = K2 ^ SM4._T1(K3 ^ K0 ^ K1 ^ SM4._CK[i + 2])
            rkey[i + 2] = K2
            K3 = K3 ^ SM4._T1(K0 ^ K1 ^ K2 ^ SM4._CK[i + 3])
            rkey[i + 3] = K3
    
    @classmethod
    def key_length(cls):
        return 16
    
    @classmethod
    def block_length(cls):
        return 16
    
    def __init__(self, key: bytes):
        if len(key) != self.key_length():
            raise ValueError(f'Key must be {self.key_length()} bytes')
        else:
            self._key = key
            self._rkey = [0] * 32
            SM4._key_expand(self._key, self._rkey)
            self._block_buffer = bytearray()
            if not hasattr(SM4, '_T_TABLES'):
                SM4._T_TABLES = SM4._make_t_tables()
    
    def encrypt_bulk(self, data: bytes) -> bytes:
        lib = _load_fast_sm4()
        if lib is not None:
            data = bytes(data)
            n = len(data)
            inbuf = ctypes.create_string_buffer(data)
            outbuf = ctypes.create_string_buffer(n)
            lib.sm4_ecb(ctypes.create_string_buffer(self._key), inbuf, outbuf, n, 1)
            return outbuf.raw
        return self._bulk(data, self._rkey)

    def decrypt_bulk(self, data: bytes) -> bytes:
        lib = _load_fast_sm4()
        if lib is not None:
            data = bytes(data)
            n = len(data)
            inbuf = ctypes.create_string_buffer(data)
            outbuf = ctypes.create_string_buffer(n)
            lib.sm4_ecb(ctypes.create_string_buffer(self._key), inbuf, outbuf, n, 0)
            return outbuf.raw
        return self._bulk(data, self._rkey[::-1])

    @classmethod
    def _make_t_tables(cls):
        S = cls._S_BOX
        def rol(x, n):
            return (x << n) & 0xFFFFFFFF | (x >> (32 - n))
        def L(y):
            return y ^ rol(y, 2) ^ rol(y, 10) ^ rol(y, 18) ^ rol(y, 24)
        T0 = [0] * 256; T1 = [0] * 256; T2 = [0] * 256; T3 = [0] * 256
        for i in range(256):
            s = S[i]
            T0[i] = L(s << 24)
            T1[i] = L(s << 16)
            T2[i] = L(s << 8)
            T3[i] = L(s)
        return (T0, T1, T2, T3)

    def _bulk(self, data: bytes, rk) -> bytes:
        n = len(data)
        out = bytearray(n)
        T0, T1, T2, T3 = self._T_TABLES
        unpack_from = struct.unpack_from
        pack_into = struct.pack_into
        idx = 0
        while idx < n:
            X0, X1, X2, X3 = unpack_from('>IIII', data, idx)
            for i in range(0, 32, 4):
                t = X1 ^ X2 ^ X3 ^ rk[i]
                X0 ^= T0[t >> 24] ^ T1[t >> 16 & 255] ^ T2[t >> 8 & 255] ^ T3[t & 255]
                t = X2 ^ X3 ^ X0 ^ rk[i + 1]
                X1 ^= T0[t >> 24] ^ T1[t >> 16 & 255] ^ T2[t >> 8 & 255] ^ T3[t & 255]
                t = X3 ^ X0 ^ X1 ^ rk[i + 2]
                X2 ^= T0[t >> 24] ^ T1[t >> 16 & 255] ^ T2[t >> 8 & 255] ^ T3[t & 255]
                t = X0 ^ X1 ^ X2 ^ rk[i + 3]
                X3 ^= T0[t >> 24] ^ T1[t >> 16 & 255] ^ T2[t >> 8 & 255] ^ T3[t & 255]
            pack_into('>IIII', out, idx, X3, X2, X1, X0)
            idx += 16
        return bytes(out)

_FAST_SM4_LIB = None
_FAST_SM4_TRIED = False

def _sm4_c_source() -> str:
    sbox = SM4._S_BOX
    fk = SM4._FK
    ck = SM4._CK
    L = []
    L.append('// auto-generated fast SM4 (GB/T 32907-2016) from tool.py constants')
    L.append('#include <stdint.h>')
    L.append('#include <stddef.h>')
    L.append('')
    L.append('static const uint8_t SBOX[256] = { ' + ', '.join(str(x) for x in sbox) + ' };')
    L.append('static const uint32_t FK[4] = { ' + ', '.join(hex(x) for x in fk) + ' };')
    L.append('static const uint32_t CK[32] = { ' + ', '.join(hex(x) for x in ck) + ' };')
    L.append('')
    L.append('static inline uint32_t rotl(uint32_t x, int n){ return (x << n) | (x >> (32 - n)); }')
    L.append('static inline uint32_t load_be(const uint8_t* p){ return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|(uint32_t)p[3]; }')
    L.append('static inline void store_be(uint8_t* p, uint32_t v){ p[0]=(uint8_t)(v>>24); p[1]=(uint8_t)(v>>16); p[2]=(uint8_t)(v>>8); p[3]=(uint8_t)v; }')
    L.append('static inline uint32_t sb(uint32_t x){ return ((uint32_t)SBOX[(x>>24)&0xff]<<24)|((uint32_t)SBOX[(x>>16)&0xff]<<16)|((uint32_t)SBOX[(x>>8)&0xff]<<8)|(uint32_t)SBOX[x&0xff]; }')
    L.append('static inline uint32_t t0(uint32_t x){ x = sb(x); return x ^ rotl(x,2) ^ rotl(x,10) ^ rotl(x,18) ^ rotl(x,24); }')
    L.append('static inline uint32_t t1(uint32_t x){ x = sb(x); return x ^ rotl(x,13) ^ rotl(x,23); }')
    L.append('')
    L.append('static void expand(const uint8_t* key, uint32_t rk[32]){')
    L.append('    uint32_t k0 = load_be(key) ^ FK[0];')
    L.append('    uint32_t k1 = load_be(key+4) ^ FK[1];')
    L.append('    uint32_t k2 = load_be(key+8) ^ FK[2];')
    L.append('    uint32_t k3 = load_be(key+12) ^ FK[3];')
    L.append('    for (int i = 0; i < 32; i++){')
    L.append('        k0 ^= t1(k1 ^ k2 ^ k3 ^ CK[i]); rk[i] = k0;')
    L.append('        k1 ^= t1(k2 ^ k3 ^ k0 ^ CK[++i]); rk[i] = k1;')
    L.append('        k2 ^= t1(k3 ^ k0 ^ k1 ^ CK[++i]); rk[i] = k2;')
    L.append('        k3 ^= t1(k0 ^ k1 ^ k2 ^ CK[++i]); rk[i] = k3;')
    L.append('    }')
    L.append('}')
    L.append('')
    L.append('static void crypt_block(const uint8_t* in, uint8_t* out, const uint32_t* rk){')
    L.append('    uint32_t x0 = load_be(in);')
    L.append('    uint32_t x1 = load_be(in+4);')
    L.append('    uint32_t x2 = load_be(in+8);')
    L.append('    uint32_t x3 = load_be(in+12);')
    L.append('    for (int i = 0; i < 32; i += 4){')
    L.append('        x0 ^= t0(x1 ^ x2 ^ x3 ^ rk[i]);')
    L.append('        x1 ^= t0(x2 ^ x3 ^ x0 ^ rk[i+1]);')
    L.append('        x2 ^= t0(x3 ^ x0 ^ x1 ^ rk[i+2]);')
    L.append('        x3 ^= t0(x0 ^ x1 ^ x2 ^ rk[i+3]);')
    L.append('    }')
    L.append('    store_be(out, x3); store_be(out+4, x2); store_be(out+8, x1); store_be(out+12, x0);')
    L.append('}')
    L.append('')
    L.append('// ECB transform. encrypt: 1, decrypt: 0. len must be multiple of 16.')
    L.append('void sm4_ecb(const uint8_t* key, const uint8_t* in, uint8_t* out, size_t len, int encrypt){')
    L.append('    uint32_t rk[32];')
    L.append('    expand(key, rk);')
    L.append('    if (!encrypt){')
    L.append('        for (int i = 0; i < 16; i++){ uint32_t tmp = rk[i]; rk[i] = rk[31-i]; rk[31-i] = tmp; }')
    L.append('    }')
    L.append('    for (size_t off = 0; off < len; off += 16){')
    L.append('        crypt_block(in + off, out + off, rk);')
    L.append('    }')
    L.append('}')
    return '\n'.join(L)

def _load_fast_sm4():
    global _FAST_SM4_LIB, _FAST_SM4_TRIED
    if _FAST_SM4_TRIED:
        return _FAST_SM4_LIB
    _FAST_SM4_TRIED = True
    try:
        tool_dir = Path(__file__).resolve().parent
        src_path = tool_dir / 'sm4_fast.c'
        so_path = tool_dir / 'sm4_fast.so'
        c_src = _sm4_c_source()
        if not src_path.exists():
            src_path.write_text(c_src)
        if src_path.read_text() != c_src:
            src_path.write_text(c_src)
        recompile = (not so_path.exists()) or (so_path.stat().st_mtime < src_path.stat().st_mtime)
        if recompile:
            for cc in ('gcc', 'cc', 'clang'):
                try:
                    r = subprocess.run([cc, '-O2', '-shared', '-fPIC', str(src_path), '-o', str(so_path)],
                                       capture_output=True, timeout=120)
                    if r.returncode == 0 and so_path.exists():
                        break
                except Exception:
                    continue
        if not so_path.exists():
            return None
        lib = ctypes.CDLL(str(so_path))
        lib.sm4_ecb.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
        lib.sm4_ecb.restype = None
        _FAST_SM4_LIB = lib
        return lib
    except Exception:
        return None

class Misc:
    @staticmethod
    def pad_to_n(data: bytes, n: int) -> bytes:
        assert n > 0
        padding = n - len(data) % n
        if padding == n:
            return data
        else:
            return data + b'\x00' * padding
    @staticmethod
    def align_up(x: int, n: int) -> int:
        return (x + n - 1) // n * n

class Reader:
    def __init__(self, buffer, cursor=0):
        self._buffer = buffer
        self._cursor = cursor
    def u1(self, move_cursor=True) -> int:
        try:
            return self.unpack('B', move_cursor=move_cursor)[0]
        except:
            return 0
    def u4(self, move_cursor=True) -> int:
        try:
            return self.unpack('<I', move_cursor=move_cursor)[0]
        except:
            return 0
    def u8(self, move_cursor=True) -> int:
        try:
            return self.unpack('<Q', move_cursor=move_cursor)[0]
        except:
            return 0
    def i1(self, move_cursor=True) -> int:
        try:
            return self.unpack('b', move_cursor=move_cursor)[0]
        except:
            return 0
    def i4(self, move_cursor=True) -> int:
        try:
            return self.unpack('<i', move_cursor=move_cursor)[0]
        except:
            return 0
    def i8(self, move_cursor=True) -> int:
        try:
            return self.unpack('<q', move_cursor=move_cursor)[0]
        except:
            return 0
    def s(self, n: int, move_cursor=True) -> bytes:
        try:
            return self.unpack(f'{n}s', move_cursor=move_cursor)[0]
        except:
            return b''
    def unpack(self, f: str, offset=0, move_cursor=True):
        try:
            x = struct.unpack_from(f, self._buffer, self._cursor + offset)
            if move_cursor:
                self._cursor += struct.calcsize(f)
            return x
        except:
            return (0,) * struct.calcsize(f)
    def string(self, move_cursor=True) -> str:
        try:
            length = self.i4(move_cursor=move_cursor)
            if length <= 0 or length > 10000:
                return ""
            offset = 0 if move_cursor else 4
            data = self.unpack(f'{length}s', offset=offset, move_cursor=move_cursor)[0]
            if isinstance(data, bytes):
                return data.rstrip(b'\x00').decode('utf-8', errors='ignore')
            return ""
        except:
            return ""

class PakInfo:
    def __init__(self, buffer, keystream: List[int]):
        try:
            def decrypt_index_encrypted(x: int) -> int:
                return (x ^ keystream[3]) & 255
            def decrypt_magic(x: int) -> int:
                return x ^ keystream[2]
            def decrypt_index_hash(x: bytes) -> bytes:
                key = struct.pack('<5I', *keystream[4:][:5])
                if len(x) == len(key):
                    return bytes((a ^ b for a, b in zip(x, key)))
                return x
            def decrypt_index_size(x: int) -> int:
                return x ^ (keystream[10] << 32 | keystream[11])
            def decrypt_index_offset(x: int) -> int:
                return x ^ (keystream[0] << 32 | keystream[1])
            reader = Reader(buffer[-PakInfo._mem_size((-1)):])
            self.index_encrypted = decrypt_index_encrypted(reader.u1()) == 1
            self.magic = decrypt_magic(reader.u4())
            self.version = reader.u4()
            self.index_hash = decrypt_index_hash(reader.s(20)) if self.version >= 6 else bytes()
            self.index_size = decrypt_index_size(reader.u8())
            self.index_offset = decrypt_index_offset(reader.u8())
            if self.version <= 3:
                self.index_encrypted = False
        except:
            self.index_encrypted = False
            self.magic = 0
            self.version = 12
            self.index_hash = bytes(20)
            self.index_size = 0
            self.index_offset = 0
    
    @staticmethod
    def _mem_size(_: int) -> int:
        return 45

class TencentPakInfo(PakInfo):
    def __init__(self, buffer, keystream: List[int]):
        try:
            def decrypt_unk(x: bytes) -> bytes:
                key = struct.pack('<8I', *keystream[7:][:8])
                if len(x) == len(key):
                    return bytes((a ^ b for a, b in zip(x, key)))
                return x
            def decrypt_stem_hash(x: int) -> int:
                return x ^ keystream[8]
            def decrypt_unk_hash(x: int) -> int:
                return x ^ keystream[9]
            super().__init__(buffer, keystream)
            reader = Reader(buffer[-TencentPakInfo._mem_size(self.version):])
            self.unk1 = decrypt_unk(reader.s(32)) if self.version >= 7 else bytes()
            self.packed_key = reader.s(256) if self.version >= 8 else bytes()
            self.packed_iv = reader.s(256) if self.version >= 8 else bytes()
            self.packed_index_hash = reader.s(256) if self.version >= 8 else bytes()
            self.stem_hash = decrypt_stem_hash(reader.u4()) if self.version >= 9 else 0
            self.unk2 = decrypt_unk_hash(reader.u4()) if self.version >= 9 else 0
            self.content_org_hash = reader.s(20) if self.version >= 12 else bytes()
        except:
            self.unk1 = bytes(32)
            self.packed_key = bytes(256)
            self.packed_iv = bytes(256)
            self.packed_index_hash = bytes(256)
            self.stem_hash = 0
            self.unk2 = 0
            self.content_org_hash = bytes(20)
    
    @staticmethod
    def _mem_size(version: int) -> int:
        size_for_7 = 32 if version >= 7 else 0
        size_for_8 = 768 if version >= 8 else 0
        size_for_9 = 8 if version >= 9 else 0
        size_for_12 = 20 if version >= 12 else 0
        return PakInfo._mem_size(version) + size_for_7 + size_for_8 + size_for_9 + size_for_12

class PakCompressedBlock:
    def __init__(self, reader: Reader):
        try:
            self.start = reader.u8()
            self.end = reader.u8()
        except:
            self.start = 0
            self.end = 0

@dataclass
class TencentPakEntry:
    def __init__(self, reader: Reader, version: int):
        try:
            self.content_hash = reader.s(20)
            if version <= 1:
                _ = reader.u8()
            self.offset = reader.u8()
            self.uncompressed_size = reader.u8()
            self.compression_method = reader.u4() & CM_MASK
            self.size = reader.u8()
            self.unk1 = reader.u1() if version >= 5 else 0
            self.unk2 = reader.s(20) if version >= 5 else bytes()
            if self.compression_method != 0 and version >= 3:
                num_blocks = reader.u4()
                self.compressed_blocks = []
                for _ in range(num_blocks):
                    try:
                        self.compressed_blocks.append(PakCompressedBlock(reader))
                    except:
                        self.compressed_blocks.append(PakCompressedBlock(Reader(b'')))
            else:
                self.compressed_blocks = []
            self.compression_block_size = reader.u4() if version >= 4 else 0
            self.encrypted = reader.u1() == 1 if version >= 4 else False
            self.encryption_method = reader.u4() if version >= 12 else 0
            self.index_new_sep = reader.u4() if version >= 12 else 0
        except:
            self.content_hash = bytes(20)
            self.offset = 0
            self.uncompressed_size = 0
            self.compression_method = 0
            self.size = 0
            self.unk1 = 0
            self.unk2 = bytes(20)
            self.compressed_blocks = []
            self.compression_block_size = 0
            self.encrypted = False
            self.encryption_method = 0
            self.index_new_sep = 0

class PakCrypto:
    class _LCG:
        def __init__(self, seed: int):
            self.state = seed
        def next(self) -> int:
            MASK_32 = 4294967295
            def wrap(x: int) -> int:
                return x & MASK_32
            x1 = wrap(1103515245 * self.state)
            self.state = wrap(x1 + 12345)
            return (self.state >> 16 & MASK_32) % 32767 if self.state else 0
    
    @staticmethod
    def zuc_keystream() -> List[int]:
        try:
            zuc = gmalg.ZUC(ZUC_KEY, ZUC_IV)
            return [struct.unpack('>I', zuc.generate())[0] for _ in range(16)]
        except:
            return [0] * 16
    
    @staticmethod
    def _xorxor(buffer, x) -> bytes:
        try:
            return bytes((buffer[i] ^ x[i % len(x)] for i in range(len(buffer))))
        except:
            return buffer
    
    @staticmethod
    def _hashhash(buffer, n: int) -> bytes:
        try:
            result = bytes()
            for i in range(math.ceil(n / SHA1.digest_size)):
                result += SHA1.new(buffer).digest()
            return result[:n] if len(result) >= n else result + b'\x00' * (n - len(result))
        except:
            return b'\x00' * n
    
    @staticmethod
    def _meowmeow(buffer) -> bytes:
        try:
            def unpad(x):
                skip = 1 + next((i for i in range(len(x)) if x[i]!= 0))
                return x[skip:]
            if len(buffer) < 43:
                return bytes()
            x1 = buffer[1:][:SHA1.digest_size]
            x2 = buffer[SHA1.digest_size + 1:]
            x1 = PakCrypto._xorxor(x1, PakCrypto._hashhash(x2, len(x1)))
            x2 = PakCrypto._xorxor(x2, PakCrypto._hashhash(x1, len(x2)))
            part1, m = (x2[:SHA1.digest_size], x2[SHA1.digest_size:])
            if part1 != SHA1.new(b'\x00' * SHA1.digest_size).digest():
                return bytes()
            return unpad(m)
        except:
            return bytes()
    
    @staticmethod
    def rsa_extract(signature: bytes, modulus: bytes) -> bytes:
        try:
            c = int.from_bytes(signature, 'little')
            n = int.from_bytes(modulus, 'little')
            e = 65537
            m = pow(c, e, n).to_bytes(256, 'little').rstrip(b'\x00')
            return PakCrypto._meowmeow(Misc.pad_to_n(m, 4))
        except:
            return bytes(32)
    
    @staticmethod
    def _decrypt_simple1(ciphertext) -> bytes:
        try:
            return bytes((x ^ SIMPLE1_DECRYPT_KEY for x in ciphertext))
        except:
            return ciphertext
    
    @staticmethod
    def _decrypt_simple2(ciphertext) -> bytes:
        try:
            class RollingKey:
                def __init__(self, initial_value: int):
                    self._value = initial_value
                def update(self, x: int) -> int:
                    self._value ^= x
                    return self._value
            assert len(ciphertext) % SIMPLE2_BLOCK_SIZE == 0
            initial_key, = struct.unpack('<I', SIMPLE2_DECRYPT_KEY)
            rolling_key = RollingKey(initial_key)
            plaintext = (struct.pack('<I', rolling_key.update(x)) for x in struct.unpack(f'<{len(ciphertext) // 4}I', ciphertext))
            return bytes(it.chain.from_iterable(plaintext))
        except:
            return ciphertext
    
    @staticmethod
    @lru_cache(maxsize=1)
    def _derive_sm4_key(file_path: PurePath, encryption_method: int) -> bytes:
        try:
            part1 = file_path.stem.lower()
            if encryption_method == EM_SM4_2:
                secret = SM4_SECRET_2
            elif encryption_method == EM_SM4_4:
                secret = SM4_SECRET_4
            else:
                index = (encryption_method - EM_SM4_NEW_BASE) % len(SM4_SECRET_NEW)
                secret = f'{SM4_SECRET_NEW[index]}{encryption_method}'
            return SHA1.new(str(part1 + secret).encode()).digest()[:SM4.key_length()]
        except:
            return bytes(16)
    
    @staticmethod
    @lru_cache(maxsize=1)
    def _sm4_context_for_key(key: bytes) -> SM4:
        try:
            return SM4(key)
        except:
            return SM4(bytes(16))
    
    @staticmethod
    def _decrypt_sm4(ciphertext, file_path: PurePath, encryption_method: int) -> bytes:
        try:
            assert len(ciphertext) % SM4.block_length() == 0
            key = PakCrypto._derive_sm4_key(file_path, encryption_method)
            sm4 = PakCrypto._sm4_context_for_key(key)
            return sm4.decrypt_bulk(ciphertext)
        except:
            return ciphertext
    
    @staticmethod
    def decrypt_index(ciphertext, pak_info: TencentPakInfo) -> bytes:
        try:
            if pak_info.version > 7:
                key = PakCrypto.rsa_extract(pak_info.packed_key, RSA_MOD_1)
                iv = PakCrypto.rsa_extract(pak_info.packed_iv, RSA_MOD_1)
                aes = AES.new(key, MODE_CBC, iv[:16])
                return unpad(aes.decrypt(ciphertext), AES.block_size)
            else:
                return PakCrypto._decrypt_simple1(ciphertext)
        except:
            return ciphertext
    
    @staticmethod
    def _is_simple1_method(encryption_method: int) -> bool:
        return encryption_method == EM_SIMPLE1
    
    @staticmethod
    def _is_simple2_method(encryption_method: int) -> bool:
        return encryption_method == EM_SIMPLE2 or encryption_method == 17
    
    @staticmethod
    def _is_sm4_method(encryption_method: int) -> bool:
        return encryption_method == EM_SM4_2 or encryption_method == EM_SM4_4 or encryption_method & EM_SM4_NEW_MASK != 0
    
    @staticmethod
    def align_encrypted_content_size(n: int, encryption_method: int) -> int:
        if PakCrypto._is_simple2_method(encryption_method):
            return Misc.align_up(n, SIMPLE2_BLOCK_SIZE)
        elif PakCrypto._is_sm4_method(encryption_method):
            return Misc.align_up(n, SM4.block_length())
        else:
            return n
    
    @staticmethod
    def decrypt_block(ciphertext, file: PurePath, encryption_method: int) -> bytes:
        try:
            if PakCrypto._is_simple1_method(encryption_method):
                return PakCrypto._decrypt_simple1(ciphertext)
            elif PakCrypto._is_simple2_method(encryption_method):
                return PakCrypto._decrypt_simple2(ciphertext)
            elif PakCrypto._is_sm4_method(encryption_method):
                return PakCrypto._decrypt_sm4(ciphertext, file, encryption_method)
            else:
                return ciphertext
        except:
            return ciphertext
    
    @staticmethod
    @lru_cache(maxsize=33)
    def generate_block_indices(n: int, encryption_method: int) -> List[int]:
        try:
            if not PakCrypto._is_sm4_method(encryption_method) or n <= 0:
                return list(range(n))
            permutation = []
            lcg = PakCrypto._LCG(n)
            seen = set()
            while len(permutation) < n:
                x = lcg.next() % n
                if x not in seen:
                    seen.add(x)
                    permutation.append(x)
            inverse = [0] * n
            for i, x in enumerate(permutation):
                inverse[x] = i
            return inverse
        except:
            return list(range(n))

class PakCompression:
    @staticmethod
    @lru_cache(maxsize=33)
    def _zstd_decompressor(dict: ZstdCompressionDict) -> ZstdDecompressor:
        try:
            return ZstdDecompressor(dict)
        except:
            return ZstdDecompressor()
    
    @staticmethod
    def zstd_dictionary(dict_data) -> ZstdCompressionDict:
        try:
            return ZstdCompressionDict(dict_data, DICT_TYPE_AUTO)
        except:
            return None
    
    @staticmethod
    def decompress_block(block, dict: Optional[ZstdCompressionDict], compression_method: int) -> bytes:
        try:
            if compression_method == CM_ZLIB:
                try:
                    return zlib.decompress(block)
                except zlib.error:
                    return block
            elif compression_method == CM_ZSTD or compression_method == CM_ZSTD_DICT:
                d = dict if compression_method == CM_ZSTD_DICT else None
                return PakCompression._zstd_decompressor(d).decompress(block)
            else:
                return block
        except:
            return block

# ==================== MAIN PAK CLASS ====================


def _unpack_cancel_requested() -> bool:
    """Non-blocking Enter-based cancel check; safe fallback for Termux."""
    try:
        import select
        if not hasattr(sys.stdin, 'fileno'):
            return False
        ready, _, _ = select.select([sys.stdin], [], [], 0)
        if not ready:
            return False
        raw = sys.stdin.readline().strip().lower()
        return raw in ('0', 'c', 'cancel')
    except Exception:
        return False


class TencentPakFile:
    def __init__(self, file_path: PurePath, is_od=False):
        try:
            self._file_path = file_path
            with open(file_path, 'rb') as file:
                self._file_content = memoryview(file.read())
            self._is_od = is_od
            self._mount_point = PurePath()
            self._is_zstd_with_dict = 'zsdic' in str(self._file_path).lower()
            self._zstd_dict = None
            self._zstd_dict_entry = None
            self._files = []
            self._index = {}
            self._pak_info = TencentPakInfo(self._file_content, PakCrypto.zuc_keystream())
            self._verify_stem_hash()
            self._tencent_load_index()
        except Exception as e:
            console.print(f"[red]Error loading PAK: {e}[/red]")
            self._file_content = memoryview(b'')
            self._files = []
            self._index = {}
            self._mount_point = PurePath()
            self._pak_info = TencentPakInfo(b'', [0]*16)
    
    def _get_method_str(self, method_int, is_encryption):
        try:
            if is_encryption:
                if PakCrypto._is_simple1_method(method_int): return "SIMPLE1"
                if PakCrypto._is_simple2_method(method_int): return "SIMPLE2"
                if PakCrypto._is_sm4_method(method_int): return f"SM4 (Type {method_int})"
                return "NONE" if method_int == 0 else "UNKNOWN"
            else:
                if method_int == CM_NONE: return "NONE"
                if method_int == CM_ZLIB: return "ZLIB"
                if method_int == CM_ZSTD: return "ZSTD"
                if method_int == CM_ZSTD_DICT: return "ZSTD_DICT"
                return "UNKNOWN"
        except:
            return "UNKNOWN"
    
    def _verify_stem_hash(self) -> None:
        try:
            if not self._is_od and self._pak_info.version >= 9:
                try:
                    assert self._pak_info.stem_hash == zlib.crc32(self._file_path.stem.encode('utf-32le'))
                except AssertionError:
                    console.print(f"Warning: pak filename differs from original stem")
        except:
            pass
    
    def _tencent_load_index(self) -> None:
        try:
            if hasattr(self, '_pak_info') and hasattr(self, '_file_content'):
                index_data = self._file_content[self._pak_info.index_offset:][:self._pak_info.index_size]
                if self._pak_info.index_encrypted:
                    index_data = PakCrypto.decrypt_index(index_data, self._pak_info)
                self._load_index(index_data)
        except Exception as e:
            console.print(f"[#7C4DFF]Index loading error: {e}, continuing...[/]")
    
    def _peek_content(self, offset: int, size: int, encryption_method: int) -> memoryview:
        try:
            size = PakCrypto.align_encrypted_content_size(size, encryption_method)
            return self._file_content[offset:][:size]
        except:
            return memoryview(b'')
    
    def _peek_block_content(self, block: PakCompressedBlock, encryption_method: int) -> memoryview:
        try:
            size = PakCrypto.align_encrypted_content_size(block.end - block.start, encryption_method)
            return self._file_content[block.start:][:size]
        except:
            return memoryview(b'')
    
    def _load_index(self, index_data) -> None:
        try:
            reader = Reader(index_data)
            mount_str = reader.string()
            self._mount_point = PurePath(mount_str) if mount_str else PurePath()
            num_files = reader.u4()
            
            self._files = []
            for i in range(min(num_files, 100000)):
                try:
                    self._files.append(TencentPakEntry(reader, self._pak_info.version))
                except:
                    self._files.append(TencentPakEntry(Reader(b''), self._pak_info.version))
            
            num_dirs = reader.u8()
            for d in range(min(num_dirs, 10000)):
                try:
                    dir_path_str = reader.string()
                    dir_path = PurePath(dir_path_str) if dir_path_str else PurePath("unknown")
                    e = {}
                    dir_entries = reader.u8()
                    for __ in range(min(dir_entries, 10000)):
                        try:
                            name = reader.string()
                            idx = ~reader.i4()
                            if 0 <= idx < len(self._files):
                                e[name] = self._files[idx]
                            else:
                                console.print(f"[#7C4DFF]Skipping invalid entry index {idx} in {dir_path}[/]")
                        except:
                            continue
                    if e:
                        self._index.update({dir_path: e})
                except:
                    continue
        except Exception as e:
            console.print(f"[#7C4DFF]Index parse error: {e}, continuing with partial data...[/]")
    
    def _write_to_disk(self, file_path: Path, entry: TencentPakEntry) -> None:
        try:
            enc_str = self._get_method_str(entry.encryption_method, True)
            comp_str = self._get_method_str(entry.compression_method, False)
            _ui_unpack_log(file_path.name, enc_str, comp_str, 'Extracting') if _UNPACK_UI_ACTIVE else console.print(_ui_panel('Extracting', Text(f'Extracting: {file_path.name}', style='bold #00CFFF'), '#00CFFF', f'Encryption: {enc_str}  |  Compression: {comp_str}'))
            
            safe_path = sanitize_path(file_path)
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            
            if entry.compression_method == CM_NONE:
                data = self._peek_content(entry.offset, entry.size, entry.encryption_method)
                if entry.encrypted:
                    data = PakCrypto.decrypt_block(data, file_path, entry.encryption_method)
                with open(safe_path, 'wb') as f:
                    f.write(data[:entry.uncompressed_size])
            else:
                with open(safe_path, 'wb') as f:
                    for x in PakCrypto.generate_block_indices(len(entry.compressed_blocks), entry.encryption_method):
                        data = self._peek_block_content(entry.compressed_blocks[x], entry.encryption_method)
                        if entry.encrypted:
                            data = PakCrypto.decrypt_block(data, file_path, entry.encryption_method)
                        data = PakCompression.decompress_block(data, self._zstd_dict, entry.compression_method)
                        f.write(data)
        except Exception as e:
            console.print(f"[red]✗ Failed to write {file_path.name}: {e}[/red]")
    
    def dump(self, out_path: Path) -> bool:
        """Extract PAK contents with the reference animated RGB HUD.

        The extraction algorithm and file handling remain unchanged; only the
        terminal presentation is managed by the live UI below.
        """
        global _UNPACK_LOGS, _UNPACK_UI_ACTIVE
        cancelled = False
        try:
            # Resolve the real PAK root from the index instead of blindly
            # concatenating Mount Point + Directory. Some PAKs store directory
            # names already prefixed by the mount point, while others store
            # paths relative to it. Concatenating both creates paths such as
            # ShadowTrackerExtra/ShadowTrackerExtra/... and is the reason a
            # separate Plane can appear necessary.
            # Always create one folder named after the PAK file itself, then
            # reproduce the PAK index hierarchy inside it.  The mount point is
            # part of that hierarchy (for example: Z/ShadowTrackerExtra/...).
            # This keeps different PAKs separated and avoids using the mount
            # point itself as the extraction root.
            pak_root_name = self._file_path.stem
            final_path = sanitize_path(out_path / pak_root_name)
            final_path.mkdir(parents=True, exist_ok=True)

            mount_clean = clean_pak_path(str(self._mount_point))
            mount_norm = mount_clean.replace('\\', '/').strip('/')

            def _real_unpack_dir(dir_path):
                raw_dir = clean_pak_path(str(dir_path)).strip('/')
                mount_lower = mount_norm.lower()
                raw_lower = raw_dir.lower()

                # If the index directory already contains the mount point,
                # preserve the complete logical PAK path exactly once.
                if mount_norm and raw_lower == mount_lower:
                    return sanitize_path(final_path / mount_norm)
                if mount_norm and raw_lower.startswith(mount_lower + '/'):
                    return sanitize_path(final_path / raw_dir)

                # Most PAKs store directory keys relative to the mount point.
                # Reconstruct the real logical path as mount + directory.
                if mount_norm and raw_dir:
                    return sanitize_path(final_path / mount_norm / raw_dir)
                if mount_norm:
                    return sanitize_path(final_path / mount_norm)
                if raw_dir:
                    return sanitize_path(final_path / raw_dir)
                return final_path

            if not self._index:
                console.print('[#00CFFF]Index empty, trying direct extraction...[/]')
                for i, entry in enumerate(self._files[:10000]):
                    if _unpack_cancel_requested():
                        return False
                    try:
                        self._write_to_disk(final_path / f'file_{i:08d}.bin', entry)
                    except Exception:
                        continue
                return True

            total_files = sum(len(d) for d in self._index.values())
            if total_files == 0:
                console.print('[#00CFFF]No files to extract![/]')
                return True

            _UNPACK_LOGS = []
            _UNPACK_UI_ACTIVE = True
            done = 0
            limit = min(total_files, 100000)

            with Live(
                _unpack_hud_renderable(self._file_path.name, done, limit),
                console=console,
                refresh_per_second=20,
                transient=False,
                screen=False,
            ) as unpack_live:
                for dir_path, dir_content in self._index.items():
                    if _unpack_cancel_requested():
                        cancelled = True
                        break

                    safe_dir = _real_unpack_dir(dir_path)
                    try:
                        safe_dir.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        safe_dir = final_path

                    for file_name, entry in dir_content.items():
                        if _unpack_cancel_requested():
                            cancelled = True
                            break
                        try:
                            safe_name = Path(file_name).name
                            if not safe_name:
                                safe_name = f'file_{hash(file_name) & 0xFFFFFFFF:08x}.bin'
                            safe_name = sanitize_path(safe_name).name
                            if not safe_name:
                                safe_name = 'unknown.bin'
                            self._write_to_disk(safe_dir / safe_name, entry)
                        except Exception:
                            pass

                        done += 1
                        unpack_live.update(
                            _unpack_hud_renderable(self._file_path.name, done, limit),
                            refresh=True,
                        )

                    if cancelled:
                        break

                if not cancelled:
                    unpack_live.update(
                        _unpack_hud_renderable(self._file_path.name, done, limit, final=True, output_path=final_path),
                        refresh=True,
                    )
                    time.sleep(0.35)

            _UNPACK_UI_ACTIVE = False

            if cancelled:
                console.print(_ui_panel(
                    'UNPACK CANCELLED',
                    Text('Operation stopped by user. Returning to main menu...', style='bold #00CFFF'),
                    '#00CFFF'
                ))
                time.sleep(0.35)
                return False

            return True

        except Exception as e:
            _UNPACK_UI_ACTIVE = False
            console.print(f'[bold #00CFFF]Dump error: {escape(str(e))}[/]')
            return False

# ==================== CREATE VIP FUNCTIONS ====================

VIP_TARGET_ROOT = PurePath('Content/Lua/GameLua/Mod/BRMod/Gameplay/Core')

def _vip_target_root_from_pak(pak_file: Path) -> PurePath:
    """Resolve the selected PAK's real Content root without a fixed package name.

    We use the already-parsed PAK index first (``_mount_point`` + ``_index``),
    then fall back to a raw index parse.  Directory names in Tencent PAK files
    are not guaranteed to use the same prefix/layout, so the package name is
    never hard-coded here.
    """
    def _parts(value):
        return [x for x in str(value or '').replace('\\', '/').split('/')
                if x and x != '.']

    def _content_root(parts):
        for i, part in enumerate(parts):
            if part.lower() == 'content':
                return PurePath('/'.join(parts[:i + 1]))
        return None

    # The TencentPakFile instance has already parsed these structures when
    # the PAK was opened. This is more reliable than reparsing the encrypted
    # index a second time.
    mount_parts = _parts(getattr(pak_file, '_mount_point', ''))
    index = getattr(pak_file, '_index', {}) or {}

    # 1) Content may be part of the mount point itself.
    root = _content_root(mount_parts)
    if root is not None:
        return root / VIP_TARGET_RELATIVE

    # 2) Look at the directory keys exactly as the PAK parser stored them.
    for raw_dir in index.keys():
        dir_parts = _parts(raw_dir)

        root = _content_root(dir_parts)
        if root is not None:
            return root / VIP_TARGET_RELATIVE

        # Some PAKs keep the mount point and directory portion separately.
        if mount_parts and dir_parts:
            root = _content_root(mount_parts + dir_parts)
            if root is not None:
                return root / VIP_TARGET_RELATIVE

    # 3) Some indexes expose Content as the first directory below the mount.
    if mount_parts:
        for raw_dir in index.keys():
            dir_parts = _parts(raw_dir)
            if dir_parts and dir_parts[0].lower() == 'content':
                return PurePath('/'.join(mount_parts + dir_parts[:1])) / VIP_TARGET_RELATIVE

    # 4) Last resort: parse the raw index. Keep this only as a fallback.
    mp, dirs = _get_all_dirs_and_mp(pak_file)
    raw_mount = _parts(mp) or mount_parts
    root = _content_root(raw_mount)
    if root is not None:
        return root / VIP_TARGET_RELATIVE

    for raw_dir in dirs.keys():
        dir_parts = _parts(raw_dir)
        root = _content_root(dir_parts)
        if root is not None:
            return root / VIP_TARGET_RELATIVE
        if raw_mount and dir_parts:
            root = _content_root(raw_mount + dir_parts)
            if root is not None:
                return root / VIP_TARGET_RELATIVE

    raise ValueError(
        'Content root could not be resolved from this PAK index. '
        'The PAK may use an index layout that does not expose directory paths.'
    )


def _vip_prepare_edit_files(edit_dir: Path, method_info: dict):
    files = sorted(p for p in edit_dir.rglob('*') if p.is_file())
    if not files:
        raise ValueError(f'No files found in EDIT folder: {edit_dir}')
    max_files = int(method_info.get('max_files', 1))
    if len(files) > max_files:
        raise ValueError(f'EDIT contains {len(files)} files; maximum for this method is {max_files}.')
    if method_info.get('rename_source', True):
        filename = method_info.get('filename')
        if len(files) != 1 or not filename:
            raise ValueError('EDIT must contain exactly one file.')
        src = files[0]
        dst = edit_dir / filename
        if src.resolve() != dst.resolve():
            if dst.exists():
                dst.unlink()
            src.rename(dst)
        return [dst]
    return files


def _vip_clean_relative_path(path: Path) -> str:
    return str(path).replace('\\', '/').lstrip('/')


def _vip_template_for_path(pak_file, all_dirs, target_path):
    """Find metadata from an existing PAK entry, preferring the exact path/name."""
    target = _vip_clean_relative_path(Path(target_path)).lower().rstrip('/')
    target_dir, _, target_name = target.rpartition('/')
    target_dir = (target_dir + '/') if target_dir else ''

    # Exact path + filename match first.
    for dp, files in all_dirs.items():
        dp_norm = _vip_clean_relative_path(dp).lower()
        if dp_norm and not dp_norm.endswith('/'):
            dp_norm += '/'
        if dp_norm == target_dir:
            for name, entry in files.items():
                if name.lower() == target_name:
                    return entry

    # Then prefer a file with the same extension.
    ext = Path(target_name).suffix.lower()
    if ext:
        for _, files in all_dirs.items():
            for name, entry in files.items():
                if Path(name).suffix.lower() == ext:
                    return entry

    # Last resort: any existing entry gives us valid entry metadata.
    for _, files in all_dirs.items():
        for _, entry in files.items():
            return entry
    return pak_file._files[0] if pak_file._files else None


def create_vip_zeroed_pak(pak_file: Path, edit_root: Path, output_path: Path, target_root: PurePath, data_path: Path) -> bool:
    """Build a compact PAK containing only the files and folder structure supplied in EDIT."""
    import copy as _cp

    try:
        pak = TencentPakFile(pak_file)
        version = pak._pak_info.version
        if version < 12:
            raise ValueError(f'Unsupported pak version: {version} (need >= 12)')

        # Preserve the user's folder structure exactly as it appears under EDIT.
        edit_files = sorted(p for p in edit_root.rglob('*') if p.is_file())
        if not edit_files:
            raise ValueError(f'Put files/folders inside: {edit_root}')

        mp_str, original_dirs = _get_all_dirs_and_mp(pak)
        if not original_dirs or not pak._files:
            raise ValueError('PAK index is empty or could not be parsed.')

        out_buf = bytearray()
        new_files = []
        rebuilt_dirs = {}
        edit_root_resolved = edit_root.resolve()

        for src in edit_files:
            rel = src.resolve().relative_to(edit_root_resolved)
            rel_str = _vip_clean_relative_path(rel)
            if not rel_str or rel_str.startswith('../') or '/..' in rel_str:
                raise ValueError(f'Invalid EDIT path: {rel}')

            target_path = target_root / PurePath(rel_str)
            target_path = PurePath(_vip_clean_relative_path(target_path))
            target_dir = _vip_clean_relative_path(target_path.parent)
            target_dir = (target_dir + '/') if target_dir not in ('', '.') else ''
            name = target_path.name
            if not name:
                continue

            # Create every parent directory represented by the supplied structure.
            parts = [x for x in target_dir.rstrip('/').split('/') if x]
            for i in range(1, len(parts) + 1):
                d = '/'.join(parts[:i]) + '/'
                rebuilt_dirs.setdefault(d, {})
            rebuilt_dirs.setdefault(target_dir, {})

            raw = src.read_bytes()
            template = _vip_template_for_path(pak, original_dirs, rel_str)
            if template is None:
                raise ValueError(f'No PAK entry available as metadata template for: {rel_str}')

            ne = _cp.copy(template)
            ne.compressed_blocks = []
            ne.content_hash = SHA1.new(raw).digest()
            ne.unk2 = SHA1.new((mp_str + target_dir + name).lower().encode('utf-8')).digest()
            ne.compression_method = _default_compression(pak)
            ne.encryption_method = 0
            ne.encrypted = False
            ne.compression_block_size = 65536
            ne.index_new_sep = 0

            _write_entry_content(out_buf, ne, raw, PurePath(target_dir + name), pak._zstd_dict)
            rebuilt_dirs[target_dir][name] = ne
            new_files.append(ne)

        # ------------------------------------------------------------------
        # BUILD NEW PAK: mandatory side-by-side marker structure.
        # These are kept as literal PAK directory strings so '.' and '>' are
        # not normalized away by pathlib. They are siblings of Content under
        # the selected target root.
        # ------------------------------------------------------------------
        # The required folders are siblings of `Content`, not children of
        # the selected Lua destination.  Resolve the package root from the
        # first literal `Content` segment so both planes land in the same
        # side-by-side structure.
        target_clean = _vip_clean_relative_path(target_root).strip('/')
        target_parts = target_clean.split('/') if target_clean else []
        # Always resolve the package root from the original PAK index.  This
        # makes the extra directories siblings of Content for BOTH planes.
        mandatory_base = ''
        for _raw_dir in original_dirs.keys():
            _parts = [x for x in str(_raw_dir).replace('\\', '/').split('/') if x]
            _ci = next((i for i, part in enumerate(_parts) if part.lower() == 'content'), None)
            if _ci is not None:
                mandatory_base = '/'.join(_parts[:_ci])
                break
        if not mandatory_base:
            # Plane 1 already carries the package root explicitly.
            _ci = next((i for i, part in enumerate(target_parts) if part.lower() == 'content'), None)
            if _ci is not None:
                mandatory_base = '/'.join(target_parts[:_ci])
            elif target_parts:
                mandatory_base = target_parts[0]
        mandatory_prefix = (mandatory_base + '/') if mandatory_base else ''
        mandatory_dirs = [
            f'{mandatory_prefix}protected_system32_drivers',
            f'{mandatory_prefix}bypass_32×64_decca',
            f'{mandatory_prefix}server @ZonE_Mod|_|_|_|_|.|.|',
            f'{mandatory_prefix}buyMod_@zOne_mOd',
            f'{mandatory_prefix}Crack_Your_Device2000×1000',
            f'{mandatory_prefix}Buy_Tools_From - @SharkFlux',
            f'{mandatory_prefix}done_done_done@@@@@@@@@@@@@@@@',        
        ]
        for forced_dir in mandatory_dirs:
            rebuilt_dirs.setdefault(forced_dir, {})

        # Keep the requested directory strings literally in the PAK index.
        # Each directory receives one nested, deliberately opaque-looking
        # marker directory and an inert text payload.  The payload is stored as
        # data only; it is never executed by the builder.
        visual_payload = '''//BYPASS FOR IOS DEVICES BY ZYREX_PRIME
hooking, or exploit. For fun/visual only.
import java.util.Random;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

public class PatchLines {
    private static final Random R = new Random();
    private static final String[] LIBS = {
        "libanogs.so", "libUE4.so", "libbgs.so", "libanticheat.so", "libgamecore.so"
    };
    private static final String[] TEMPLATES = {
        "PATCH_LIB(\"%s\", \"%s\", \"EDIT HEX\");",
        "PATCH_LIB(\"%s\", \"%s\", \"NOP OUT\");",
        "PATCH_LIB(\"%s\", \"%s\", \"WRITE BYTES\");",
        "PATCH_LIB(\"%s\", \"%s\", \"FLT PATCH\");"
    };
    public static void main(String[] args) throws Exception {
        System.out.println("PATCH_LIB(\"libanogs.so\", \"0x3E8508\", \"EDIT HEX\");");
        System.out.println("PATCH_LIB(\"libanogs.so\", \"0x3F2110\", \"EDIT HEX\");");
        System.out.println("PATCH_LIB(\"libanogs.so\", \"0x404D50\", \"EDIT HEX\");");
        System.out.println("// Reminder: This output is simulated for prank/entertainment only.");
    }
}
'''
        # Deterministic weird nested names, safe as archive strings.
        weird_names = [
            'xX__VOID_7F3A9C__Xx', 'N0t_A_F0lder_9A7', '___qW7-NULL-Ω___',
            '0x00__ZNE__4D2', 'zzZ__UNREADABLE__91', '.___Q9___..', 'KX91__∆__7B44'
        ]
        forced_entries = []
        for i, forced_dir in enumerate(mandatory_dirs):
            nested_dir = f'{forced_dir}/'+weird_names[i]
            rebuilt_dirs.setdefault(forced_dir, {})
            rebuilt_dirs.setdefault(nested_dir, {})
            forced_entries.append((nested_dir, f'PATCH_LINES_{i+1:02d}.txt'))
        marker_raw = visual_payload.encode('utf-8')
        marker_template = _vip_template_for_path(pak, original_dirs, PurePath('ZONE/@ZONE_MOD.txt'))
        if marker_template is None:
            raise ValueError('No PAK entry available for mandatory marker template.')
        for nested_dir, marker_name in forced_entries:
            marker_entry = _cp.copy(marker_template)
            marker_entry.compressed_blocks = []
            marker_entry.content_hash = SHA1.new(marker_raw).digest()
            marker_entry.unk2 = SHA1.new((mp_str + nested_dir + marker_name).lower().encode('utf-8')).digest()
            marker_entry.compression_method = _default_compression(pak)
            marker_entry.encryption_method = 0
            marker_entry.encrypted = False
            marker_entry.compression_block_size = 65536
            marker_entry.index_new_sep = 0
            _write_entry_content(out_buf, marker_entry, marker_raw, PurePath(nested_dir + '/' + marker_name), pak._zstd_dict)
            rebuilt_dirs[nested_dir][marker_name] = marker_entry
            new_files.append(marker_entry)

        # The requested ZONE marker is included above; do not add a second
        # normalized copy here.
        marker_dir = f'{mandatory_prefix}ZONE/././'
        marker_name = '@ZONE_MOD/////'

        # HARD INDEX INVARIANT: never serialize a build unless the exact
        # literal directory keys are still present immediately before the
        # footer is written.  Do NOT pass these keys through Path/PurePath.
        required_literal_dirs = tuple(mandatory_dirs)
        missing_literal_dirs = [d for d in required_literal_dirs if d not in rebuilt_dirs]
        if missing_literal_dirs:
            raise ValueError(
                'Mandatory literal PAK directory keys were normalized or removed: '
                + ', '.join(missing_literal_dirs)
            )

        # Keep this assertion close to the serialization boundary so future
        # edits cannot silently remove the required raw strings.
        for _required_dir in mandatory_dirs:
            assert rebuilt_dirs[_required_dir] is not None

        # ------------------------------------------------------------------
        # BUILD NEW PAK: safe anti-theft/integrity marker.
        # This is metadata only; it does not create traversal paths or
        # deliberately crash third-party extractors.  The marker lets this
        # tool recognize a package produced by BUILD NEW PAK and verify that
        # the expected protection record survived the build.
        # ------------------------------------------------------------------
        protection_dir = f'{mandatory_prefix}ZONE_PROTECTION/'
        protection_name = '@ZONE_MOD_PROTECTED'
        protection_raw = (
            b'ZONE_BUILD_PROTECTION\n'
            b'FORMAT=PAK_INDEX_MARKER\n'
            b'INTEGRITY=SHA1\n'
            b'PURPOSE=ANTI_TAMPER\n'
        )
        protection_entry = _cp.copy(marker_template)
        protection_entry.compressed_blocks = []
        protection_entry.content_hash = SHA1.new(protection_raw).digest()
        protection_entry.unk2 = SHA1.new(
            (mp_str + protection_dir + protection_name).lower().encode('utf-8')
        ).digest()
        protection_entry.compression_method = _default_compression(pak)
        protection_entry.encryption_method = 0
        protection_entry.encrypted = False
        protection_entry.compression_block_size = 65536
        protection_entry.index_new_sep = 0
        _write_entry_content(
            out_buf, protection_entry, protection_raw,
            PurePath(protection_dir + protection_name), pak._zstd_dict
        )
        rebuilt_dirs.setdefault(protection_dir, {})[protection_name] = protection_entry
        new_files.append(protection_entry)

        # Hard invariant for the safe protection marker.
        if protection_name not in rebuilt_dirs.get(protection_dir, {}):
            raise ValueError('Anti-theft integrity marker was not registered in the PAK index.')

        output_path.parent.mkdir(parents=True, exist_ok=True)
        _write_pak_index_footer(
            pak, mp_str, rebuilt_dirs, new_files, {}, out_buf, output_path
        )

        console.print(_ui_panel(
            'BUILD NEW PAK COMPLETE',
            Group(
                Text(f'FILES: {len(new_files)}', style='bold #00FF88'),
                Text(f'PATH: {target_root.as_posix()} + EDIT structure', style='dim #AAB7C8'),
                Text(f'OUTPUT: {output_path}', style='dim #AAB7C8'),
            ),
            '#00FF88',
        ))
        return True
    except Exception as e:
        console.print(f'[red]BUILD NEW PAK error: {e}[/red]')
        return False

# ==================== UI FUNCTIONS ====================


def dump_unpacking_log(pak_file, output_log_path: Path):
    try:
        with open(output_log_path, 'w', encoding='utf-8') as log_file:
            log_file.write('================================================================================\n')
            log_file.write('PAK UNPACKING DEBUG LOG\n')
            log_file.write('================================================================================\n\n')
            log_file.write(f'PAK File: {pak_file._file_path}\n')
            log_file.write(f'PAK Info Version: {pak_file._pak_info.version}\n')
            log_file.write(f'Mount Point: {pak_file._mount_point}\n')
            log_file.write('--------------------------------------------------------------------------------\n\n')
            file_count = 0
            for dir_path, files in pak_file._index.items():
                for file_name, entry in files.items():
                    file_count += 1
                    full_path = str(PurePath(dir_path) / file_name).replace('\\', '/')
                    log_file.write(f'\n[{file_count}] {full_path}\n')
                    log_file.write(f'  Uncompressed Size: {entry.uncompressed_size:,} bytes\n')
                    log_file.write(f'  Compressed Size: {entry.size:,} bytes\n')
                    log_file.write(f'  Compression Method: {entry.compression_method}\n')
                    log_file.write(f'  Encryption Method: {entry.encryption_method}\n')
                    log_file.write(f'  Compressed Blocks: {len(entry.compressed_blocks)}\n')
                    if entry.compressed_blocks:
                        for i, blk in enumerate(entry.compressed_blocks):
                            block_size = blk.end - blk.start
                            log_file.write(f'    Block {i}: Offset={blk.start:,} Size={block_size:,} bytes\n')
            log_file.write('\n================================================================================\n')
            log_file.write('END OF LOG\n')
            log_file.write('================================================================================\n')
        console.print(f'[bold #00FF88]✅ Debug log saved to: {output_log_path}[/]')
    except:
        pass

def ensure_directories(base_dir: Path):
    try:
        (base_dir / "PAK").mkdir(parents=True, exist_ok=True)
        (base_dir / "UNPACK").mkdir(parents=True, exist_ok=True)
        (base_dir / "REPACK").mkdir(parents=True, exist_ok=True)
        (base_dir / "RESULT").mkdir(parents=True, exist_ok=True)
        pak_tool_dir = base_dir / "PAK TOOL"
        (pak_tool_dir / "EDIT").mkdir(parents=True, exist_ok=True)
        (pak_tool_dir / "UNPACK").mkdir(parents=True, exist_ok=True)
        (pak_tool_dir / "RESULT").mkdir(parents=True, exist_ok=True)
        (pak_tool_dir / "PAK").mkdir(parents=True, exist_ok=True)
        # BUILD NEW PAK uses only these three folders:
        # 1 PAK ORGINAL / 2 EDIT / 3 OUT
        costume_dir = base_dir / "BUILD NEW PAK"
        (costume_dir / "1 PAK ORGINAL").mkdir(parents=True, exist_ok=True)
        (costume_dir / "2 EDIT").mkdir(parents=True, exist_ok=True)
        (costume_dir / "3 OUT").mkdir(parents=True, exist_ok=True)

        # Remove only the old duplicate folders when they are empty.
        # Never delete user data from them automatically.
        for old_name in ("EDIT", "OUT"):
            old_dir = costume_dir / old_name
            if old_dir.exists() and old_dir.is_dir():
                try:
                    if not any(old_dir.iterdir()):
                        old_dir.rmdir()
                except Exception:
                    pass
    except:
        pass

def print_banner():
    _ui_clear()
    g=Group(Align.center(_ui_rainbow_text('ZONE TOOL',0,True)),Align.center(Text('PAK TOOL / GAMEPATCH EDITION',style='bold white')),Text(''),Align.center(Text('TERMUX • RGB NEON INTERFACE',style='bold #00E5FF')))
    console.print(RainbowPanel(g,'ZONE TOOL','RGB MOVING BORDER'))
    console.print()


def get_indian_time():
    try:
        tz = pytz.timezone("Asia/Kolkata")
        return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    except:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def safe_input(prompt: str='') -> str:
    try:
        return input(prompt)
    except (EOFError, RuntimeError):
        try:
            if sys.platform != 'win32':
                with open('/dev/tty', 'r') as tty:
                    sys.stderr.write(prompt)
                    sys.stderr.flush()
                    return tty.readline().rstrip('\n')
            else:
                with open('CON', 'r') as con:
                    sys.stderr.write(prompt)
                    sys.stderr.flush()
                    return con.readline().rstrip('\r\n')
        except:
            return ''
    except:
        return ''

def human_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f'{size:.2f} {unit}'
        size /= 1024.0
    return f'{size:.2f} PB'

def _ui_clear():
    try: os.system('cls' if os.name=='nt' else 'clear')
    except Exception: pass


def _ui_panel(title,body,accent='#00E5FF',subtitle=None):
    return RainbowPanel(body,str(title).upper(),subtitle or '')


def _ui_pause(label='Press Enter to continue...'):
    safe_input(f'\n[bold #00CFFF]{label}[/] ')


def _ui_action(title,subtitle=''):
    _ui_clear(); g=Group(Align.center(Text(str(title).upper(),style='bold #00E5FF')),Align.center(Text(subtitle,style='bold #00E5FF')) if subtitle else Text(''),Text(''),Align.center(Text('PROCESSING',style='bold #00E5FF'))); console.print(RainbowPanel(g,'ZONE TOOL','RGB ACTIVE')); console.print()


def safe_method_pak(data_path: Path) -> bool:
    """Create a portable ZIP from BUILD NEW PAK/3 OUT.

    The ZIP always contains exactly this root layout:
        <Name Pak>/files/UE4Game/ShadowTrackerExtra/ShadowTrackerExtra/Saved/Paks/Paks/<file>

    All files currently present in BUILD NEW PAK/3 OUT are included, preserving
    their relative names. The generated ZIP is saved under Safe Method Pak.
    """
    try:
        out_dir = data_path / 'BUILD NEW PAK' / '3 OUT'
        safe_dir = data_path / 'Safe Method Pak'
        safe_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        raw_name = _ui_prompt(
            'SAFE METHOD PAK',
            'Enter the folder name for the ZIP package.\nExample: ZONE',
            'Name Pak:'
        ).strip()
        if not raw_name:
            _ui_error('INVALID NAME', 'No package folder name was provided.')
            return False

        # Folder name only: prevent absolute paths and parent traversal.
        package_name = sanitize_path(raw_name).name
        if package_name in ('', '.', '..'):
            _ui_error('INVALID NAME', 'The package folder name is not valid.')
            return False

        files = sorted((p for p in out_dir.rglob('*') if p.is_file()), key=lambda x: x.as_posix().lower())
        if not files:
            _ui_error('OUT EMPTY', f'No files were found in: {out_dir}')
            return False

        # If several PAK/files exist, let the user choose exactly one to package.
        if len(files) > 1:
            console.print(_ui_panel(
                'SELECT PAK',
                Group(*[
                    Text(f'[{i}] {src.relative_to(out_dir).as_posix()}', style='bold #00E5FF')
                    for i, src in enumerate(files, 1)
                ]),
                '#00E5FF',
            ))
            while True:
                raw_choice = _ui_prompt('SELECT PAK', f'Choose the file to ZIP (1-{len(files)})', 'PAK NUMBER:').strip()
                try:
                    choice_num = int(raw_choice)
                except ValueError:
                    _ui_error('INVALID CHOICE', 'Please enter a valid number.')
                    continue
                if 1 <= choice_num <= len(files):
                    files = [files[choice_num - 1]]
                    break
                _ui_error('INVALID CHOICE', f'Choose a number from 1 to {len(files)}.')

        zip_path = safe_dir / f'{package_name}.zip'
        if zip_path.exists():
            try:
                zip_path.unlink()
            except Exception:
                pass

        fixed_root = f'{package_name}/files/UE4Game/ShadowTrackerExtra/ShadowTrackerExtra/Saved/Paks/Paks/'
        _ui_action('SAFE METHOD PAK', f'{package_name}.zip')
        console.print(_ui_panel(
            'SAFE METHOD PAK',
            Group(
                Text(f'SOURCE: {out_dir}', style='dim #AAB7C8'),
                Text(f'FILES: {len(files)}', style='bold #00FF88'),
                Text(f'TARGET: {fixed_root}<file>', style='bold #00E5FF'),
                Text(f'OUTPUT: {zip_path}', style='dim #AAB7C8'),
            ),
            '#00FF88',
        ))

        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for src in files:
                # Keep every OUT file directly under the requested Paks/Paks path.
                # If duplicate basenames exist in subfolders, preserve the relative
                # path below Paks/Paks to avoid overwriting ZIP members.
                rel = src.relative_to(out_dir).as_posix()
                arcname = fixed_root + rel
                zf.write(src, arcname)

        _ui_success('SAFE PACKAGE READY', [
            ('NAME', package_name),
            ('FILES', str(len(files))),
            ('ZIP', zip_path),
            ('SIZE', human_size(zip_path.stat().st_size)),
        ])
        console.print(_ui_panel(
            'EXTRACTED STRUCTURE',
            Text(
                f'{package_name}/files/UE4Game/ShadowTrackerExtra/ShadowTrackerExtra/Saved/Paks<file>',
                style='bold #00FF88'
            ),
            '#00FF88'
        ))
        return True
    except Exception as e:
        _ui_error('SAFE METHOD PAK FAILED', e)
        import traceback
        traceback.print_exc()
        return False


def delete_folder(data_path: Path) -> None:
    try:
        folders = []
        for item in data_path.iterdir():
            if item.is_dir() and item.name not in ['PAK', 'UNPACK', 'REPACK', 'RESULT', 'PAK TOOL', 'BUILD NEW PAK']:
                folders.append(item)
        if not folders:
            console.print(_ui_panel('NO FOLDERS', Text('No removable folders were found.', style='dim #AAB7C8'), '#7C4DFF'))
            return

        table = Table(expand=True, box=ROUNDED, border_style='#26364E', show_lines=False, padding=(0, 1))
        table.add_column('#', justify='center', width=4, style='bold #00E5FF')
        table.add_column('FOLDER', style='bold white')
        table.add_column('SIZE', justify='right', style='dim #AAB7C8')
        for i, folder in enumerate(folders, 1):
            folder_size = 0
            for root, dirs, files in os.walk(folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    if os.path.isfile(file_path):
                        folder_size += os.path.getsize(file_path)
            table.add_row(str(i), folder.name, human_size(folder_size))

        console.print(_ui_panel('DELETE FOLDER', table, '#7C4DFF', f'{len(folders)} folders available'))
        try:
            choice = int(safe_input(f'[bold #00E5FF]>[/] Select folder [1-{len(folders)}]: ').strip())
            if 1 <= choice <= len(folders):
                selected_folder = folders[choice - 1]
                confirm = safe_input(
                    f'[bold #00E5FF]CONFIRM ACTION[/]\n[dim]Delete:[/] {selected_folder.name}\n\n[bold #00E5FF][Y][/] Continue  [bold #7C4DFF][N][/] Cancel\n[bold #00E5FF]>[/] '
                ).strip().lower()
                if confirm in ('y', 'yes'):
                    shutil.rmtree(selected_folder)
                    console.print(_ui_panel('OPERATION COMPLETE', Text(f'Deleted: {selected_folder.name}', style='bold #00E5FF'), '#00E5FF'))
                else:
                    console.print(_ui_panel('CANCELLED', Text('No changes were made.', style='dim #AAB7C8'), '#7C4DFF'))
            else:
                console.print(_ui_panel('INVALID SELECTION', Text('Enter a valid folder number.', style='bold #FF4F7B'), '#FF4F7B'))
        except ValueError:
            console.print(_ui_panel('INVALID INPUT', Text('Enter a numeric selection.', style='bold #FF4F7B'), '#FF4F7B'))
    except Exception as e:
        console.print(_ui_panel('OPERATION FAILED', Text(str(e), style='bold #FF4F7B'), '#FF4F7B'))


def display_file_selector(title, folder_path, file_pattern='*.pak'):
    """Reference-style PAK picker; selection semantics are unchanged."""
    try:
        files = sorted(folder_path.glob(file_pattern), key=lambda x: x.name.lower())
        if not files:
            console.print(Text('No PAK files found.', style='bold #00FF44'))
            return None, None

        width = max(58, min(console.size.width - 2, 120))
        inner = width - 2
        no_w = max(8, min(12, inner // 7))
        size_w = max(13, min(18, inner // 6))
        file_w = max(20, inner - no_w - size_w)

        def rgb(pos):
            return Style.parse(_ui_rgb_color(pos, 0.022))

        def print_segments(*segments):
            # Segment objects are low-level Rich render data, not renderables.
            # Passing them directly to console.print() makes Rich print their
            # Python repr (Segment(...)) instead of drawing the frame.
            line = Text()
            for seg in segments:
                if isinstance(seg, Segment):
                    line.append(seg.text, style=seg.style)
                else:
                    line.append(str(seg))
            console.print(line)

        def clip_name(name, max_len):
            name = str(name)
            return name if len(name) <= max_len else (name[:max_len-3] + '...' if max_len > 3 else name[:max_len])

        def size_mb(path):
            try:
                return f'{path.stat().st_size / (1024 * 1024):.2f}'
            except Exception:
                return '0.00'

        console.print()
        console.print(Align.center(Text('Select PAK File', style='bold italic white')))
        console.print()

        # Top border / header.
        print_segments(
            Segment('┌', rgb(0)), Segment('─' * no_w, rgb(4)), Segment('┬', rgb(10)),
            Segment('─' * file_w, rgb(18)), Segment('┬', rgb(26)),
            Segment('─' * size_w, rgb(32)), Segment('┐', rgb(40)))

        def data_row(pos, no, name, size, no_style, name_style, size_style):
            return [
                Segment('│', rgb(pos)),
                Segment(str(no).center(no_w), Style.parse(no_style)),
                Segment('│', rgb(pos + 7)),
                Segment(clip_name(name, file_w).ljust(file_w), Style.parse(name_style)),
                Segment('│', rgb(pos + 25)),
                Segment(str(size).center(size_w), Style.parse(size_style)),
                Segment('│', rgb(pos + 40)),
            ]

        print_segments(*data_row(45, 'No.', 'File Name', 'Size',
                                  'bold italic #FFE900', 'bold italic #FFE900',
                                  'bold italic #FFE900'))

        print_segments(
            Segment('├', rgb(55)), Segment('─' * no_w, rgb(60)), Segment('┼', rgb(66)),
            Segment('─' * file_w, rgb(72)), Segment('┼', rgb(78)),
            Segment('─' * size_w, rgb(84)), Segment('┤', rgb(90)))

        for i, f in enumerate(files, 1):
            # Each PAK gets its own separated row so multiple files cannot visually merge.
            size_text = f'{size_mb(f)} MB'
            print_segments(*data_row(96 + i * 2, i, f.name, size_text,
                                     'bold #00FF44', 'bold italic white',
                                     'bold italic #00FF44'))

            # Divider between PAK entries (but not after the last one).
            if i < len(files):
                print_segments(
                    Segment('├', rgb(110 + i * 3)), Segment('─' * no_w, rgb(114 + i * 3)),
                    Segment('┼', rgb(118 + i * 3)), Segment('─' * file_w, rgb(122 + i * 3)),
                    Segment('┼', rgb(126 + i * 3)), Segment('─' * size_w, rgb(130 + i * 3)),
                    Segment('┤', rgb(134 + i * 3))
                )

        print_segments(
            Segment('└', rgb(120)), Segment('─' * no_w, rgb(126)), Segment('┴', rgb(132)),
            Segment('─' * file_w, rgb(138)), Segment('┴', rgb(144)),
            Segment('─' * size_w, rgb(150)), Segment('┘', rgb(156)))

        console.print()
        console.print(Text(f'Enter number ({len(files)}):', style='bold italic #00FF44'), end=' ')
        raw = safe_input().strip()
        if raw == '0':
            return None, files
        idx = int(raw) - 1
        if idx < 0 or idx >= len(files):
            console.print(Text('Invalid file number.', style='bold #FF4F7B'))
            return None, files
        return files[idx], files
    except (ValueError, TypeError):
        console.print(Text('Enter a numeric selection.', style='bold #FF4F7B'))
        return None, files if 'files' in locals() else None
    except Exception as e:
        console.print(Text(f'File selector error: {e}', style='bold #FF4F7B'))
        return None, None


def inject_edit_files(pak_file, edit_root, output_path, protect_new=False, sm4_type=47):
    import copy as _cp
    version = pak_file._pak_info.version
    if version < 12:
        raise ValueError(f'Unsupported pak version: {version} (need >= 12)')
    
    edit_files = [p for p in Path(edit_root).rglob('*') if p.is_file()]
    if not edit_files:
        raise ValueError(f'No files found in EDIT folder: {edit_root}')
    
    mp_str, all_dirs = _get_all_dirs_and_mp(pak_file)
    
    injections = {}
    for p in edit_files:
        rel = p.relative_to(edit_root)
        parts = rel.parts
        file_name = parts[-1]
        rel_dir = '/'.join(parts[:-1]).replace('\\', '/')
        rel_dir = _strip_mount_prefix(pak_file, rel_dir)
        target_dir = _find_existing_dir(all_dirs, rel_dir) if rel_dir.strip('/') else ''
        if target_dir is None:
            target_dir = _normalize_dir_key(rel_dir)
        existing = None
        if target_dir in all_dirs:
            for name, e in list(all_dirs[target_dir].items()):
                if name.lower() == file_name.lower():
                    existing = (name, e)
                    break
        if existing:
            full_path = target_dir + existing[0]
            injections[full_path] = (p, existing[1], False)
        else:
            full_path = target_dir + file_name
            template = _pick_template(pak_file, all_dirs, target_dir, file_name)
            injections[full_path] = (p, template, True)
        console.print(f'  [bold #00E5FF]●[/] [white]{full_path}[/white] '
                      f'[dim]({"replace existing" if existing else "add new"})[/dim]')
    
    new_files = []
    for e in pak_file._files:
        ne = _cp.copy(e)
        ne.compressed_blocks = [_cp.copy(b) for b in e.compressed_blocks]
        new_files.append(ne)
    old_to_new = {id(pak_file._files[i]): new_files[i] for i in range(len(pak_file._files))}
    
    out_buf = bytearray()
    edited_count = 0
    new_count = 0
    
    for dp_str, dir_files in list(all_dirs.items()):
        for name, old_entry in list(dir_files.items()):
            full_path = str(PurePath(dp_str) / name).replace('\\', '/')
            ne = old_to_new.get(id(old_entry), None)
            if ne is None:
                ne = _cp.copy(old_entry)
                ne.compressed_blocks = [_cp.copy(b) for b in old_entry.compressed_blocks]
                new_files.append(ne)
                old_to_new[id(old_entry)] = ne
            
            if full_path in injections:
                p, template, is_new = injections[full_path]
                new_raw = p.read_bytes()
                pak_rel = PurePath(full_path)
                ne.content_hash = SHA1.new(new_raw).digest()
                ne.uncompressed_size = len(new_raw)
                if is_new:
                    ne.compression_method = _default_compression(pak_file)
                    if protect_new:
                        ne.encryption_method = sm4_type
                        ne.encrypted = True
                    else:
                        ne.encryption_method = template.encryption_method if template else 0
                        ne.encrypted = template.encrypted if template else False
                    ne.unk1 = template.unk1 if template else 0
                    ne.compression_block_size = (template.compression_block_size if template
                                                 and template.compression_block_size > 0 else 65536)
                    ne.index_new_sep = template.index_new_sep if template else 0
                    new_count += 1
                else:
                    ne.compression_method = old_entry.compression_method
                    if protect_new:
                        ne.encryption_method = sm4_type
                        ne.encrypted = True
                    else:
                        ne.encryption_method = old_entry.encryption_method
                        ne.encrypted = old_entry.encrypted
                    ne.unk1 = old_entry.unk1
                    ne.compression_block_size = (old_entry.compression_block_size
                                                 if old_entry.compression_block_size > 0 else 65536)
                    ne.index_new_sep = old_entry.index_new_sep
                    edited_count += 1
                ne.unk2 = SHA1.new((mp_str + full_path).lower().encode('utf-8')).digest()
                _write_entry_content(out_buf, ne, new_raw, pak_rel, pak_file._zstd_dict)
                console.print(f'  [bold #00FF88]✓[/] '
                              f'[#00E5FF]{"Edited" if not is_new else "Added"}[/]: {full_path} '
                              f'[dim]({len(new_raw):,} bytes)[/dim]')
            else:
                _copy_original_content(out_buf, pak_file, ne, old_entry)
    
    for full_path, (p, template, is_new) in injections.items():
        if not is_new:
            continue
        already = False
        for dp_str, dir_files in all_dirs.items():
            for name, entry in dir_files.items():
                if str(PurePath(dp_str) / name).replace('\\', '/') == full_path:
                    already = True
                    break
            if already:
                break
        if already:
            continue
        ne = _cp.copy(template) if template else None
        if ne is None:
            ne = TencentPakEntry(Reader(b''), version)
            ne.compression_method = CM_NONE
            ne.encrypted = False
        else:
            ne.compressed_blocks = [_cp.copy(b) for b in template.compressed_blocks]
        new_raw = p.read_bytes()
        pak_rel = PurePath(full_path)
        ne.content_hash = SHA1.new(new_raw).digest()
        ne.uncompressed_size = len(new_raw)
        ne.compression_method = _default_compression(pak_file)
        if protect_new:
            ne.encryption_method = sm4_type
            ne.encrypted = True
        else:
            ne.encryption_method = template.encryption_method if template else 0
            ne.encrypted = template.encrypted if template else False
        ne.unk1 = template.unk1 if template else 0
        ne.compression_block_size = (template.compression_block_size if template
                                     and template.compression_block_size > 0 else 65536)
        ne.index_new_sep = template.index_new_sep if template else 0
        ne.unk2 = SHA1.new((mp_str + full_path).lower().encode('utf-8')).digest()
        _write_entry_content(out_buf, ne, new_raw, pak_rel, pak_file._zstd_dict)
        new_files.append(ne)
        old_to_new[id(ne)] = ne
        dp_key = full_path.rsplit('/', 1)[0] + '/' if '/' in full_path else ''
        all_dirs.setdefault(dp_key, {})[full_path.rsplit('/', 1)[-1]] = ne
        new_count += 1
        console.print(f'  [bold #00FF88]✓[/] '
                      f'[#00E5FF]Added[/]: {full_path} '
                      f'[dim]({len(new_raw):,} bytes)[/dim]')
    
    _write_pak_index_footer(pak_file, mp_str, all_dirs, new_files, old_to_new, out_buf, output_path)
    return edited_count, new_count

def protect_pak_file(pak_file, output_path, sm4_type=47):
    import copy as _cp
    version = pak_file._pak_info.version
    if version < 12:
        raise ValueError(f'Unsupported pak version: {version} (need >= 12)')
    
    mp_str, all_dirs = _get_all_dirs_and_mp(pak_file)
    new_files = []
    for e in pak_file._files:
        ne = _cp.copy(e)
        ne.compressed_blocks = [_cp.copy(b) for b in e.compressed_blocks]
        new_files.append(ne)
    old_to_new = {id(pak_file._files[i]): new_files[i] for i in range(len(pak_file._files))}
    
    out_buf = bytearray()
    protected = 0
    skipped = 0
    
    for dp_str, dir_files in list(all_dirs.items()):
        for name, old_entry in list(dir_files.items()):
            full_path = str(PurePath(dp_str) / name).replace('\\', '/')
            ne = old_to_new.get(id(old_entry), None)
            if ne is None:
                ne = _cp.copy(old_entry)
                ne.compressed_blocks = [_cp.copy(b) for b in old_entry.compressed_blocks]
                new_files.append(ne)
                old_to_new[id(old_entry)] = ne
            
            is_marker = (old_entry.compression_method == CM_NONE and old_entry.size == 0)
            is_zdict = (pak_file._zstd_dict_entry is not None and old_entry is pak_file._zstd_dict_entry)
            if is_marker or is_zdict:
                _copy_original_content(out_buf, pak_file, ne, old_entry)
                skipped += 1
                continue
            
            try:
                plaintext = _extract_entry_plaintext(pak_file, old_entry, full_path)
            except:
                _copy_original_content(out_buf, pak_file, ne, old_entry)
                skipped += 1
                console.print(f"  [bold red]![/bold red] [red]Skipped undecryptable[/red]: {full_path}")
                continue
            ne.compression_method = old_entry.compression_method
            if ne.compression_method == CM_NONE:
                ne.compression_method = CM_ZLIB
            ne.encryption_method = sm4_type
            ne.encrypted = True
            ne.unk1 = old_entry.unk1
            ne.unk2 = old_entry.unk2
            ne.index_new_sep = old_entry.index_new_sep
            ne.compression_block_size = (old_entry.compression_block_size
                                         if old_entry.compression_block_size > 0 else 65536)
            _write_entry_content(out_buf, ne, plaintext, PurePath(full_path), pak_file._zstd_dict, fast=True)
            protected += 1
            if protected <= 12 or protected % 250 == 0:
                console.print(f'  [bold #7C4DFF]PROTECT[/] '
                              f'[#7C4DFF]Re-encrypted[/]: {full_path} '
                              f'[dim]({len(plaintext):,} bytes)[/dim]')
    
    _write_pak_index_footer(pak_file, mp_str, all_dirs, new_files, old_to_new, out_buf, output_path)
    return protected, skipped

def _normalize_dir_key(path_str):
    s = str(path_str).replace('\\', '/').strip('/')
    return (s + '/') if s else ''

def _find_existing_dir(all_dirs, want_dir):
    want = _normalize_dir_key(want_dir).strip('/').lower()
    if not want:
        return ''
    for k in all_dirs:
        if k.strip('/').lower() == want:
            return k
    best = None
    for k in all_dirs:
        key = k.strip('/').lower()
        if key and want.endswith('/' + key):
            if best is None or len(key) > len(best):
                best = k
    return best

def _strip_mount_prefix(pak_file, rel_dir):
    mp = str(pak_file._mount_point).replace('\\', '/').strip('/')
    rd = str(rel_dir).replace('\\', '/').strip('/')
    if mp and (rd.lower() == mp.lower() or rd.lower().startswith(mp.lower() + '/')):
        return rd[len(mp):].lstrip('/')
    return rd

def _pick_template(pak_file, all_dirs, target_dir, file_name):
    ext = Path(file_name).suffix.lower()
    if target_dir in all_dirs:
        for name, e in all_dirs[target_dir].items():
            if Path(name).suffix.lower() == ext:
                return e
    for dp, files in all_dirs.items():
        for name, e in files.items():
            if Path(name).suffix.lower() == ext:
                return e
    for dp, files in all_dirs.items():
        for name, e in files.items():
            return e
    return pak_file._files[0] if pak_file._files else None

def _default_compression(pak_file):
    cm_counter = {}
    for e in pak_file._files:
        cm = e.compression_method
        if cm in (CM_ZLIB, CM_ZSTD, CM_ZSTD_DICT):
            cm_counter[cm] = cm_counter.get(cm, 0) + 1
    if pak_file._is_zstd_with_dict and cm_counter.get(CM_ZSTD_DICT, 0):
        return CM_ZSTD_DICT
    if cm_counter.get(CM_ZSTD, 0):
        return CM_ZSTD
    if cm_counter.get(CM_ZSTD_DICT, 0):
        return CM_ZSTD
    return CM_ZLIB

def _write_entry_content(out_buf, ne, plaintext, pak_rel, zstd_dict, fast=False):
    if ne.compression_method == CM_NONE:
        cipher = (_encrypt_plaintext(plaintext, pak_rel, ne.encryption_method) if ne.encrypted else plaintext)
        ne.offset = len(out_buf)
        ne.size = len(plaintext)
        ne.uncompressed_size = len(plaintext)
        out_buf += cipher
        return
    cs = ne.compression_block_size if ne.compression_block_size > 0 else 65536
    chunks = [plaintext[i:i + cs] for i in range(0, len(plaintext), cs)]
    if not chunks:
        ne.compressed_blocks = []
        ne.offset = len(out_buf)
        ne.size = 0
        ne.uncompressed_size = 0
        return
    n = len(chunks)
    inv = PakCrypto.generate_block_indices(n, ne.encryption_method) if ne.encrypted else list(range(n))
    file_order = [0] * n
    for j in range(n):
        file_order[inv[j]] = j
    new_blks = [None] * n
    for k in range(n):
        chunk = chunks[file_order[k]]
        compressed = _best_compress(chunk, ne.compression_method, zstd_dict, fast=fast)
        cipher = (_encrypt_plaintext(compressed, pak_rel, ne.encryption_method) if ne.encrypted else compressed)
        blk = PakCompressedBlock.__new__(PakCompressedBlock)
        blk.start = len(out_buf)
        blk.end = blk.start + len(cipher)
        out_buf += cipher
        new_blks[k] = blk
    ne.compressed_blocks = new_blks
    ne.offset = new_blks[0].start
    ne.size = sum(b.end - b.start for b in new_blks)
    ne.uncompressed_size = len(plaintext)

def _extract_entry_plaintext(pak_file, entry, full_path):
    em = entry.encryption_method
    cm = entry.compression_method
    path = PurePath(full_path)
    if cm == CM_NONE:
        data = pak_file._peek_content(entry.offset, entry.size, em)
        if entry.encrypted:
            data = PakCrypto.decrypt_block(data, path, em)
        return bytes(data[:entry.uncompressed_size])
    out = bytearray()
    for x in PakCrypto.generate_block_indices(len(entry.compressed_blocks), em):
        data = pak_file._peek_block_content(entry.compressed_blocks[x], em)
        if entry.encrypted:
            data = PakCrypto.decrypt_block(data, path, em)
        out += PakCompression.decompress_block(data, pak_file._zstd_dict, cm)
    return bytes(out)

def _copy_original_content(out_buf, pak_file, ne, old_entry):
    em = old_entry.encryption_method
    if old_entry.compression_method == CM_NONE:
        read_sz = (PakCrypto.align_encrypted_content_size(old_entry.size, em) if old_entry.encrypted else old_entry.size)
        ne.offset = len(out_buf)
        out_buf += bytes(pak_file._file_content[old_entry.offset: old_entry.offset + read_sz])
    elif old_entry.compressed_blocks:
        new_blks = []
        for ob in old_entry.compressed_blocks:
            unc = ob.end - ob.start
            enc = (PakCrypto.align_encrypted_content_size(unc, em) if old_entry.encrypted else unc)
            nb = PakCompressedBlock.__new__(PakCompressedBlock)
            nb.start = len(out_buf)
            nb.end = nb.start + unc
            out_buf += bytes(pak_file._file_content[ob.start: ob.start + enc])
            new_blks.append(nb)
        ne.compressed_blocks = new_blks
        ne.offset = new_blks[0].start
    ne.encryption_method = old_entry.encryption_method
    ne.encrypted = old_entry.encrypted

def _write_pak_index_footer(pak_file, mp_str, all_dirs, new_files, old_to_new, out_buf, output_path):
    version = pak_file._pak_info.version
    keystream = PakCrypto.zuc_keystream()
    eidx = {id(new_files[i]): i for i in range(len(new_files))}
    old_id_to_new_idx = {id(pak_file._files[i]): i for i in range(len(pak_file._files))}
    idx = bytearray(_pw_string(mp_str))
    idx += struct.pack('<I', len(new_files))
    for ne in new_files:
        idx += _pw_entry(ne, version)
    idx += struct.pack('<Q', len(all_dirs))
    for dp_str, dir_files in all_dirs.items():
        idx += _pw_string(dp_str)
        idx += struct.pack('<Q', len(dir_files))
        for name, old_e in dir_files.items():
            idx += _pw_string(name)
            found_idx = eidx.get(id(old_e))
            if found_idx is None:
                found_idx = old_id_to_new_idx.get(id(old_e))
            if found_idx is None:
                copy_of = next((k for k, v in old_to_new.items() if v is old_e), None)
                if copy_of is not None:
                    found_idx = eidx.get(id(old_to_new[copy_of]))
            if found_idx is None:
                for i, e in enumerate(new_files):
                    if e.offset == old_e.offset and e.size == old_e.size:
                        found_idx = i
                        break
            idx += struct.pack('<i', ~found_idx if found_idx is not None else -1)
    index_plain = bytes(idx)
    new_sha1 = SHA1.new(index_plain).digest()
    if pak_file._pak_info.index_encrypted:
        key = PakCrypto.rsa_extract(pak_file._pak_info.packed_key, RSA_MOD_1)
        iv = PakCrypto.rsa_extract(pak_file._pak_info.packed_iv, RSA_MOD_1)
        aes = AES.new(key, MODE_CBC, iv[:16])
        pad = (-len(index_plain)) % AES.block_size or AES.block_size
        index_bytes = aes.encrypt(index_plain + bytes([pad] * pad))
    else:
        index_bytes = index_plain
    new_idx_offset = len(out_buf)
    new_idx_size = len(index_bytes)
    out_buf += index_bytes
    footer_sz = TencentPakInfo._mem_size(version)
    new_footer = bytearray(pak_file._file_content[-footer_sz:])
    h_key = struct.pack('<5I', *keystream[4:9])
    new_footer[-36:-16] = bytes(a ^ b for a, b in zip(new_sha1, h_key))
    new_footer[-16:-8] = ((new_idx_size ^ (keystream[10] << 32 | keystream[11])).to_bytes(8, 'little'))
    new_footer[-8:] = ((new_idx_offset ^ (keystream[0] << 32 | keystream[1])).to_bytes(8, 'little'))
    out_buf += new_footer
    with open(output_path, 'wb') as f:
        f.write(out_buf)

def _pw_string(s):
    if not s: return struct.pack('<i', 0)
    b = s.encode('utf-8') + b'\x00'
    return struct.pack('<i', len(b)) + b

def _pw_entry(e, v):
    w = bytearray(e.content_hash)
    w += struct.pack('<Q', e.offset)
    w += struct.pack('<Q', e.uncompressed_size)
    w += struct.pack('<I', e.compression_method)
    w += struct.pack('<Q', e.size)
    if v >= 5:
        w += bytes([e.unk1])
        w += e.unk2
    if e.compression_method != CM_NONE and v >= 3:
        w += struct.pack('<I', len(e.compressed_blocks))
        for b in e.compressed_blocks:
            w += struct.pack('<QQ', b.start, b.end)
    if v >= 4:
        w += struct.pack('<I', e.compression_block_size)
        w += bytes([1 if e.encrypted else 0])
    if v >= 12:
        w += struct.pack('<II', e.encryption_method, e.index_new_sep)
    return bytes(w)

def _get_all_dirs_and_mp(pak_file):
    try:
        raw = bytes(pak_file._file_content[
            pak_file._pak_info.index_offset:][:pak_file._pak_info.index_size])
        if pak_file._pak_info.index_encrypted:
            raw = PakCrypto.decrypt_index(raw, pak_file._pak_info)
        r = Reader(raw)
        mp = r.string()
        num_files = r.u4()
        for _ in range(num_files):
            TencentPakEntry(r, pak_file._pak_info.version)
        dirs = {}
        for _ in range(r.u8()):
            dp = r.string()
            cnt = r.u8()
            dirs[dp] = {r.string(): pak_file._files[~r.i4()] for _ in range(cnt)}
        return mp, dirs
    except:
        return "", {}

def _best_compress(chunk, cm, zstd_dict=None, fast=False):
    try:
        if cm == CM_ZLIB:
            return zlib.compress(chunk, 1 if fast else 9)
        if cm in (CM_ZSTD, CM_ZSTD_DICT):
            zd = zstd_dict if cm == CM_ZSTD_DICT else None
            levels = [6, 3, 1] if fast else [22, 19, 16, 13, 10, 7, 4, 1]
            for lvl in levels:
                try:
                    return ZstdCompressor(level=lvl, dict_data=zd, threads=1).compress(chunk)
                except:
                    continue
        return chunk
    except:
        return chunk

def _encrypt_plaintext(plaintext: bytes, pak_relative_path: PurePath, encryption_method: int) -> bytes:
    try:
        if PakCrypto._is_simple1_method(encryption_method):
            return bytes((b ^ SIMPLE1_DECRYPT_KEY for b in plaintext))
        elif PakCrypto._is_simple2_method(encryption_method):
            pad = -len(plaintext) % SIMPLE2_BLOCK_SIZE
            plaintext += b'\x00' * pad
            key, = struct.unpack('<I', SIMPLE2_DECRYPT_KEY)
            rolling = key
            out = []
            for x, in struct.iter_unpack('<I', plaintext):
                c = rolling ^ x
                out.append(c)
                rolling ^= c
            return struct.pack(f'<{len(out)}I', *out)
        elif PakCrypto._is_sm4_method(encryption_method):
            key = PakCrypto._derive_sm4_key(pak_relative_path, encryption_method)
            sm4 = PakCrypto._sm4_context_for_key(key)
            pad_len = -len(plaintext) % 16
            if pad_len > 0:
                plaintext = plaintext + b'\x00' * pad_len
            return sm4.encrypt_bulk(plaintext)
        else:
            return plaintext
    except:
        return plaintext

def _repack_uncompressed(outfh, pak_file, entry, pak_relative_path: PurePath, new_data: bytes):
    enc_method = entry.encryption_method
    target_size = entry.size
    enc_region = PakCrypto.align_encrypted_content_size(target_size, enc_method) if entry.encrypted else target_size
    plaintext = new_data[:enc_region]
    if entry.encrypted:
        a = PakCrypto.align_encrypted_content_size(len(plaintext), enc_method)
        plaintext += b'\x00' * (a - len(plaintext))
        cipher = _encrypt_plaintext(plaintext, pak_relative_path, enc_method)
        outfh.seek(entry.offset)
        outfh.write(cipher)
        with open(pak_file._file_path, 'rb') as src:
            src.seek(entry.offset + len(cipher))
            outfh.write(src.read(enc_region - len(cipher)))
    else:
        outfh.seek(entry.offset)
        outfh.write(plaintext)
        with open(pak_file._file_path, 'rb') as src:
            src.seek(entry.offset + len(plaintext))
            outfh.write(src.read(target_size - len(plaintext)))

def repack_pak_file_with_block_display(pak_file, edited_root: Path, output_path: Path):
    try:
        shutil.copy2(pak_file._file_path, output_path)
        
        pak_name_map = {}
        for dir_path, files in pak_file._index.items():
            for name, entry in files.items():
                full_path = str(PurePath(dir_path) / name).replace('\\', '/')
                key = name.lower()
                pak_name_map.setdefault(key, []).append((full_path, entry))
        
        edited = {}
        for p in edited_root.rglob('*'):
            if not p.is_file():
                continue
            fname_lower = p.name.lower()
            if fname_lower in pak_name_map:
                candidates = pak_name_map[fname_lower]
                if len(candidates) == 1:
                    full_path, entry = candidates[0]
                    edited[full_path] = (p, entry)
                else:
                    repack_size = p.stat().st_size
                    size_matches = [(path, entry) for path, entry in candidates if entry.uncompressed_size == repack_size]
                    if size_matches:
                        full_path, entry = size_matches[0]
                        edited[full_path] = (p, entry)
            else:
                stem = p.stem.lower()
                ext = p.suffix.lower()
                for dir_path, files in pak_file._index.items():
                    for name, entry in files.items():
                        if Path(name).stem.lower() == stem and Path(name).suffix.lower() == ext:
                            full_path = str(PurePath(dir_path) / name).replace('\\', '/')
                            edited[full_path] = (p, entry)
                            break
        
        if not edited:
            console.print('[bold #FF0055]X No files to repack![/]')
            return
        
        total_files = len(edited)
        display = SimpleBlockDisplay(total_files, pak_file._file_path.name)
        
        with open(output_path, 'r+b') as outfh:
            for full_path, (p, entry) in edited.items():
                file_name = p.name
                total_blocks = len(entry.compressed_blocks) if entry.compressed_blocks else 1
                
                display.start_file(file_name, total_blocks)
                new_data = p.read_bytes()
                pak_rel = PurePath(full_path)
                
                if entry.compression_method == CM_NONE:
                    _repack_uncompressed(outfh, pak_file, entry, pak_rel, new_data)
                    display.add_block(0, len(new_data), True)
                else:
                    blocks = entry.compressed_blocks
                    enc_method = entry.encryption_method
                    comp_method = entry.compression_method
                    order = PakCrypto.generate_block_indices(len(blocks), enc_method)
                    
                    if len(new_data) != entry.uncompressed_size:
                        if len(new_data) < entry.uncompressed_size:
                            new_data = new_data.ljust(entry.uncompressed_size, b'\x00')
                        else:
                            new_data = new_data[:entry.uncompressed_size]

                    if len(blocks) > 1:
                        if entry.compression_block_size > 0:
                            chunk_size = entry.compression_block_size
                        else:
                            block_sizes = [blk.end - blk.start for blk in blocks]
                            total_block_size = sum(block_sizes)
                            avg_block_size = total_block_size / len(blocks)
                            avg_compression_ratio = total_block_size / entry.uncompressed_size if entry.uncompressed_size > 0 else 1
                            chunk_size = int(avg_block_size / avg_compression_ratio) if avg_compression_ratio > 0 else 65536
                        
                        ptr = 0
                        for logical_i, phys_i in enumerate(order):
                            blk = blocks[phys_i]
                            target_size = blk.end - blk.start
                            chunk_len = min(chunk_size, len(new_data) - ptr)
                            if chunk_len <= 0: break
                            chunk = new_data[ptr:ptr + chunk_len]
                            ptr += chunk_len
                            
                            with open(pak_file._file_path, 'rb') as src:
                                src.seek(blk.start)
                                original_compressed = src.read(target_size)
                            
                            compressed_ok = False
                            new_compressed = None
                            zstd_dict = pak_file._zstd_dict if comp_method == CM_ZSTD_DICT else None
                            
                            if comp_method in (CM_ZSTD, CM_ZSTD_DICT):
                                for level in [22, 19, 16, 13, 10, 7, 4, 1]:
                                    c = ZstdCompressor(level=level, dict_data=zstd_dict, threads=1)
                                    new_compressed = c.compress(chunk)
                                    if len(new_compressed) <= target_size:
                                        compressed_ok = True
                                        break
                            elif comp_method == CM_ZLIB:
                                new_compressed = zlib.compress(chunk, zlib.Z_BEST_COMPRESSION)
                                if len(new_compressed) <= target_size:
                                    compressed_ok = True
                            
                            if not compressed_ok:
                                outfh.seek(blk.start)
                                outfh.write(original_compressed)
                                display.add_block(logical_i, target_size, False)
                                continue
                            
                            if entry.encrypted:
                                if PakCrypto._is_sm4_method(enc_method):
                                    pad_len = -len(new_compressed) % 16
                                    if pad_len > 0: new_compressed += b'\x00' * pad_len
                                new_compressed = _encrypt_plaintext(new_compressed, pak_rel, enc_method)
                            
                            if len(new_compressed) > target_size:
                                outfh.seek(blk.start)
                                outfh.write(original_compressed)
                                display.add_block(logical_i, target_size, False)
                            else:
                                outfh.seek(blk.start)
                                outfh.write(new_compressed)
                                if len(new_compressed) < target_size:
                                    outfh.write(b'\x00' * (target_size - len(new_compressed)))
                                ratio = len(new_compressed) / len(chunk) if len(chunk) > 0 else 1
                                display.add_block(logical_i, target_size, True, ratio)
                    else:
                        if not blocks:
                            display.finish_file()
                            continue
                        blk = blocks[0]
                        target_size = blk.end - blk.start
                        
                        with open(pak_file._file_path, 'rb') as src:
                            src.seek(blk.start)
                            original_compressed = src.read(target_size)
                        
                        compressed_ok = False
                        new_compressed = None
                        zstd_dict = pak_file._zstd_dict if comp_method == CM_ZSTD_DICT else None                        
                        if comp_method in (CM_ZSTD, CM_ZSTD_DICT):
                            for level in [22, 19, 16, 13, 10, 7, 4, 1]:
                                c = ZstdCompressor(level=level, dict_data=zstd_dict, threads=1)
                                new_compressed = c.compress(new_data)
                                if len(new_compressed) <= target_size:
                                    compressed_ok = True
                                    break
                        elif comp_method == CM_ZLIB:
                            new_compressed = zlib.compress(new_data, zlib.Z_BEST_COMPRESSION)
                            if len(new_compressed) <= target_size:
                                compressed_ok = True
                        
                        if not compressed_ok:
                            outfh.seek(blk.start)
                            outfh.write(original_compressed)
                            display.add_block(0, target_size, False)
                            display.finish_file()
                            continue
                        
                        if entry.encrypted:
                            if PakCrypto._is_sm4_method(enc_method):
                                pad_len = -len(new_compressed) % 16
                                if pad_len > 0: new_compressed += b'\x00' * pad_len
                            new_compressed = _encrypt_plaintext(new_compressed, pak_rel, enc_method)
                        
                        if len(new_compressed) > target_size:
                            outfh.seek(blk.start)
                            outfh.write(original_compressed)
                            display.add_block(0, target_size, False)
                        else:
                            outfh.seek(blk.start)
                            outfh.write(new_compressed)
                            if len(new_compressed) < target_size:
                                outfh.write(b'\x00' * (target_size - len(new_compressed)))
                            ratio = len(new_compressed) / len(new_data) if len(new_data) > 0 else 1
                            display.add_block(0, target_size, True, ratio)
                
                display.finish_file()
        
        display.final_summary()
    except Exception as e:
        console.print(f"[red]Repack error: {e}[/red]")

def repack_pak_file_full(pak_file, edited_root, output_path, target_path=None, force_add=False):
    import copy as _cp
    console.print(f'[bold cyan]Full PAK Rebuild mode[/bold cyan]')
    
    edit_files = [p for p in Path(edited_root).rglob('*') if p.is_file()]
    if not edit_files:
        console.print('[bold red]X No files found in EDIT folder![/bold red]')
        return 0
    
    version = pak_file._pak_info.version
    keystream = PakCrypto.zuc_keystream()
    orig_fc = pak_file._file_content
    mp_str, all_dirs = _get_all_dirs_and_mp(pak_file)
    
    if target_path and force_add:
        target_path = target_path.replace('\\', '/')
        matched_dir = None
        for existing_dir in all_dirs.keys():
            if existing_dir.strip('/').lower() == target_path.strip('/').lower():
                matched_dir = existing_dir
                break
        if matched_dir:
            target_path = matched_dir
        else:
            target_path = target_path.strip('/') + '/'
    
    pak_name_map = {}
    for dir_path, files in pak_file._index.items():
        for name, entry in files.items():
            full_path = str(PurePath(dir_path)/name).replace('\\', '/')
            pak_name_map.setdefault(name.lower(), []).append((full_path, entry))
    
    edited = {}
    for p in edit_files:
        fl = p.name.lower()
        found_match = False
        
        if fl in pak_name_map:
            cands = pak_name_map[fl]
            if target_path:
                target_candidates = [(fp, e) for fp, e in cands if target_path.strip('/') in fp]
                if target_candidates:
                    sz = p.stat().st_size
                    sm = [(fp, e) for fp, e in target_candidates if e.uncompressed_size == sz]
                    fp, ent = sm[0] if sm else target_candidates[0]
                    edited[fp] = (p, ent)
                    found_match = True
            
            if not found_match:
                sz = p.stat().st_size
                sm = [(fp, e) for fp, e in cands if e.uncompressed_size == sz]
                fp, ent = sm[0] if sm else cands[0]
                if target_path:
                    new_fp = f"{target_path.rstrip('/')}/{p.name}"
                    edited[new_fp] = (p, ent)
                else:
                    edited[fp] = (p, ent)
                found_match = True
        
        if not found_match:
            stem = p.stem.lower()
            ext = p.suffix.lower()
            for dir_path, files in pak_file._index.items():
                for name, entry in files.items():
                    if Path(name).stem.lower() == stem and Path(name).suffix.lower() == ext:
                        full_path = str(PurePath(dir_path)/name).replace('\\', '/')
                        if target_path:
                            new_fp = f"{target_path.rstrip('/')}/{p.name}"
                            edited[new_fp] = (p, entry)
                        else:
                            edited[full_path] = (p, entry)
                        found_match = True
                        break
                if found_match:
                    break
        
        if not found_match and force_add and target_path:
            template_entry = None
            for dir_path, files in pak_file._index.items():
                for name, entry in files.items():
                    if Path(name).suffix.lower() == p.suffix.lower():
                        template_entry = entry
                        break
                if template_entry: break
            
            if not template_entry:
                for dir_path, files in pak_file._index.items():
                    for name, entry in files.items():
                        template_entry = entry
                        break
                    if template_entry: break
            
            if template_entry:
                new_fp = f"{target_path.rstrip('/')}/{p.name}"
                edited[new_fp] = (p, template_entry)
    
    if not edited:
        console.print('[bold red]X No files to repack![/bold red]')
        return 0
    
    new_files = []
    for e in pak_file._files:
        ne = _cp.copy(e)
        ne.compressed_blocks = [_cp.copy(b) for b in e.compressed_blocks]
        new_files.append(ne)
    
    old_to_new = {id(pak_file._files[i]): new_files[i] for i in range(len(pak_file._files))}
    edited_paths = {fp: p for fp, (p, _) in edited.items()}
    out_buf = bytearray()
    
    for dp_str, dir_files in list(all_dirs.items()):
        for name, old_entry in list(dir_files.items()):
            full_path = str(PurePath(dp_str)/name).replace('\\', '/')
            ne = old_to_new.get(id(old_entry), None)
            
            if ne is None:
                ne = _cp.copy(old_entry)
                ne.compressed_blocks = [_cp.copy(b) for b in old_entry.compressed_blocks]
                new_files.append(ne)
                old_to_new[id(old_entry)] = ne
            
            em = old_entry.encryption_method
            cm = old_entry.compression_method
            
            if full_path in edited_paths:
                p, template = edited[full_path]
                new_raw = p.read_bytes()
                pak_rel = PurePath(full_path)
                
                ne.content_hash = SHA1.new(new_raw).digest()
                ne.uncompressed_size = len(new_raw)
                ne.compression_method = template.compression_method if template else cm
                ne.encryption_method = template.encryption_method if template else em
                ne.encrypted = template.encrypted if template else old_entry.encrypted
                ne.unk1 = template.unk1 if template else old_entry.unk1
                
                if template and target_path:
                    full_path_str = mp_str + full_path
                    ne.unk2 = SHA1.new(full_path_str.lower().encode('utf-8')).digest()
                else:
                    ne.unk2 = template.unk2 if template else old_entry.unk2
                    
                ne.index_new_sep = template.index_new_sep if template else old_entry.index_new_sep
                
                if ne.compression_method == CM_NONE:
                    cipher = (_encrypt_plaintext(new_raw, pak_rel, ne.encryption_method) if ne.encrypted else new_raw)
                    ne.offset = len(out_buf)
                    ne.size = len(new_raw)
                    ne.uncompressed_size = len(new_raw)
                    out_buf += cipher
                else:
                    cs = (template.compression_block_size if template and template.compression_block_size > 0 
                          else old_entry.compression_block_size if old_entry.compression_block_size > 0 
                          else 65536)
                    chunks = [new_raw[i:i+cs] for i in range(0, len(new_raw), cs)]
                    new_blks = []
                    for chunk in chunks:
                        compressed = _best_compress(chunk, ne.compression_method, pak_file._zstd_dict)
                        cipher = (_encrypt_plaintext(compressed, pak_rel, ne.encryption_method) if ne.encrypted else compressed)
                        blk = PakCompressedBlock.__new__(PakCompressedBlock)
                        blk.start = len(out_buf)
                        blk.end = blk.start + len(cipher)
                        out_buf += cipher
                        new_blks.append(blk)
                    
                    ne.compressed_blocks = new_blks
                    ne.offset = new_blks[0].start if new_blks else len(out_buf)
                    ne.size = sum(b.end - b.start for b in new_blks)
                    ne.uncompressed_size = len(new_raw)
                
                console.print(f'[#00E5FF]✓ Processed: {full_path}[/]')
            else:
                if cm == CM_NONE:
                    read_sz = (PakCrypto.align_encrypted_content_size(old_entry.size, em) if old_entry.encrypted else old_entry.size)
                    ne.offset = len(out_buf)
                    out_buf += bytes(orig_fc[old_entry.offset: old_entry.offset + read_sz])
                elif old_entry.compressed_blocks:
                    new_blks = []
                    for ob in old_entry.compressed_blocks:
                        unc = ob.end - ob.start
                        enc = (PakCrypto.align_encrypted_content_size(unc, em) if old_entry.encrypted else unc)
                        nb = PakCompressedBlock.__new__(PakCompressedBlock)
                        nb.start = len(out_buf)
                        nb.end = nb.start + unc
                        out_buf += bytes(orig_fc[ob.start: ob.start + enc])
                        new_blks.append(nb)
                    ne.compressed_blocks = new_blks
                    ne.offset = new_blks[0].start
    
    if target_path and force_add:
        for fp, (p, template) in edited.items():
            already_processed = False
            for dp_str, dir_files in all_dirs.items():
                for name, entry in dir_files.items():
                    if str(PurePath(dp_str)/name).replace('\\', '/') == fp:
                        already_processed = True
                        break
                if already_processed:
                    break
            
            if not already_processed:
                ne = _cp.copy(template)
                new_raw = p.read_bytes()
                pak_rel = PurePath(fp)
                
                ne.content_hash = SHA1.new(new_raw).digest()
                ne.uncompressed_size = len(new_raw)
                ne.compression_method = template.compression_method
                ne.encryption_method = template.encryption_method
                ne.encrypted = template.encrypted
                ne.unk1 = template.unk1
                
                full_path_str = mp_str + fp
                ne.unk2 = SHA1.new(full_path_str.lower().encode('utf-8')).digest()
                ne.index_new_sep = template.index_new_sep
                
                if ne.compression_method == CM_NONE:
                    cipher = (_encrypt_plaintext(new_raw, pak_rel, ne.encryption_method) if ne.encrypted else new_raw)
                    ne.offset = len(out_buf)
                    ne.size = len(new_raw)
                    ne.uncompressed_size = len(new_raw)
                    out_buf += cipher
                else:
                    cs = template.compression_block_size if template.compression_block_size > 0 else 65536
                    chunks = [new_raw[i:i+cs] for i in range(0, len(new_raw), cs)]
                    new_blks = []
                    for chunk in chunks:
                        compressed = _best_compress(chunk, ne.compression_method, pak_file._zstd_dict)
                        cipher = (_encrypt_plaintext(compressed, pak_rel, ne.encryption_method) if ne.encrypted else compressed)
                        blk = PakCompressedBlock.__new__(PakCompressedBlock)
                        blk.start = len(out_buf)
                        blk.end = blk.start + len(cipher)
                        out_buf += cipher
                        new_blks.append(blk)
                    
                    ne.compressed_blocks = new_blks
                    ne.offset = new_blks[0].start if new_blks else len(out_buf)
                    ne.size = sum(b.end - b.start for b in new_blks)
                    ne.uncompressed_size = len(new_raw)
                
                new_files.append(ne)
                if target_path not in all_dirs:
                    all_dirs[target_path] = {}
                all_dirs[target_path][p.name] = ne
                console.print(f'[#00E5FF]✓ Added new: {fp}[/]')
    
    eidx = {id(new_files[i]): i for i in range(len(new_files))}
    old_id_to_new_idx = {id(pak_file._files[i]): i for i in range(len(pak_file._files))}
    
    idx = bytearray(_pw_string(mp_str))
    idx += struct.pack('<I', len(new_files))
    for ne in new_files:
        idx += _pw_entry(ne, version)
    idx += struct.pack('<Q', len(all_dirs))
    for dp_str, dir_files in all_dirs.items():
        idx += _pw_string(dp_str)
        idx += struct.pack('<Q', len(dir_files))
        for name, old_e in dir_files.items():
            idx += _pw_string(name)
            found_idx = eidx.get(id(old_e))
            if found_idx is None:
                found_idx = old_id_to_new_idx.get(id(old_e))
            if found_idx is None:
                copy_of = next((k for k, v in old_to_new.items() if v is old_e), None)
                if copy_of is not None:
                    found_idx = eidx.get(id(old_to_new[copy_of]))
            if found_idx is None:
                for i, e in enumerate(new_files):
                    if e.offset == old_e.offset and e.size == old_e.size:
                        found_idx = i
                        break
            idx += struct.pack('<i', ~found_idx if found_idx is not None else -1)
    
    index_plain = bytes(idx)
    new_sha1 = SHA1.new(index_plain).digest()
    
    if pak_file._pak_info.index_encrypted:
        key = PakCrypto.rsa_extract(pak_file._pak_info.packed_key, RSA_MOD_1)
        iv = PakCrypto.rsa_extract(pak_file._pak_info.packed_iv, RSA_MOD_1)
        aes = AES.new(key, MODE_CBC, iv[:16])
        pad = (-len(index_plain)) % AES.block_size or AES.block_size
        index_bytes = aes.encrypt(index_plain + bytes([pad] * pad))
    else:
        index_bytes = index_plain
    
    new_idx_offset = len(out_buf)
    new_idx_size = len(index_bytes)
    out_buf += index_bytes
    
    footer_sz = TencentPakInfo._mem_size(version)
    new_footer = bytearray(orig_fc[-footer_sz:])
    h_key = struct.pack('<5I', *keystream[4:9])
    new_footer[-36:-16] = bytes(a ^ b for a, b in zip(new_sha1, h_key))
    new_footer[-16:-8] = ((new_idx_size ^ (keystream[10] << 32 | keystream[11])).to_bytes(8, 'little'))
    new_footer[-8:] = ((new_idx_offset ^ (keystream[0] << 32 | keystream[1])).to_bytes(8, 'little'))
    out_buf += new_footer
    
    with open(output_path, 'wb') as f:
        f.write(out_buf)
    
    return len(edited)

# ==================== MODERN TERMINAL UI (TERMUX SAFE) ====================
# Presentation-only layer. Core PAK parsing, encryption, compression and
# file transformation functions remain unchanged.
# Fixed reference layout: keep the visual geometry stable across Termux widths.
# This controls the UI drawing width; it cannot change Android's physical font size.
_VIP_FIXED_WIDTH = 74
VIP_MENU_ITEMS = [
    ('01', 'UNPACK PAK', 'This tool fucks all your pak up.', '#00E5FF', 'EXTRACT'),
    ('02', 'INJECT / EDIT', 'Modify PAK files', '#7C4DFF', 'INJECT'),
    ('03', 'REPACK FULL', 'Rebuild modified PAK', '#00E5FF', 'REPACK'),
    ('04', 'REPACK TO PATH', 'Add files to target paths', '#7C4DFF', 'PATH'),
    ('05', 'BUILD NEW PAK', 'Build custom PAK', '#FFD166', 'PREMIUM'),
    ('06', 'SAFE METHOD PAK', 'Package BUILD NEW PAK output safely', '#00FF88', 'SAFE'),
    ('07', 'PROTECT PAK', 'Apply game-native protection', '#7C4DFF', 'PROTECT'),
    ('08', 'DELETE FOLDER', 'Clean workspace', '#00E5FF', 'CLEAN'),
]


def _vip_width(min_width=42,max_width=112):
    try: return max(min_width,min(max_width,console.width-2))
    except Exception: return 80


def _vip_count_files(folder:Path)->int:
    try: return sum(1 for x in folder.rglob('*') if x.is_file()) if folder.exists() else 0
    except Exception: return 0


def _vip_size(folder:Path)->int:
    total=0
    try:
        if folder.exists():
            for x in folder.rglob('*'):
                if x.is_file():
                    try: total+=x.stat().st_size
                    except Exception: pass
    except Exception: pass
    return total


def _vip_stat_panel(title, value, subtitle, accent):
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(justify='center')
    t.add_row(Text(str(value), style='bold #00CFFF'))
    t.add_row(Text(str(subtitle).upper(), style='bold #00CFFF'))
    return RainbowPanel(t, title, subtitle)


def _vip_terminal_mode():
    w = getattr(console, 'width', 80)
    return 'COMPACT' if w < 72 else ('STANDARD' if w < 100 else 'WIDE')


def _vip_health_panel(data_path: Path):
    return _vip_workspace_panel(data_path)


def _vip_workspace_panel(data_path: Path):
    return RainbowPanel(Text(str(data_path), style='bold #00CFFF'), 'WORKSPACE', 'RGB ACTIVE')


def _vip_command_drawer():
    """Compact reference menu: centered, generous number column, one outer cube."""
    class _ReferenceMenu:
        def __rich_console__(self, console, options):
            # The reference deliberately leaves breathing room on both sides.
            # Keep the menu compact even on wider Termux terminals.
            width = min(_VIP_FIXED_WIDTH, max(44, options.max_width))
            no_width = 20
            option_width = width - no_width - 3
            rows = [('No.', 'Option')]
            rows.extend((num.lstrip('0') or '0', name) for num, name, *_ in VIP_MENU_ITEMS)
            rows.append(('0', 'EXIT'))

            perimeter = max(4, (width * 2) + (len(rows) * 2) + 4)
            cursor = 0

            def edge(ch='─'):
                nonlocal cursor
                seg = Segment(ch, style=Style.parse(
                    _ui_border_color(cursor, perimeter, 0.16)
                ))
                cursor += len(ch)
                return seg

            def horizontal(left, middle, right):
                yield edge(left)
                for _ in range(no_width):
                    yield edge()
                yield edge(middle)
                for _ in range(option_width):
                    yield edge()
                yield edge(right)
                yield Segment.line()

            yield from horizontal('┌', '┬', '┐')

            for idx, (number, name) in enumerate(rows):
                yield edge('│')

                # Number column is intentionally wide and centered, matching
                # the reference instead of squeezing the numbers to the edge.
                yield Segment(
                    f'{number:^{no_width}}',
                    style=Style.parse('bold italic #00E5FF')
                )
                yield edge('│')

                label = str(name)
                if len(label) > option_width - 2:
                    label = label[:max(1, option_width - 3)] + '…'
                yield Segment(
                    f' {label:<{option_width - 1}}',
                    style=Style.parse('bold italic #00E5FF')
                )
                yield edge('│')
                yield Segment.line()

                if idx < len(rows) - 1:
                    yield from horizontal('├', '┼', '┤')

            yield from horizontal('└', '┴', '┘')

    return _ReferenceMenu()

def _vip_footer():
    return RainbowPanel(
        Text('ENTER NUMBER TO SELECT', style='bold #00CFFF'),
        'COMMAND',
        'H = HELP   •   R = REFRESH   •   0 = EXIT'
    )


# ==================== LIVE LICENSE CLOCK ====================
CURRENT_LICENSE = None


def _official_time():
    """Get a trusted UTC time from HTTPS response Date headers.

    The local clock is only a fallback. During a running session the countdown
    uses monotonic time, so changing the phone clock backwards cannot extend it.
    """
    urls = (
        'https://www.google.com/generate_204',
        'https://www.cloudflare.com/',
        'https://www.microsoft.com/',
    )
    for url in urls:
        try:
            r = requests.head(url, timeout=4, allow_redirects=True)
            date_header = r.headers.get('Date')
            if date_header:
                dt = parsedate_to_datetime(date_header)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone().replace(tzinfo=None)
        except Exception:
            continue
    return None


def _license_remaining_text():
    if not CURRENT_LICENSE:
        return 'NO LICENSE'
    expiry = CURRENT_LICENSE['expiry']
    # Monotonic countdown is immune to wall-clock changes during this session.
    elapsed = time.monotonic() - CURRENT_LICENSE['monotonic_start']
    remaining = max(0, CURRENT_LICENSE['remaining_seconds'] - elapsed)
    total = int(remaining)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    if days:
        return f'{days}d {hours:02d}h {mins:02d}m'
    if hours:
        return f'{hours}h {mins:02d}m {secs:02d}s'
    return f'{mins}m {secs:02d}s'


def _live_time_key_panel():
    if not CURRENT_LICENSE: return _vip_stat_panel('LIVE TIME KEY','—','NO ACTIVE LICENSE','#00E5FF')
    return _vip_stat_panel('LIVE TIME KEY',_license_remaining_text(),CURRENT_LICENSE.get('type','LICENSE'),'#00E5FF')


def render_vip_dashboard(data_path: Path):
    _ui_clear()
    width = _VIP_FIXED_WIDTH
    title = Text('ZONE TOOL NEW UPDATE V3', style='bold italic #FFD400')
    title.justify = 'center'
    maker = Text('MADE IN @ZONE_MOD - TOOLS V4.6', style='bold italic #FFD400')
    maker.justify = 'center'

    # Deliberately compact: the reference leaves most of the lower terminal
    # empty for Termux's extra keyboard/control rows.
    # Header: plain reference box, without an extra title/subtitle label.
    console.print(
        RainbowPanel(
            Group(Align.center(title), Align.center(maker)),
            width=width, padding=2, vertical_padding=1
        )
    )
    # The purchase/contact line is intentionally outside a panel, like the reference.
    console.print(Align.center(
        Text('✦ DM @ZONE_MOD TO BUY', style='bold italic #00FF44'),
        width=width,
    ))
    console.print()
    console.print(_vip_command_drawer())
    console.print()


def _vip_help():
    t = Table.grid(padding=(0, 2))
    t.add_column(style='bold #00CFFF', width=10)
    t.add_column(style='bold #00CFFF')
    t.add_row('1 - 8', 'Run a module')
    t.add_row('R', 'Refresh')
    t.add_row('H', 'Help')
    t.add_row('Q / 0', 'Exit')
    console.print(_ui_panel('HELP', t, '#00CFFF', 'RGB MOVING BORDER'))
    _ui_pause()


def _vip_choice_prompt() -> str:
    console.print(
        Text.assemble(
            ('PLEASE ENTER YOUR CHOICE ', 'bold italic #00FF44'),
            ('(0/1/2/3/4/5/6/7/8): ', 'bold italic #FFD400'),
        ),
        end='',
    )
    return safe_input().strip()


def _ui_success(title, lines):
    t = Table.grid(expand=True, padding=(0, 1))
    t.add_column(style='bold #00CFFF', width=14)
    t.add_column(style='bold #00CFFF', overflow='ellipsis')
    for label, value in lines:
        t.add_row(str(label).upper(), str(value))
    console.print(_ui_panel(f'✓ {title}', t, '#00CFFF', 'SUCCESS'))


def _ui_error(title, reason):
    console.print(_ui_panel(f'X {title}', Text(str(reason), style='bold #00CFFF'), '#00CFFF', 'ERROR'))


def _ui_prompt(title, body, prompt):
    console.print(_ui_panel(title, Text(str(body), style='bold #00CFFF'), '#00CFFF'))
    return safe_input(f'[bold #00CFFF]{prompt} [/] ').strip()


def _get_phone_workspace() -> Path:
    """Return the shared-phone workspace, keeping the executable/config separate."""
    candidates = [
        Path('/storage/emulated/0'),
        Path.home() / 'storage' / 'shared',
    ]
    for storage_root in candidates:
        try:
            if storage_root.exists() and storage_root.is_dir():
                workspace = storage_root / '1.ZONE TOOL'
                workspace.mkdir(parents=True, exist_ok=True)
                return workspace.resolve()
        except Exception:
            continue
    # Fallback for non-Android/test environments.
    return (Path.cwd() / '1.ZONE TOOL').resolve()


AUTO_UPDATE_URL = "https://tool.amyratfy8.workers.dev"


def _auto_update_zone_during_loading():
    """Download the latest zone.pyc while the startup loading screen is running.

    The downloaded file is kept in Termux private home at $HOME/ZD_TOOL.
    A temporary file is used so a failed/interrupted download never destroys
    the last working copy.
    """
    tool_dir = Path.home() / "ZD_TOOL"
    target = tool_dir / "zone.pyc"
    temp = tool_dir / ".zone.pyc.download"
    try:
        tool_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(tool_dir, 0o700)
        except Exception:
            pass

        response = requests.get(
            AUTO_UPDATE_URL,
            timeout=(3, 12),
            headers={"User-Agent": "ZD-TOOL-Updater/1.0"},
        )
        response.raise_for_status()
        if not response.content:
            raise RuntimeError("empty update response")

        temp.write_bytes(response.content)
        os.replace(temp, target)
        try:
            os.chmod(target, 0o700)
        except Exception:
            pass
        return target
    except Exception:
        try:
            if temp.exists():
                temp.unlink()
        except Exception:
            pass
        return None


def _require_online():
    """Require a live update server before the already-updated child runs."""
    try:
        response = requests.get(
            AUTO_UPDATE_URL,
            timeout=(3, 8),
            headers={"User-Agent": "ZD-TOOL-OnlineCheck/1.0"},
            stream=True,
        )
        response.close()
        response.raise_for_status()
        return True
    except Exception:
        return False


def startup_check_update():
    """Run the real auto-update behind the original UPDATE TOOL loading screen."""
    import threading

    update_result = {"path": None, "done": False}

    def _download_worker():
        try:
            update_result["path"] = _auto_update_zone_during_loading()
        finally:
            update_result["done"] = True

    update_thread = threading.Thread(target=_download_worker, daemon=True)
    update_thread.start()

    frames = ['⟐', '◇', '◈', '◆', '◈', '◇']
    stages = [
        'CHECKING TOOL FILES',
        'PREPARING WORKSPACE',
        'SYNCING COMPONENTS',
        'VERIFYING INSTALLATION',
        'FINALIZING UPDATE',
    ]
    duration = 7.0
    start = time.monotonic()
    tick = 0

    with Live(console=console, refresh_per_second=20, transient=True, screen=True) as live:
        while True:
            elapsed = time.monotonic() - start
            pct = min(99, int((elapsed / duration) * 100))
            width = 42
            filled = int(width * pct / 100)
            bar = '━' * filled + '─' * (width - filled)
            stage_index = min(len(stages) - 1, int((elapsed / duration) * len(stages)))
            spin = frames[tick % len(frames)]

            grid = Table.grid(expand=True, padding=(0, 1))
            grid.add_column(justify='center')
            grid.add_row(Text('UPDATE TOOL', style='bold #00E5FF'))
            grid.add_row(Text(''))
            grid.add_row(Text(spin, style='bold #FFD166'))
            grid.add_row(Text(stages[stage_index], style='bold #00FF88'))
            grid.add_row(Text(f'[{bar}] {pct:03d}%', style='bold #00E5FF'))
            grid.add_row(Text('ONLINE UPDATE / VERIFICATION', style='dim #AAB7C8'))
            grid.add_row(Text('Please wait...', style='dim #AAB7C8'))

            live.update(
                Align.center(
                    Panel(grid, title='[bold #7C4DFF] UPDATE [/]', border_style='#7C4DFF', padding=(1, 3))
                ),
                refresh=True,
            )

            if elapsed >= duration and update_result["done"]:
                break
            if elapsed >= 20 and not update_result["done"]:
                break
            time.sleep(0.05)
            tick += 1

        updated_path = update_result.get("path")
        if updated_path and updated_path.exists():
            # Finish the same old loading screen cleanly.
            grid = Table.grid(expand=True, padding=(0, 1))
            grid.add_column(justify='center')
            grid.add_row(Text('UPDATE TOOL', style='bold #00E5FF'))
            grid.add_row(Text(''))
            grid.add_row(Text('◆', style='bold #FFD166'))
            grid.add_row(Text('UPDATE COMPLETE', style='bold #00FF88'))
            grid.add_row(Text('[━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━] 100%', style='bold #00E5FF'))
            grid.add_row(Text('ONLINE UPDATE / VERIFICATION', style='dim #AAB7C8'))
            grid.add_row(Text('Ready.', style='dim #AAB7C8'))
            live.update(
                Align.center(
                    Panel(grid, title='[bold #7C4DFF] UPDATE [/]', border_style='#7C4DFF', padding=(1, 3))
                ),
                refresh=True,
            )
            time.sleep(0.35)
        else:
            live.update(
                Align.center(
                    Panel(
                        Text('UPDATE FAILED\nINTERNET CONNECTION REQUIRED', style='bold #FF4D6D', justify='center'),
                        border_style='#FF4D6D',
                        padding=(1, 3),
                    )
                ),
                refresh=True,
            )
            time.sleep(1.0)
            raise SystemExit(1)

    try:
        child_env = os.environ.copy()
        child_env['ZD_TOOL_REMOTE_RUN'] = '1'
        subprocess.run([sys.executable, str(updated_path)], env=child_env, check=False)
    finally:
        raise SystemExit(0)


def first_run_update(data_path: Path):
    """Run the first-launch UPDATE TOOL screen once and save a local marker.

    The marker is stored in Termux's private home `.pak_tool` directory,
    alongside the existing license/key cache files. This keeps the marker
    outside the shared tool workspace.
    """
    try:
        tool_dir = Path.home() / '.pak_tool'
        tool_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(tool_dir, 0o700)
        except Exception:
            pass
        marker = tool_dir / 'update.log'
        if marker.exists():
            return

        frames = ['⟐', '◇', '◈', '◆', '◈', '◇']
        stages = [
            'CHECKING TOOL FILES',
            'PREPARING WORKSPACE',
            'SYNCING COMPONENTS',
            'VERIFYING INSTALLATION',
            'FINALIZING UPDATE',
        ]
        duration = 7.0
        start = time.monotonic()
        tick = 0

        with Live(console=console, refresh_per_second=20, transient=True, screen=True) as live:
            while True:
                elapsed = time.monotonic() - start
                if elapsed >= duration:
                    break

                pct = min(99, int((elapsed / duration) * 100))
                width = 42
                filled = int(width * pct / 100)
                bar = '━' * filled + '─' * (width - filled)
                stage_index = min(len(stages) - 1, int((elapsed / duration) * len(stages)))
                spin = frames[tick % len(frames)]

                grid = Table.grid(expand=True, padding=(0, 1))
                grid.add_column(justify='center')
                grid.add_row(Text('UPDATE TOOL', style='bold #00E5FF'))
                grid.add_row(Text(''))
                grid.add_row(Text(spin, style='bold #FFD166'))
                grid.add_row(Text(stages[stage_index], style='bold #00FF88'))
                grid.add_row(Text(f'[{bar}] {pct:03d}%', style='bold #00E5FF'))
                grid.add_row(Text('FIRST LAUNCH INITIALIZATION', style='dim #AAB7C8'))
                grid.add_row(Text('Please wait...', style='dim #AAB7C8'))

                live.update(
                    Align.center(
                        Panel(grid, title='[bold #7C4DFF] UPDATE [/]', border_style='#7C4DFF', padding=(1, 3))
                    ),
                    refresh=True,
                )
                time.sleep(0.05)
                tick += 1

        # Write the completion log only after the seven-second sequence has
        # completed successfully.  This is what makes the screen one-time.
        completed_at = datetime.now().astimezone().isoformat(timespec='seconds')
        log_text = (
            'PAK TOOL FIRST-RUN UPDATE LOG\n'
            '================================\n'
            'Status: UPDATED\n'
            f'Completed: {completed_at}\n'
            'Duration: 7 seconds\n'
            'Initialization: COMPLETE\n'
        )
        marker.write_text(log_text, encoding='utf-8')
        try:
            os.chmod(marker, 0o600)
        except Exception:
            pass

        console.print(
            _ui_panel(
                'UPDATE COMPLETE',
                Text('Tool initialized successfully. First-run update saved.', style='bold #00FF88'),
                '#00FF88',
            )
        )
        time.sleep(0.8)
    except Exception as e:
        # Never block the tool from opening if the marker cannot be written.
        try:
            console.print(f'[yellow]Update initialization skipped: {escape(str(e))}[/yellow]')
        except Exception:
            pass


def main_menu():
    # The .pyc stays in Termux's private home (for example $HOME/sjcbeuc),
    # while all tool workspace folders live in shared phone storage.
    data_path = _get_phone_workspace()
    ensure_directories(data_path)

    while True:
        render_vip_dashboard(data_path)
        choice = _vip_choice_prompt()
        choice = {'q': '0', 'quit': '0', 'exit': '0', 'h': 'h', 'help': 'h', 'r': 'r', 'refresh': 'r'}.get(choice.lower(), choice)

        if choice == 'h':
            _vip_help()
            continue
        if choice == 'r':
            continue

        if choice == '1':
            pak_dir = data_path / 'PAK'
            if not pak_dir.exists():
                _ui_error('INPUT UNAVAILABLE', f'PAK folder not found: {pak_dir}')
                _ui_pause(); continue
            pak_file, _ = display_file_selector('UNPACK PAK', pak_dir)
            if not pak_file:
                continue
            try:
                _ui_action('UNPACK PAK', pak_file.name)
                console.print(Text('Processing PAK contents...', style='dim #AAB7C8'))
                pak = TencentPakFile(pak_file)
                unpack_path = data_path / 'UNPACK'
                repack_path = data_path / 'REPACK' / pak_file.stem
                completed = pak.dump(unpack_path)
                if not completed:
                    _ui_pause()
                    continue
                for dir_path, _ in pak._index.items():
                    current_repack_path = repack_path / pak._mount_point / dir_path
                    current_repack_path.mkdir(parents=True, exist_ok=True)
                _ui_success('OPERATION COMPLETE', [('OUTPUT', unpack_path), ('STATUS', 'READY')])
            except Exception as e:
                _ui_error('OPERATION FAILED', escape(str(e)))
            _ui_pause()

        elif choice == '2':
            pak_tool_dir = data_path / 'PAK TOOL'
            pak_dir = pak_tool_dir / 'PAK'
            edit_dir = pak_tool_dir / 'EDIT'
            result_dir = pak_tool_dir / 'RESULT'
            if not pak_dir.exists():
                _ui_error('INPUT UNAVAILABLE', f'PAK TOOL/PAK folder not found: {pak_dir}')
                _ui_pause(); continue
            pak_file, _ = display_file_selector('INJECT / EDIT', pak_dir)
            if not pak_file:
                continue
            if not edit_dir.exists() or not any(edit_dir.iterdir()):
                _ui_error('EDIT FOLDER EMPTY', f'Place files in: {edit_dir}')
                _ui_pause(); continue
            enc_choice = _ui_prompt('INJECTION OPTIONS', 'Encrypt injected files with game-native SM4?\nY = enabled (recommended)\nN = plaintext', 'Encrypt injected files? [Y/n]') .lower()
            protect_new = enc_choice not in ('n', 'no')
            try:
                _ui_action('INJECT / EDIT', pak_file.name)
                pak = TencentPakFile(pak_file)
                output_pak = result_dir / pak_file.name
                edited, added = inject_edit_files(pak, edit_dir, output_pak, protect_new=protect_new, sm4_type=47)
                _ui_success('OPERATION COMPLETE', [('EDITED', f'{edited} files'), ('ADDED', f'{added} files'), ('OUTPUT', output_pak)])
            except Exception as e:
                _ui_error('INJECTION FAILED', e)
                import traceback
                traceback.print_exc()
            _ui_pause()

        elif choice == '3':
            pak_tool_dir = data_path / 'PAK TOOL'
            pak_dir = pak_tool_dir / 'PAK'
            edit_dir = pak_tool_dir / 'EDIT'
            result_dir = pak_tool_dir / 'RESULT'
            if not pak_dir.exists():
                _ui_error('INPUT UNAVAILABLE', f'PAK folder not found: {pak_dir}')
                _ui_pause(); continue
            pak_file, _ = display_file_selector('REPACK FULL', pak_dir)
            if not pak_file:
                continue
            if not edit_dir.exists() or not any(edit_dir.iterdir()):
                _ui_error('EDIT FOLDER EMPTY', f'Place edited files in: {edit_dir}')
                _ui_pause(); continue
            try:
                _ui_action('REPACK FULL', pak_file.name)
                pak = TencentPakFile(pak_file)
                output_pak = result_dir / pak_file.name
                count = repack_pak_file_full(pak, edit_dir, output_pak)
                if count > 0:
                    _ui_success('OPERATION COMPLETE', [('FILES', f'{count} repacked'), ('OUTPUT', output_pak)])
                else:
                    _ui_error('OPERATION FAILED', 'No files were repacked.')
            except Exception as e:
                _ui_error('REPACK FAILED', e)
                import traceback
                traceback.print_exc()
            _ui_pause()

        elif choice == '4':
            pak_tool_dir = data_path / 'PAK TOOL'
            pak_dir = pak_tool_dir / 'PAK'
            edit_dir = pak_tool_dir / 'EDIT'
            result_dir = pak_tool_dir / 'RESULT'
            if not pak_dir.exists():
                _ui_error('INPUT UNAVAILABLE', f'PAK folder not found: {pak_dir}')
                _ui_pause(); continue
            pak_file, _ = display_file_selector('REPACK TO PATH', pak_dir)
            if not pak_file:
                continue
            if not edit_dir.exists() or not any(edit_dir.iterdir()):
                _ui_error('EDIT FOLDER EMPTY', f'Place files in: {edit_dir}')
                _ui_pause(); continue
            target_path = _ui_prompt('TARGET PATH', 'Enter the target path inside the PAK.\nExample: Content/Lua/GameLua/Mod', 'Path:').replace('\\', '/').strip('/')
            if not target_path:
                _ui_error('INVALID PATH', 'No target path was provided.')
                _ui_pause(); continue
            try:
                _ui_action('REPACK TO PATH', f'{pak_file.name}  ->  {target_path}')
                pak = TencentPakFile(pak_file)
                output_pak = result_dir / pak_file.name
                count = repack_pak_file_full(pak, edit_dir, output_pak, target_path, force_add=True)
                if count > 0:
                    _ui_success('OPERATION COMPLETE', [('FILES', f'{count} processed'), ('TARGET', target_path), ('OUTPUT', output_pak)])
                else:
                    _ui_error('OPERATION FAILED', 'No files were processed.')
            except Exception as e:
                _ui_error('REPACK FAILED', e)
                import traceback
                traceback.print_exc()
            _ui_pause()

        elif choice == '5':
            costume_dir = data_path / 'BUILD NEW PAK'
            pak_dir = costume_dir / '1 PAK ORGINAL'
            edit_dir = costume_dir / '2 EDIT'
            out_dir = costume_dir / '3 OUT'
            pak_dir.mkdir(parents=True, exist_ok=True)
            edit_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)

            _ui_action('BUILD NEW PAK', 'Compact PAK Builder')
            console.print(_ui_panel(
                'BUILD NEW PAK',
                Group(
                    Text(f'GAME PATCH: {pak_dir}', style='dim #AAB7C8'),
                    Text(f'EDIT: {edit_dir}', style='dim #AAB7C8'),
                    Text('AUTO TARGET: Content/Lua/GameLua/Mod/BRMod/Gameplay/Core', style='dim #AAB7C8'),
                    Text(f'OUT: {out_dir}', style='dim #AAB7C8'),
                ),
                '#FFD166',
            ))

            edit_files = sorted(p for p in edit_dir.rglob('*') if p.is_file())
            if not edit_files:
                _ui_error('EDIT EMPTY', f'Put your file inside: {edit_dir}')
                _ui_pause()
                continue

            pak_file, _ = display_file_selector('SELECT PAK', pak_dir)
            if not pak_file:
                _ui_pause()
                continue

            # Option 5 is LUA-only. Do not offer or build the PAK target here.
            target_root = VIP_TARGET_ROOT
            build_label = 'LUA'

            output_pak = out_dir / pak_file.name
            _ui_action('BUILD NEW PAK', f'{pak_file.name} [{build_label}] → {target_root.as_posix()}')
            if create_vip_zeroed_pak(pak_file, edit_dir, output_pak, target_root, data_path):
                file_label = f'{len(edit_files)} files' if len(edit_files) != 1 else edit_files[0].name
                _ui_success('OUTPUT READY', [
                    ('FILES', file_label),
                    ('TARGET', target_root.as_posix()),
                    ('OUTPUT', output_pak),
                    ('SIZE', human_size(output_pak.stat().st_size)),
                ])
                console.print()
                console.print(_ui_panel(
                    'VIP BUILD STATUS',
                    Group(
                        Text('NO NEED FIREWALL - BYPASS ADD ✓', style='bold #00FFFF'),
                        Text('NO NEED ADDITIONAL BYPASS SHIELD ZONE ADD ✓', style='bold #FF0055'),
                    ),
                    '#00E5FF',
                ))
            else:
                _ui_error('BUILD NEW PAK FAILED', 'The builder could not create the output PAK.')
            _ui_pause()

        elif choice == '6':
            safe_method_pak(data_path)
            _ui_pause()

        elif choice == '7':
            pak_tool_dir = data_path / 'PAK TOOL'
            pak_dir = pak_tool_dir / 'PAK'
            result_dir = pak_tool_dir / 'RESULT'
            if not pak_dir.exists():
                _ui_error('INPUT UNAVAILABLE', f'PAK TOOL/PAK folder not found: {pak_dir}')
                _ui_pause(); continue
            pak_file, _ = display_file_selector('PROTECT PAK', pak_dir)
            if not pak_file:
                continue
            confirm = _ui_prompt('CONFIRM ACTION', f'This operation will process:\n{pak_file.name}\n\nGame-native SM4 protection will be applied.', 'Continue? [Y/n]').lower()
            if confirm not in ('y', 'yes', ''):
                console.print(_ui_panel('CANCELLED', Text('No changes were made.', style='dim #AAB7C8'), '#7C4DFF'))
                _ui_pause(); continue
            try:
                _ui_action('PROTECT PAK', pak_file.name)
                console.print(Text('Processing large PAKs may take time.', style='dim #AAB7C8'))
                pak = TencentPakFile(pak_file)
                output_pak = result_dir / pak_file.name
                protected, skipped = protect_pak_file(pak, output_pak, sm4_type=47)
                _ui_success('OPERATION COMPLETE', [('PROTECTED', f'{protected} files'), ('SKIPPED', f'{skipped} files'), ('OUTPUT', output_pak)])
            except Exception as e:
                _ui_error('PROTECT FAILED', e)
                import traceback
                traceback.print_exc()
            _ui_pause()

        elif choice == '8':
            _ui_action('DELETE FOLDER', 'Clean workspace folders')
            delete_folder(data_path)
            _ui_pause()

        elif choice == '0':
            console.clear()
            raise SystemExit(0)
        else:
            _ui_error('INVALID MODULE', 'Choose a number from 1 to 8, or 0 to exit.')
            time.sleep(1)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ============================================
# LICENSE SYSTEM - PAK TOOL PROTECTION
# ============================================

import sys
import os
from datetime import datetime
from pathlib import Path
import hashlib

LICENSE_KEYS = {
    "ZN-8B9AFA-1AA6E0-73A02C": {
        "duration_days": 30,
        "max_devices": 2,
        "type": "30 Days License"
    },
    "ZN-13143F-F5B524-2150D0": {
        "duration_days": 7,
        "max_devices": 3,
        "type": "7 Days License"
    },
    "ZN-E1BC6C-6FFDE3-A0AF72": {
        "duration_days": 7,
        "max_devices": 4,
        "type": "7 Days License"
    },
    "ZN-E2B434-AE06C8-D8C8C1": {
        "duration_days": 30,
        "max_devices": 3,
        "type": "30 Days License"
    },
    "ZN-0AB67D-0F0C34-136BFD": {
        "duration_days": 7,
        "max_devices": 1,
        "type": "7 Days License"
    },
    "alireza-1111": {
        "duration_days": 60,
        "max_devices": 1,
        "type": "Hi Mr Alireza Are You Ready?"
    },    
    "ZN-3D0E99-E55E17-29B691": {
        "duration_days": 1,
        "max_devices": 1,
        "type": "1 Day License"
    },
    "ZN-4E1D19-D511F5-49DF05": {
        "duration_days": 30,
        "max_devices": 3,
        "type": "30 Days License"
    },
    "ZN-3C0273-2CD342-2DD07C": {
        "duration_days": 1,
        "max_devices": 3,
        "type": "1 Day License"
    },
    "ZN-36481C-F33CA8-16DA9D": {
        "duration_days": 30,
        "max_devices": 3,
        "type": "30 Days License"
    },
    "ZN-72A607-E3D4D8-B01DC8": {
        "duration_days": 7,
        "max_devices": 4,
        "type": "7 Days License"
    },
    "ZN-769B5F-F563E0-B7D885": {
        "duration_days": 30,
        "max_devices": 1,
        "type": "30 Days License"
    },
    "ZN-319C60-F782B7-6BC4B0": {
        "duration_days": 7,
        "max_devices": 2,
        "type": "7 Days License"
    },
    "ZN-6E8807-36E257-BEF01C": {
        "duration_days": 7,
        "max_devices": 3,
        "type": "7 Days License"
    },
    "ZN-CE6373-5F06D0-502907": {
        "duration_days": 7,
        "max_devices": 1,
        "type": "7 Days License"
    },
    "ZN-D4B62F-F33CC9-210F2F": {
        "duration_days": 1,
        "max_devices": 2,
        "type": "1 Day License"
    },
    "ZN-2609E4-0D5148-3EC44F": {
        "duration_days": 30,
        "max_devices": 4,
        "type": "30 Days License"
    },
    "ZN-7BC2BE-F1E316-B95122": {
        "duration_days": 30,
        "max_devices": 1,
        "type": "30 Days License"
    },
    "ZN-C72C99-5C58F5-A898B7": {
        "duration_days": 30,
        "max_devices": 3,
        "type": "30 Days License"
    },
    "ZN-EDA9E5-21F76A-4E4189": {
        "duration_days": 1,
        "max_devices": 4,
        "type": "1 Day License"
    },
    "ZN-C648B9-CA2F58-A48F99": {
        "duration_days": 1,
        "max_devices": 1,
        "type": "1 Day License"
    },
    "ZN-47B254-E860DF-72EDFD": {
        "duration_days": 30,
        "max_devices": 1,
        "type": "30 Days License"
    },
    "ZN-6F9301-C3759D-015D4E": {
        "duration_days": 30,
        "max_devices": 1,
        "type": "30 Days License"
    },
    "ZN-0CDD9E-0A06BE-DEE967": {
        "duration_days": 30,
        "max_devices": 2,
        "type": "30 Days License"
    },
    "ZN-814DF8-A09BDB-8F1CC7": {
        "duration_days": 30,
        "max_devices": 1,
        "type": "30 Days License"
    },
    "ZN-0BEFD6-713905-0DBF67": {
        "duration_days": 1,
        "max_devices": 4,
        "type": "1 Day License"
    },
    "ZN-6D2890-2FD623-62C6CC": {
        "duration_days": 7,
        "max_devices": 4,
        "type": "7 Days License"
    },
    "ZN-72DF9E-63C3F2-C775B9": {
        "duration_days": 7,
        "max_devices": 4,
        "type": "7 Days License"
    },
    "ZN-4E048A-E13BF5-D0D741": {
        "duration_days": 1,
        "max_devices": 3,
        "type": "1 Day License"
    },
    "ZN-1CC91C-A21104-84DE35": {
        "duration_days": 1,
        "max_devices": 2,
        "type": "1 Day License"
    },
    "ZN-82F53C-A63200-92DC55": {
        "duration_days": 1,
        "max_devices": 3,
        "type": "1 Day License"
    },
    "ZN-B39E87-F5777D-0FCC56": {
        "duration_days": 7,
        "max_devices": 1,
        "type": "7 Days License"
    },
    "ZN-DA637F-C2BE4B-AB800E": {
        "duration_days": 30,
        "max_devices": 2,
        "type": "30 Days License"
    },
    "ZN-84739B-FBDB22-52CFAE": {
        "duration_days": 7,
        "max_devices": 2,
        "type": "7 Days License"
    },
    "ZN-1AA03D-541141-83BE30": {
        "duration_days": 1,
        "max_devices": 1,
        "type": "1 Day License"
    },
    "ZN-083F7D-0A8F55-7BB75D": {
        "duration_days": 30,
        "max_devices": 2,
        "type": "30 Days License"
    },
    "ZN-8EFFFD-DEAA11-5145C8": {
        "duration_days": 1,
        "max_devices": 2,
        "type": "1 Day License"
    },
    "ZN-C63B5D-3B623C-6AC18B": {
        "duration_days": 1,
        "max_devices": 4,
        "type": "1 Day License"
    },
    "ZN-72F1C9-06116D-E8041F": {
        "duration_days": 30,
        "max_devices": 2,
        "type": "30 Days License"
    },
    "ZN-185F58-73887A-AC56B6": {
        "duration_days": 7,
        "max_devices": 1,
        "type": "7 Days License"
    },
    "ZN-B4289B-4FF903-E6CCE7": {
        "duration_days": 1,
        "max_devices": 2,
        "type": "1 Day License"
    },
    "ZN-07C8F7-D3831C-76BEC4": {
        "duration_days": 1,
        "max_devices": 4,
        "type": "1 Day License"
    },
    "ZN-72BE9E-F32C85-195178": {
        "duration_days": 7,
        "max_devices": 3,
        "type": "7 Days License"
    },
    "ZN-D5E52E-B71666-E64FA0": {
        "duration_days": 30,
        "max_devices": 1,
        "type": "30 Days License"
    },
    "ZN-1F6593-A17D5B-5F31DF": {
        "duration_days": 1,
        "max_devices": 2,
        "type": "1 Day License"
    },
    "ZN-203526-DF5093-9CAE8C": {
        "duration_days": 1,
        "max_devices": 3,
        "type": "1 Day License"
    },
    "ZN-7DAF0F-ABAF4F-94D191": {
        "duration_days": 1,
        "max_devices": 3,
        "type": "1 Day License"
    },
    "ZN-18E2DE-91689A-748DB2": {
        "duration_days": 1,
        "max_devices": 4,
        "type": "1 Day License"
    },
    "ZN-C57595-6CBBB1-EB7C4E": {
        "duration_days": 7,
        "max_devices": 4,
        "type": "7 Days License"
    },
    "ZN-941881-BD62DD-D91AC0": {
        "duration_days": 1,
        "max_devices": 1,
        "type": "1 Day License"
    },
    "ZN-1CE992-F7B8D3-5041FC": {
        "duration_days": 1,
        "max_devices": 2,
        "type": "1 Day License"
    },
    "ZN-C53178-1AF3D7-FE1DDB": {
        "duration_days": 1,
        "max_devices": 4,
        "type": "1 Day License"
    },
    "ZN-B64EB4-038E35-9A335E": {
        "duration_days": 30,
        "max_devices": 1,
        "type": "30 Days License"
    },
    "ZN-742384-45A748-67EDE7": {
        "duration_days": 30,
        "max_devices": 1,
        "type": "30 Days License"
    },
    "ZN-A52B79-4FA392-591856": {
        "duration_days": 30,
        "max_devices": 4,
        "type": "30 Days License"
    },
    "ZN-9B6F2A-30B4CB-D36D89": {
        "duration_days": 7,
        "max_devices": 1,
        "type": "7 Days License"
    },
    "ZN-AB9A09-0A9582-D708D9": {
        "duration_days": 30,
        "max_devices": 3,
        "type": "30 Days License"
    },
    "ZN-89E752-6243BB-637E51": {
        "duration_days": 7,
        "max_devices": 2,
        "type": "7 Days License"
    },
    "ZN-42FF30-C97CFE-47864B": {
        "duration_days": 1,
        "max_devices": 1,
        "type": "1 Day License"
    },
    "ZN-D934B8-54D794-39F524": {
        "duration_days": 30,
        "max_devices": 4,
        "type": "30 Days License"
    },
    "ZN-94202D-523A81-D77417": {
        "duration_days": 7,
        "max_devices": 2,
        "type": "7 Days License"
    },
    "ZN-8C8F88-C06FBE-8EE27B": {
        "duration_days": 7,
        "max_devices": 2,
        "type": "7 Days License"
    },
    "ZN-804091-3B3459-472716": {
        "duration_days": 1,
        "max_devices": 1,
        "type": "1 Day License"
    },
    "ZN-572D39-77C06B-1CBDB8": {
        "duration_days": 30,
        "max_devices": 3,
        "type": "30 Days License"
    },
    "ZN-EBB8B0-500AB5-BAC989": {
        "duration_days": 7,
        "max_devices": 3,
        "type": "7 Days License"
    },
    "ZN-0CBE49-33D5A4-871B08": {
        "duration_days": 30,
        "max_devices": 1,
        "type": "30 Days License"
    },
    "ZN-36573E-05B66A-634F01": {
        "duration_days": 30,
        "max_devices": 2,
        "type": "30 Days License"
    },
    "ZN-3D7EF6-F37C86-C56549": {
        "duration_days": 30,
        "max_devices": 4,
        "type": "30 Days License"
    },
    "ZN-2EF196-68E2FF-435BDE": {
        "duration_days": 7,
        "max_devices": 1,
        "type": "7 Days License"
    },
    "ZN-6718CF-8D45F3-F5DA07": {
        "duration_days": 7,
        "max_devices": 2,
        "type": "7 Days License"
    },
    "ZN-B9CB59-A70ABF-6B7367": {
        "duration_days": 30,
        "max_devices": 2,
        "type": "30 Days License"
    },
    "ZN-A1D6D1-A0338D-0A15DE": {
        "duration_days": 30,
        "max_devices": 1,
        "type": "30 Days License"
    },
    "ZN-3FC7A5-28278C-2E8B3E": {
        "duration_days": 30,
        "max_devices": 1,
        "type": "30 Days License"
    },
    "ZN-55E134-4DC3C7-6167BD": {
        "duration_days": 7,
        "max_devices": 1,
        "type": "7 Days License"
    },
    "ZN-3D500D-1F3141-E8537F": {
        "duration_days": 1,
        "max_devices": 4,
        "type": "1 Day License"
    },
    "ZN-AD5B97-51BA10-AFD9D8": {
        "duration_days": 1,
        "max_devices": 3,
        "type": "1 Day License"
    },
    "ZN-BF9FF4-0AE3C5-C72309": {
        "duration_days": 1,
        "max_devices": 1,
        "type": "1 Day License"
    },
    "ZN-B517DA-06365D-B8145E": {
        "duration_days": 1,
        "max_devices": 1,
        "type": "1 Day License"
    },
    "ZN-7A465F-7A9D4B-E16F27": {
        "duration_days": 7,
        "max_devices": 4,
        "type": "7 Days License"
    },
    "ZN-9B036D-BBCAB5-2C78A9": {
        "duration_days": 1,
        "max_devices": 4,
        "type": "1 Day License"
    },
    "ZN-08B219-37F45B-685277": {
        "duration_days": 30,
        "max_devices": 1,
        "type": "30 Days License"
    },
    "alireza|3255": {
        "duration_days": 30,
        "max_devices": 4,
        "type": "Welcome To Tool (MrAliReza)"
    },
    "ZN-46E880-C18AEA-A6F95D": {
        "duration_days": 30,
        "max_devices": 2,
        "type": "30 Days License"
    },
    "ZN-C72014-D6E02B-7ED6C3": {
        "duration_days": 1,
        "max_devices": 3,
        "type": "1 Day License"
    },
    "ZN-D1659D-FBF8CA-3F7932": {
        "duration_days": 1,
        "max_devices": 3,
        "type": "1 Day License"
    },
    "ZN-283CCB-D2B6DE-AB1F99": {
        "duration_days": 30,
        "max_devices": 2,
        "type": "30 Days License"
    },
    "ZN-35E254-DF57D2-6DAEC7": {
        "duration_days": 30,
        "max_devices": 3,
        "type": "30 Days License"
    },
    "ZN-535034-87B030-D71402": {
        "duration_days": 1,
        "max_devices": 3,
        "type": "1 Day License"
    },
    "ZN-6A2FB0-8E0842-B88654": {
        "duration_days": 7,
        "max_devices": 3,
        "type": "7 Days License"
    },
    "ZN-95F13C-A0E8EF-AB7362": {
        "duration_days": 7,
        "max_devices": 2,
        "type": "7 Days License"
    },
    "ZN-96C25B-707B4E-1C64BE": {
        "duration_days": 7,
        "max_devices": 2,
        "type": "7 Days License"
    },
    "ZN-C82287-0BEE41-FF67FA": {
        "duration_days": 1,
        "max_devices": 2,
        "type": "1 Day License"
    },
    "ZN-40E243-C9B96A-345A0C": {
        "duration_days": 7,
        "max_devices": 4,
        "type": "7 Days License"
    },
    "ZN-E5D008-839C17-26CFB1": {
        "duration_days": 7,
        "max_devices": 4,
        "type": "7 Days License"
    },
    "ZN-DCB90A-64E337-265D8A": {
        "duration_days": 1,
        "max_devices": 1,
        "type": "1 Day License"
    },
    "ZN-5541B6-EA282B-4D0E3A": {
        "duration_days": 7,
        "max_devices": 4,
        "type": "7 Days License"
    },
    "MRAMIRYT-OWN": {
        "duration_days": 60,
        "max_devices": 3,
        "type": "Welcome MRAMIRYT"
    },
    "EGO-OWN": {
        "duration_days": 60,
        "max_devices": 1,
        "type": "Welcome Ego"
    },
    "ALIREZA-OWN": {
        "duration_days": 60,
        "max_devices": 1,
        "type": "Welcome Alireza"
    },
    "zone1157": {
        "duration_days": 60,
        "max_devices": 1,
        "type": "HI DEVELOPER TOOLS"
    },
    "HassanXpubg-OWN": {
        "duration_days": 60,
        "max_devices": 1,
        "type": "Welcome Hassan"
    }
}

def _license_cache_file():
    config_dir = Path.home() / '.pak_tool'
    config_dir.mkdir(exist_ok=True)
    try:
        os.chmod(config_dir, 0o700)
    except Exception:
        pass
    return config_dir / 'saved_license.dat'


def _save_cached_license(license_key: str):
    """Remember the valid key locally until its existing license expiry."""
    cache_file = _license_cache_file()
    try:
        cache_file.write_text(license_key.strip(), encoding='utf-8')
        try:
            os.chmod(cache_file, 0o600)
        except Exception:
            pass
    except Exception:
        pass


def _load_cached_license():
    cache_file = _license_cache_file()
    try:
        key = cache_file.read_text(encoding='utf-8').strip()
        return key if key else None
    except Exception:
        return None


def _clear_cached_license():
    try:
        _license_cache_file().unlink(missing_ok=True)
    except Exception:
        pass


def _activate_license_key(license_key: str, cache_on_success: bool = True) -> bool:
    """Validate a key using the existing license/expiry rules and activate it."""
    global CURRENT_LICENSE
    if license_key not in LICENSE_KEYS:
        return False

    key_info = LICENSE_KEYS[license_key]
    trusted_now = _official_time()
    now = trusted_now or datetime.now()
    config_dir = Path.home() / '.pak_tool'
    config_dir.mkdir(exist_ok=True)
    activation_file = config_dir / f"license_{hashlib.sha256(license_key.encode()).hexdigest()[:16]}.dat"

    if activation_file.exists():
        try:
            activation_data = activation_file.read_text(encoding='utf-8').strip().split('|')
            activation_time = datetime.strptime(activation_data[0], '%Y-%m-%d %H:%M:%S')
            device_count = int(activation_data[1])
        except Exception:
            activation_time = now
            device_count = 1
    else:
        activation_time = now
        device_count = 1
        activation_file.write_text(
            f"{activation_time.strftime('%Y-%m-%d %H:%M:%S')}|{device_count}",
            encoding='utf-8'
        )

    expiry_date = activation_time + timedelta(days=key_info['duration_days'])
    license_type = key_info['type']
    max_devices = key_info['max_devices']

    last_run_file = config_dir / 'last_run.dat'
    if last_run_file.exists():
        try:
            last_run = datetime.strptime(last_run_file.read_text().strip(), '%Y-%m-%d %H:%M:%S')
            if now < last_run:
                console.print(_ui_panel(
                    'SECURITY ALERT',
                    Text('SYSTEM DATE TAMPERING DETECTED', style='bold red'),
                    '#FF4F7B'
                ))
                last_run_file.unlink(missing_ok=True)
                _clear_cached_license()
                sys.exit(1)
        except Exception:
            pass

    last_run_file.write_text(now.strftime('%Y-%m-%d %H:%M:%S'))

    if now >= expiry_date:
        _clear_cached_license()
        return False

    time_left = expiry_date - now
    CURRENT_LICENSE = {
        'key': license_key,
        'type': license_type,
        'expiry': expiry_date,
        'remaining_seconds': max(0, time_left.total_seconds()),
        'monotonic_start': time.monotonic(),
        'trusted_time': trusted_now is not None,
    }
    if cache_on_success:
        _save_cached_license(license_key)
    return True


def check_license():
    """Professional ZOEN MOD access screen with persistent license login."""
    try:
        # Reuse the previously entered key while its existing license time remains valid.
        cached_key = _load_cached_license()
        if cached_key and _activate_license_key(cached_key, cache_on_success=False):
            return True
        if cached_key:
            _clear_cached_license()

        _ui_clear()
        brand = Text('ZOEN', style='bold #00F5D4')
        brand.append(' MOD', style='bold white')

        info = Table.grid(padding=(0, 2))
        info.add_column(style='dim #718096')
        info.add_column(style='bold #00E5FF')
        info.add_row('PRODUCT', 'PAK ENGINEERING SUITE')
        info.add_row('ACCESS', 'LICENSE VERIFICATION')
        info.add_row('SECURITY', 'LOCAL LICENSE CHECK')

        console.print(Panel(
            Group(
                Align.center(brand),
                Align.center(Text('SECURE ACCESS GATE', style='bold white')),
                Align.center(Text('Protected terminal session', style='dim #8EA0B5')),
                Text(''),
                Align.center(info),
            ),
            title='[bold #00F5D4]◆ ZOEN AUTHORITY ◆[/]',
            subtitle='[dim]LOCAL ACCESS CONTROL[/]',
            border_style='#00F5D4',
            box=DOUBLE_EDGE,
            padding=(1, 3),
        ))
        console.print()

        for attempt in range(3):
            remaining = 3 - attempt
            console.print(_ui_panel(
                'AUTHENTICATION',
                Text(f'Enter license key  •  attempt {attempt + 1}/3', style='bold white'),
                '#7C4DFF'
            ))
            license_key = Prompt.ask('[bold #00F5D4]LICENSE KEY[/]').strip()

            if _activate_license_key(license_key, cache_on_success=True):
                time_left = CURRENT_LICENSE['expiry'] - datetime.now()
                days = time_left.days
                hours = time_left.seconds // 3600
                mins = (time_left.seconds % 3600) // 60
                remaining_text = (
                    f'{days}d {hours}h {mins}m' if days > 0 else
                    f'{hours}h {mins}m' if hours > 0 else f'{mins}m'
                )
                key_info = LICENSE_KEYS[license_key]
                details = Table.grid(padding=(0, 2))
                details.add_column(style='dim #718096')
                details.add_column(style='bold #00F5D4')
                details.add_row('STATUS', '● VALID')
                details.add_row('TYPE', CURRENT_LICENSE['type'])
                details.add_row('TIME LEFT', remaining_text)
                details.add_row('DEVICES', f'1/{key_info["max_devices"]}')
                details.add_row('CLOCK', 'OFFICIAL' if CURRENT_LICENSE['trusted_time'] else 'LOCAL FALLBACK')
                details.add_row('EXPIRES', CURRENT_LICENSE['expiry'].strftime('%Y-%m-%d %H:%M'))

                console.print(_ui_panel(
                    'ACCESS GRANTED', details, '#00FF88',
                    'License saved locally until expiry'
                ))
                time.sleep(0.8)
                return True

            console.print(_ui_panel(
                'INVALID KEY',
                Text(f'{remaining - 1} attempt(s) remaining', style='bold #FF4F7B'),
                '#FF4F7B'
            ))

        console.print(_ui_panel(
            'ACCESS LOCKED',
            Text('TOO MANY FAILED ATTEMPTS. EXITING.', style='bold red'),
            '#FF4F7B'
        ))
        return False
    except Exception as e:
        console.print(f'[red]License system error: {escape(str(e))}[/red]')
        sys.exit(1)

def block_unpackers():
    suspicious = ['pydevd', '_pydevd', 'debugpy', 'pdb', 'bdb']
    for mod in suspicious:
        if mod in sys.modules:
            sys.exit(1)

# ============================================
# RUN - application entry point
# ============================================

if __name__ == '__main__':
    _enforce_tool_path()
    if not check_license():
        sys.exit(1)
    block_unpackers()
    # The freshly downloaded child process is already coming from the
    # loading screen above, so do not show the startup animation again.
    remote_run = os.environ.get('ZD_TOOL_REMOTE_RUN') == '1'
    if remote_run:
        if not _require_online():
            console.print(Panel(
                Text("OFFLINE TOOL\nINTERNET CONNECTION REQUIRED", style="bold #FF4D6D", justify="center"),
                border_style="#FF4D6D",
                padding=(1, 3),
            ))
            sys.exit(1)
    else:
        startup_check_update()
    try:
        main_menu()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
