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
import asyncio

from evdev.ecodes import EV_REL, REL_X, REL_Y, REL_WHEEL, REL_HWHEEL, \
    EV_ABS, ABS_X, ABS_Y, ABS_RX, ABS_RY

from keymapper.config import config
from keymapper.mapping import Mapping
from keymapper.dev.event_producer import EventProducer, MOUSE, WHEEL

from tests.test import InputDevice, UInput, MAX_ABS, clear_write_history, \
    uinput_write_history, cleanup, new_event


abs_state = [0, 0, 0, 0]


class TestEvAbsMapper(unittest.TestCase):
    # there is also `test_abs_to_rel` in test_injector.py
    def setUp(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        self.mapping = Mapping()

        device = InputDevice('/dev/input/event30')
        uinput = UInput()
        self.event_producer = EventProducer(self.mapping)
        self.event_producer.set_max_abs_from(device)
        self.event_producer.set_mouse_uinput(uinput)
        asyncio.ensure_future(self.event_producer.run())

        config.set('gamepad.joystick.x_scroll_speed', 1)
        config.set('gamepad.joystick.y_scroll_speed', 1)

    def tearDown(self):
        cleanup()

    def test_debounce(self):
        pass

    def do(self, a, b, c, d, expectation):
        """Present fake values to the loop and observe the outcome."""
        clear_write_history()
        self.event_producer.notify(new_event(EV_ABS, ABS_X, a))
        self.event_producer.notify(new_event(EV_ABS, ABS_Y, b))
        self.event_producer.notify(new_event(EV_ABS, ABS_RX, c))
        self.event_producer.notify(new_event(EV_ABS, ABS_RY, d))
        # 3 frames
        loop = asyncio.get_event_loop()
        loop.run_until_complete(asyncio.sleep(3 / 60))
        history = [h.t for h in uinput_write_history]
        # sleep long enough to test if multiple events are written
        self.assertGreater(len(history), 1)
        self.assertIn(expectation, history)
        self.assertEqual(history.count(expectation), len(history))

    def test_joystick_purpose_1(self):
        speed = 20
        self.mapping.set('gamepad.joystick.non_linearity', 1)
        self.mapping.set('gamepad.joystick.pointer_speed', speed)
        self.mapping.set('gamepad.joystick.left_purpose', MOUSE)
        self.mapping.set('gamepad.joystick.right_purpose', WHEEL)

        self.do(MAX_ABS, 0, 0, 0, (EV_REL, REL_X, speed))
        self.do(-MAX_ABS, 0, 0, 0, (EV_REL, REL_X, -speed))
        self.do(0, MAX_ABS, 0, 0, (EV_REL, REL_Y, speed))
        self.do(0, -MAX_ABS, 0, 0, (EV_REL, REL_Y, -speed))

        # vertical wheel event values are negative
        self.do(0, 0, MAX_ABS, 0, (EV_REL, REL_HWHEEL, 1))
        self.do(0, 0, -MAX_ABS, 0, (EV_REL, REL_HWHEEL, -1))
        self.do(0, 0, 0, MAX_ABS, (EV_REL, REL_WHEEL, -1))
        self.do(0, 0, 0, -MAX_ABS, (EV_REL, REL_WHEEL, 1))

    def test_joystick_purpose_2(self):
        speed = 30
        config.set('gamepad.joystick.non_linearity', 1)
        config.set('gamepad.joystick.pointer_speed', speed)
        config.set('gamepad.joystick.left_purpose', WHEEL)
        config.set('gamepad.joystick.right_purpose', MOUSE)
        config.set('gamepad.joystick.x_scroll_speed', 1)
        config.set('gamepad.joystick.y_scroll_speed', 2)

        # vertical wheel event values are negative
        self.do(MAX_ABS, 0, 0, 0, (EV_REL, REL_HWHEEL, 1))
        self.do(-MAX_ABS, 0, 0, 0, (EV_REL, REL_HWHEEL, -1))
        self.do(0, MAX_ABS, 0, 0, (EV_REL, REL_WHEEL, -2))
        self.do(0, -MAX_ABS, 0, 0, (EV_REL, REL_WHEEL, 2))

        self.do(0, 0, MAX_ABS, 0, (EV_REL, REL_X, speed))
        self.do(0, 0, -MAX_ABS, 0, (EV_REL, REL_X, -speed))
        self.do(0, 0, 0, MAX_ABS, (EV_REL, REL_Y, speed))
        self.do(0, 0, 0, -MAX_ABS, (EV_REL, REL_Y, -speed))

    def test_joystick_purpose_3(self):
        speed = 40
        self.mapping.set('gamepad.joystick.non_linearity', 1)
        config.set('gamepad.joystick.pointer_speed', speed)
        self.mapping.set('gamepad.joystick.left_purpose', MOUSE)
        config.set('gamepad.joystick.right_purpose', MOUSE)

        self.do(MAX_ABS, 0, 0, 0, (EV_REL, REL_X, speed))
        self.do(-MAX_ABS, 0, 0, 0, (EV_REL, REL_X, -speed))
        self.do(0, MAX_ABS, 0, 0, (EV_REL, REL_Y, speed))
        self.do(0, -MAX_ABS, 0, 0, (EV_REL, REL_Y, -speed))

        self.do(0, 0, MAX_ABS, 0, (EV_REL, REL_X, speed))
        self.do(0, 0, -MAX_ABS, 0, (EV_REL, REL_X, -speed))
        self.do(0, 0, 0, MAX_ABS, (EV_REL, REL_Y, speed))
        self.do(0, 0, 0, -MAX_ABS, (EV_REL, REL_Y, -speed))

    def test_joystick_purpose_4(self):
        config.set('gamepad.joystick.left_purpose', WHEEL)
        config.set('gamepad.joystick.right_purpose', WHEEL)
        self.mapping.set('gamepad.joystick.x_scroll_speed', 2)
        self.mapping.set('gamepad.joystick.y_scroll_speed', 3)

        self.do(MAX_ABS, 0, 0, 0, (EV_REL, REL_HWHEEL, 2))
        self.do(-MAX_ABS, 0, 0, 0, (EV_REL, REL_HWHEEL, -2))
        self.do(0, MAX_ABS, 0, 0, (EV_REL, REL_WHEEL, -3))
        self.do(0, -MAX_ABS, 0, 0, (EV_REL, REL_WHEEL, 3))

        # vertical wheel event values are negative
        self.do(0, 0, MAX_ABS, 0, (EV_REL, REL_HWHEEL, 2))
        self.do(0, 0, -MAX_ABS, 0, (EV_REL, REL_HWHEEL, -2))
        self.do(0, 0, 0, MAX_ABS, (EV_REL, REL_WHEEL, -3))
        self.do(0, 0, 0, -MAX_ABS, (EV_REL, REL_WHEEL, 3))


if __name__ == "__main__":
    unittest.main()
