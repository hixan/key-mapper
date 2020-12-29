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
import time
import copy

import evdev
from evdev.ecodes import EV_KEY, KEY_Z

from keymapper.dev.injector import is_numlock_on, set_numlock, \
    ensure_numlock, KeycodeInjector, build_dependency_graph
from keymapper.state import custom_mapping, system_mapping
from keymapper.mapping import Mapping
from keymapper.config import config
from keymapper.dev.macros import parse

from tests.test import InputEvent, pending_events, fixtures, \
    EVENT_READ_TIMEOUT, uinput_write_history_pipe, \
    MAX_ABS, cleanup


# some stuff to choose from in tests
keys = [
    (EV_KEY, 100),
    (EV_KEY, 101),
    (EV_KEY, 102),
    (EV_KEY, 103),
    (EV_KEY, 104),
    (EV_KEY, 105),
]
events = [
    (EV_KEY, 100, 1),
    (EV_KEY, 101, 1),
    (EV_KEY, 102, 1),
    (EV_KEY, 103, 1),
    (EV_KEY, 104, 1),
    (EV_KEY, 105, 1),
]


class TestCombinations(unittest.TestCase):
    def test_build_dependency_graph_1(self):
        # no combinations
        result = build_dependency_graph({
            keys[0]: (KEY_Z, events[0]),
            keys[1]: (KEY_Z, events[1])
        })
        self.assertDictEqual(result, {})

    def test_build_dependency_graph_2(self):
        # one 2-combination
        combination = (
            keys[0], keys[1]
        )
        result = build_dependency_graph({
            combination: (KEY_Z,)  # the second element is not of interested
        })
        self.assertDictEqual(result, {
            keys[1]: [keys[0]],
            keys[0]: []
        })

    def test_build_dependency_graph_3(self):
        # two 2-combinations and a normal key
        combinations = [
            (keys[0], keys[1]),
            (keys[0], keys[2])
        ]
        result = build_dependency_graph({
            combinations[0]: (KEY_Z,),
            combinations[1]: (KEY_Z,),
            keys[2]: (KEY_Z, events[2])
        })
        self.assertDictEqual(result, {
            keys[1]: [keys[0]],
            keys[2]: [keys[0]],
            keys[0]: []
        })

    def test_build_dependency_graph_5(self):
        # one 3-combination
        combinations = [
            (keys[0], keys[1], keys[2]),
        ]
        result = build_dependency_graph({
            combinations[0]: (KEY_Z,)
        })
        self.assertDictEqual(result, {
            keys[2]: [keys[1]],
            keys[1]: [keys[0]],
            keys[0]: []
        })

    def test_build_dependency_graph_6(self):
        # two combinations that end in the same key
        combinations = [
            (keys[0], keys[1]),
            (keys[2], keys[1])
        ]
        result = build_dependency_graph({
            combinations[0]: (KEY_Z,),
            combinations[1]: (KEY_Z,),
        })
        self.assertDictEqual(result, {
            keys[1]: [keys[0], keys[2]],
            keys[2]: [],
            keys[0]: []
        })

    def test_build_dependency_graph_7(self):
        # a 2-combination and 3-combination that end in the same key,
        # and one normal key
        combinations = [
            (keys[0], keys[1]),
            (keys[3], keys[2], keys[1])
        ]
        result = build_dependency_graph({
            combinations[0]: (KEY_Z,),
            combinations[1]: (KEY_Z,),
            keys[1]: (KEY_Z, events[1])
        })
        self.assertDictEqual(result, {
            keys[1]: [keys[0], keys[2]],
            keys[2]: [keys[3]],
            keys[3]: [],
            keys[0]: []
        })

    def test_build_dependency_graph_8(self):
        # two 3-combinations with a common middle key
        combinations = [
            (keys[1], keys[5], keys[2]),
            (keys[3], keys[5], keys[4])
        ]
        result = build_dependency_graph({
            combinations[0]: (KEY_Z,),
            combinations[1]: (KEY_Z,),
        })
        print(result)
        self.assertDictEqual(result, {
            keys[2]: [keys[5]],
            keys[4]: [keys[5]],
            keys[5]: [keys[1], keys[3]],
            keys[1]: [],
            keys[3]: []
        })

    def test_build_dependency_graph_9(self):
        # two 3-combinations with a common start key
        combinations = [
            (keys[5], keys[1], keys[2]),
            (keys[5], keys[3], keys[4])
        ]
        result = build_dependency_graph({
            combinations[0]: (KEY_Z,),
            combinations[1]: (KEY_Z,),
        })
        print(result)
        self.assertDictEqual(result, {
            keys[2]: [keys[1]],
            keys[4]: [keys[3]],
            keys[1]: [keys[5]],
            keys[3]: [keys[5]],
            keys[5]: []
        })

    def test_build_dependency_graph_10(self):
        # two 3-combinations that only differ by their last key,
        # and one 2-combination
        combinations = [
            (keys[5], keys[4], keys[0]),
            (keys[5], keys[4], keys[1]),
            (keys[2], keys[3])
        ]
        result = build_dependency_graph({
            combinations[0]: (KEY_Z,),
            combinations[1]: (KEY_Z,),
            combinations[2]: (KEY_Z,),
        })
        print(result)
        self.assertDictEqual(result, {
            keys[0]: [keys[4]],
            keys[1]: [keys[4]],
            keys[4]: [keys[5]],
            keys[5]: [],
            keys[3]: [keys[2]],
            keys[2]: []
        })

    def test_build_dependency_graph_11(self):
        # two 3-combinations that only differ by their last key,
        # that is like the 3-combinations but stops early
        combinations = [
            (keys[5], keys[4], keys[0]),
            (keys[5], keys[4], keys[1]),
            (keys[5], keys[4])
        ]
        result = build_dependency_graph({
            combinations[0]: (KEY_Z,),
            combinations[1]: (KEY_Z,),
            combinations[2]: (KEY_Z,),
        })
        print(result)
        self.assertDictEqual(result, {
            keys[0]: [keys[4]],
            keys[1]: [keys[4]],
            keys[4]: [keys[5]],
            keys[5]: [],
            keys[3]: [keys[2]],
            keys[2]: []
        })

    def test_build_dependency_graph_12(self):
        # one 2-combination and one 3-combination, that has one key added
        # in front while the rest is similar to the 2-combination
        combinations = [
            (keys[1], keys[2]),
            (keys[0], keys[1], keys[2]),
        ]
        result = build_dependency_graph({
            combinations[0]: (KEY_Z,),
            combinations[1]: (KEY_Z,),
        })
        print(result)
        self.assertDictEqual(result, {
            keys[2]: [keys[1]],
            keys[1]: [keys[0]],
            keys[0]: []
        })


if __name__ == "__main__":
    unittest.main()
