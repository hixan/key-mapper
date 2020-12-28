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


class Memory:
    """Class to remember which keys are pressed down.

    Makes it easier to keep integrity of `unreleased` and `pressed`.
    """
    def __init__(self, key_to_code):
        self.key_to_code = key_to_code

        # mapping of future up event (type, code) to (output code, input event)
        # This is needed in order to release the correct event
        # mapped on a D-Pad. Both directions on each axis report the same type,
        # code and value (0) when releasing, but the correct release-event for
        # the mapped output needs to be triggered.
        # "I have got this release event, what was this for?"
        # It remembers the input event so that it can be cleared from `pressed`
        self._unreleased = {}

        # pressed inputs (type, code, value). This needs the value, as opposed
        # to `unreleased`, because the D-Pad event value -1 might be part of a
        # combination, but D-Pad 1 not.
        # "I have got this down event, lets remember that"
        self._pressed = set()

        # It could be done with only _unreleased, but I would have to search
        # through it. I need to access stuff for both (type, key, value) and
        # (type, key). So I'd rather have two structures to access stuff more
        # efficiently.

        # TODO what if
        #  - i get (type, code, value) as input
        #  - _unreleased.get((type, code))
        #  - input event to check for combinations: [1]
        #  Because D-Pad-1 and D-Pad+1 cannot be at the same time, so it
        #  is safe to index by (type, code) only. And it also stores the
        #  source event
        #  the more pressing question is how to get combinations. Order of
        #  events? yes. that is more flexible, sounds natural (shift+a = A),
        #  (a+shift = aaa).

        # map from key to what it needs as parent. e.g.
        # a expects shift as parent for A
        combi_dependencies = {}

        # how to check for combinations:
        # 1. got key down event

        # 2. get existing combinations for that key
        previous1 = combi_dependencies.get(key)
        previous2 = combi_dependencies.get(previous1)
        previous3 = combi_dependencies.get(previous2)
        # as long as it's != null. while loop and put on stack or something

        # 3. check if all of them are pressed down
        if (
            # previous1[:2] in self._unreleased and  # (of course this one is)
            previous2[:2] in self._unreleased and
            previous3[:2] in self._unreleased
        ):
            combined_key = (previous1, previous2, previous3)
            # do stuff
            # get target keycode
            target_code = key_to_code.get(combined_key)
            # get macro
            macro = macros.get(combined_key)

    def down(self, type, code, value):
        """Register a key down event."""
        self._unreleased[(type, code)] = (
            (self.key_to_code((type, code, value))),
            (type, code, value)
        )
        self._pressed.add((type, code, value))

    def up(self, type, code):
        """Handle a key up event."""
        full_original_event = self._unreleased.get((type, code))[1]
        self._pressed.remove(full_original_event)
        del self._unreleased[(type, code)]

    def is_pressed(self, type, code, value):
        """Is this key currently pressed."""
        # Value might be -1 for D-Pad left
        return self._pressed.get((type, code, value)) is not None


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


def handle_keycode(key_to_code, macros, event, uinput):
    """Write mapped keycodes, forward unmapped ones and manage macros.

    Parameters
    ----------
    key_to_code : dict
        mapping of (type, code, value) to linux-keycode
        or multiple of those like ((...), (...), ...) for combinatinos
    macros : dict
        mapping of (type, code, value) to _Macro objects
        or multiple of those like ((...), (...), ...) for combinatinos
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
    short = (event.type, event.code)

    existing_macro = active_macros.get(short)
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
        active_macros[short] = macro
        macro.press_key()
        logger.spam('got %s, maps to macro %s', key, macro.code)
        asyncio.ensure_future(macro.run())
        return

    if is_key_down(event) and short in unreleased:
        # duplicate key-down. skip this event. Avoid writing millions of
        # key-down events when a continuous value is reported, for example
        # for gamepad triggers
        logger.spam('%s, duplicate key down', key)
        return

    if is_key_up(event) and short in unreleased:
        target_type = EV_KEY
        target_value = 0
        target_code = unreleased[short]
        del unreleased[short]
        logger.spam('%s, releasing %s', key, target_code)
    elif key in key_to_code and is_key_down(event):
        target_type = EV_KEY
        target_value = 1
        target_code = key_to_code[key]
        unreleased[short] = target_code
        logger.spam('%s, maps to %s', key, target_code)
    else:
        target_type = key[0]
        target_code = key[1]
        target_value = key[2]
        logger.spam('%s, unmapped', key)

    uinput.write(target_type, target_code, target_value)
    uinput.syn()
