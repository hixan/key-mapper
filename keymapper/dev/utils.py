#!/usr/bin/python3
# -*- coding: utf-8 -*-
# key-mapper - GUI for device specific keyboard mappings
# Copyright (C) 2021 sezanzeb <proxima@hip70890b.de>
#
# This file is part of key-mapper.
#
# key-mapper is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# key-mapper is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with key-mapper.  If not, see <https://www.gnu.org/licenses/>.


"""Utility functions for all other modules in keymapper.dev"""


import math

import evdev
from evdev.ecodes import EV_KEY, EV_ABS, ABS_X, ABS_Y, ABS_RX, ABS_RY, \
    EV_REL, REL_WHEEL, REL_HWHEEL

from keymapper.logger import logger
from keymapper.config import BUTTONS


# other events for ABS include buttons
JOYSTICK = [
    evdev.ecodes.ABS_X,
    evdev.ecodes.ABS_Y,
    evdev.ecodes.ABS_RX,
    evdev.ecodes.ABS_RY,
]


# a third of a quarter circle
JOYSTICK_BUTTON_THRESHOLD = math.sin((math.pi / 2) / 3 * 1)


def sign(value):
    """Get the sign of the value, or 0 if 0."""
    if value > 0:
        return 1

    if value < 0:
        return -1

    return 0


def is_wheel(event):
    """Check if this is a wheel event."""
    return event.type == EV_REL and event.code in [REL_WHEEL, REL_HWHEEL]


def will_report_key_up(event):
    """Check if the key is expected to report a down event as well."""
    return not is_wheel(event)


def should_map_event_as_btn(device, event, mapping):
    """Does this event describe a button.

    If it does, this function will make sure its value is one of [-1, 0, 1],
    so that it matches the possible values in a mapping object if needed.

    If a new kind of event should be mappable to buttons, this is the place
    to add it.

    Especially important for gamepad events, some of the buttons
    require special rules.
    """
    if event.type == EV_KEY:
        return True

    is_mousepad = event.type == EV_ABS and 47 <= event.code <= 61
    if is_mousepad:
        return False

    if is_wheel(event):
        return True

    if event.type == EV_ABS:
        if event.code in JOYSTICK:
            l_purpose = mapping.get('gamepad.joystick.left_purpose')
            r_purpose = mapping.get('gamepad.joystick.right_purpose')

            max_abs = get_max_abs(device)

            if max_abs is None:
                logger.error(
                    'Got %s, but max_abs is %s',
                    (event.type, event.code, event.value), max_abs
                )
                return False

            threshold = max_abs * JOYSTICK_BUTTON_THRESHOLD
            triggered = abs(event.value) > threshold

            if event.code in [ABS_X, ABS_Y] and l_purpose == BUTTONS:
                event.value = sign(event.value) if triggered else 0
                return True

            if event.code in [ABS_RX, ABS_RY] and r_purpose == BUTTONS:
                event.value = sign(event.value) if triggered else 0
                return True
        else:
            # normalize event numbers to one of -1, 0, +1. Otherwise mapping
            # trigger values that are between 1 and 255 is not possible,
            # because they might skip the 1 when pressed fast enough.
            event.value = sign(event.value)
            return True

    return False


def get_max_abs(device):
    """Figure out the maximum value of EV_ABS events of that device.

    Like joystick movements or triggers.
    """
    # since input_device.absinfo(EV_ABS).max is too new for (some?) ubuntus,
    # figure out the max value via the capabilities
    capabilities = device.capabilities(absinfo=True)

    if EV_ABS not in capabilities:
        return None

    absinfos = [
        entry[1] for entry in
        capabilities[EV_ABS]
        if isinstance(entry, tuple) and isinstance(entry[1], evdev.AbsInfo)
    ]

    if len(absinfos) == 0:
        logger.error('Failed to get max abs of "%s"')
        return None

    max_abs = absinfos[0].max

    return max_abs
