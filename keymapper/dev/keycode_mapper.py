#!/usr/bin/python3
# -*- coding: utf-8 -*-
# key-mapper - GUI for device specific keyboard mappings
# Copyright (C) 2020 sezanzeb <proxima@hip70890b.de>
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


"""Inject a keycode based on the mapping."""


import asyncio

from evdev.ecodes import EV_KEY, EV_ABS

from keymapper.logger import logger
from keymapper.util import sign
from keymapper.dev.ev_abs_mapper import JOYSTICK


# maps mouse buttons to macro instances that have been executed. They may
# still be running or already be done. Just like unreleased, this is a
# mapping of (type, code). The value is not included in the key, because
# a key release event with a value of 0 needs to be able to find the
# running macro. The downside is that a d-pad cannot execute two macros at
# once, one for each direction. Only sequentially.
active_macros = {}

# mapping of future up event (type, code) to (output code, input event)
# This is needed in order to release the correct event mapped on a
# D-Pad. Each direction on one D-Pad axis reports the same type and
# code, but different values. There cannot be both at the same time,
# as pressing one side of a D-Pad forces the other side to go up.
# "I have got this release event, what was this for?"
# It maps to (output_code, input_event) with input_event being the
# same as the key, but with the value of e.g. -1 or 1. The complete
# 3-tuple output event is used for combined button presses. A
# combination might be desired for D-Pad left, but not D-Pad right.
unreleased = {}


def should_map_event_as_btn(ev_type, code):
    """Does this event describe a button.

    Especially important for gamepad events, some of the buttons
    require special rules.

    Parameters
    ----------
    ev_type : int
        one of evdev.events
    code : int
        linux keycode
    """
    if ev_type == EV_KEY:
        return True

    if ev_type == EV_ABS:
        is_mousepad = 47 <= code <= 61
        if not is_mousepad and code not in JOYSTICK:
            return True

    return False


def is_key_down(event):
    """Is this event a key press."""
    return event.value != 0


def is_key_up(event):
    """Is this event a key release."""
    return event.value == 0


COMBINATION_INCOMPLETE = 1  # not all keys of the combination are pressed
NOT_COMBINED = 2  # this key is not part of a combination


def resolve_dependencies(key, combi_dependencies):
    """Get a list of pressed down keys that may make up a combined key press,
    with key as the newest key, which will get the highest index.

    The first element is the first key that has to be pressed down.
    """
    # TODO unittest
    # TODO unittest a + b + c and b + a + c, all keys being down
    dependencies = [key]

    while True:
        dependency = combi_dependencies.get(dependencies[-1])

        if dependency is None:
            # dependency list completely resolved
            break

        if isinstance(dependency, list):
            # a + b + c; d + b + c; [a, d]
            # take the first one of a or d that is unreleased
            dependency = [d for d in dependency if unreleased.get(d[:2])][0]

        # (output code, input event)
        unreleased_entry = unreleased.get(dependency[:2])

        if unreleased_entry is None:
            return COMBINATION_INCOMPLETE

        if unreleased_entry[1] != key:
            # For example D-Pad left is the dependency, but D-Pad right is
            # in unreleased. D-Pad right being unreleased means D-Pad left
            # cannot be pressed down, they are mutually exclusive.
            return COMBINATION_INCOMPLETE

        dependencies.append(dependency)

    return dependencies


def handle_keycode(key_to_code, macros, combi_dependencies, event, uinput):
    """Write mapped keycodes, forward unmapped ones and manage macros.

    Parameters
    ----------
    key_to_code : dict
        mapping of (type, code, value) to linux-keycode
        or multiple of those like ((...), (...), ...) for combinations
    macros : dict
        mapping of (type, code, value) to _Macro objects
        or multiple of those like ((...), (...), ...) for combinations.
        combinations need to be present in every possible valid ordering.
        e.g. shift + alt + a and alt + shift + a
    combi_dependencies : dict
        See docstring of KeycodeInjector._map_dependencies
    event : evdev.InputEvent
    """
    if event.type == EV_KEY and event.value == 2:
        # button-hold event. Linux creates them on its own for the
        # injection-fake-device if the release event won't appear,
        # no need to forward or map them.
        return

    # normalize event numbers to one of -1, 0, +1. Otherwise mapping
    # trigger values that are between 1 and 255 is not possible, because
    # they might skip the 1 when pressed fast enough.
    key = (event.type, event.code, sign(event.value))
    without_value = (event.type, event.code)

    dependencies = resolve_dependencies(key, combi_dependencies)
    # combination = [unreleased.keys()]

    if dependencies == COMBINATION_INCOMPLETE:
        # failed, maybe later
        return

    if isinstance(dependencies, list):
        # the combination is complete. query for the combined key instead
        key = tuple(dependencies)

    existing_macro = active_macros.get(without_value)
    if existing_macro is not None:
        if is_key_up(event) and not existing_macro.running:
            # key was released, but macro already stopped
            return

        if is_key_up(event) and existing_macro.holding:
            # Tell the macro for that keycode that the key is released and
            # let it decide what to with that information.
            existing_macro.release_key()
            return

        if is_key_down(event) and existing_macro.running:
            # for key-down events and running macros, don't do anything.
            # This avoids spawning a second macro while the first one is not
            # finished, especially since gamepad-triggers report a ton of
            # events with a positive value.
            return

    if key in macros:
        macro = macros[key]
        active_macros[without_value] = macro
        macro.press_key()
        logger.spam('got %s, maps to macro %s', key, macro.code)
        asyncio.ensure_future(macro.run())
        return

    if is_key_down(event) and without_value in unreleased:
        # duplicate key-down. skip this event. Avoid writing millions of
        # key-down events when a continuous value is reported, for example
        # for gamepad triggers
        logger.spam('%s, duplicate key down', key)
        return

    if is_key_up(event) and without_value in unreleased:
        target_type = EV_KEY
        target_value = 0
        target_code = unreleased[without_value][0]
        del unreleased[without_value]
        logger.spam('%s, releasing %s', key, target_code)
    elif key in key_to_code and is_key_down(event):
        target_type = EV_KEY
        target_value = 1
        target_code = key_to_code[key]
        unreleased[without_value] = (target_code, key)
        logger.spam('%s, maps to %s', key, target_code)
    else:
        target_type = key[0]
        target_code = key[1]
        target_value = key[2]
        logger.spam('%s, unmapped', key)

    uinput.write(target_type, target_code, target_value)
    uinput.syn()
