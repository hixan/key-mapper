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


import unittest

from evdev import ecodes
from evdev.ecodes import EV_KEY, EV_ABS, ABS_HAT0X, KEY_A, \
    EV_REL, REL_X, REL_WHEEL, REL_HWHEEL

from keymapper.config import config, BUTTONS
from keymapper.mapping import Mapping
from keymapper.dev import utils
from keymapper.key import Key

from tests.test import new_event, InputDevice, MAX_ABS


class TestDevUtils(unittest.TestCase):
    def test_max_abs(self):
        self.assertEqual(utils.get_max_abs(InputDevice('/dev/input/event30')), MAX_ABS)
        self.assertIsNone(utils.get_max_abs(InputDevice('/dev/input/event10')))

    def test_will_report_key_up(self):
        self.assertFalse(utils.will_report_key_up(new_event(EV_REL, REL_WHEEL, 1)))
        self.assertFalse(utils.will_report_key_up(new_event(EV_REL, REL_HWHEEL, -1)))
        self.assertTrue(utils.will_report_key_up(new_event(EV_KEY, KEY_A, 1)))
        self.assertTrue(utils.will_report_key_up(new_event(EV_ABS, ABS_HAT0X, -1)))

    def test_is_wheel(self):
        self.assertTrue(utils.is_wheel(new_event(EV_REL, REL_WHEEL, 1)))
        self.assertTrue(utils.is_wheel(new_event(EV_REL, REL_HWHEEL, -1)))
        self.assertFalse(utils.is_wheel(new_event(EV_KEY, KEY_A, 1)))
        self.assertFalse(utils.is_wheel(new_event(EV_ABS, ABS_HAT0X, -1)))

    def test_should_map_event_as_btn(self):
        device = InputDevice('/dev/input/event30')
        mapping = Mapping()

        # the function name is so horribly long
        def do(event):
            return utils.should_map_event_as_btn(device, event, mapping)

        """D-Pad"""

        self.assertTrue(do(new_event(EV_ABS, ABS_HAT0X, 1)))
        self.assertTrue(do(new_event(EV_ABS, ABS_HAT0X, -1)))

        """Mouse movements"""

        self.assertTrue(do(new_event(EV_REL, REL_WHEEL, 1)))
        self.assertTrue(do(new_event(EV_REL, REL_WHEEL, -1)))
        self.assertTrue(do(new_event(EV_REL, REL_HWHEEL, 1)))
        self.assertTrue(do(new_event(EV_REL, REL_HWHEEL, -1)))
        self.assertFalse(do(new_event(EV_REL, REL_X, -1)))

        """regular keys and buttons"""

        self.assertTrue(do(new_event(EV_KEY, KEY_A, 1)))
        self.assertTrue(do(new_event(EV_ABS, ABS_HAT0X, -1)))

        """mousepad events"""

        self.assertFalse(do(new_event(EV_ABS, ecodes.ABS_MT_SLOT, 1)))
        self.assertFalse(do(new_event(EV_ABS, ecodes.ABS_MT_TOOL_Y, 1)))
        self.assertFalse(do(new_event(EV_ABS, ecodes.ABS_MT_POSITION_X, 1)))

        """joysticks"""

        self.assertFalse(do(new_event(EV_ABS, ecodes.ABS_RX, 1234)))
        self.assertFalse(do(new_event(EV_ABS, ecodes.ABS_Y, -1)))

        mapping.set('gamepad.joystick.left_purpose', BUTTONS)

        # the event.value should be modified for the left joystick
        # to one of 0, -1 or 1
        event = new_event(EV_ABS, ecodes.ABS_RX, MAX_ABS)
        self.assertFalse(do(event))
        self.assertEqual(event.value, MAX_ABS)
        event = new_event(EV_ABS, ecodes.ABS_Y, -MAX_ABS)
        self.assertTrue(do(event))
        self.assertEqual(event.value, -1)
        event = new_event(EV_ABS, ecodes.ABS_X, -MAX_ABS // 4)
        self.assertTrue(do(event))
        self.assertEqual(event.value, 0)

        config.set('gamepad.joystick.right_purpose', BUTTONS)

        event = new_event(EV_ABS, ecodes.ABS_RX, MAX_ABS)
        self.assertTrue(do(event))
        self.assertEqual(event.value, 1)
        event = new_event(EV_ABS, ecodes.ABS_Y, MAX_ABS)
        self.assertTrue(do(event))
        self.assertEqual(event.value, 1)
        event = new_event(EV_ABS, ecodes.ABS_X, MAX_ABS // 4)
        self.assertTrue(do(event))
        self.assertEqual(event.value, 0)
