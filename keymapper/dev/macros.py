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


"""Executes more complex patterns of keystrokes.

To keep it short on the UI, the available functions are one-letter long.

The outermost macro (in the examples below the one created by 'r',
'r' and 'w') will be started, which triggers a chain reaction to execute
all of the configured stuff.

Examples
--------
r(3, k(a).w(10)): a <10ms> a <10ms> a
r(2, k(a).k(-)).k(b): a - a - b
w(1000).m(Shift_L, r(2, k(a))).w(10).k(b): <1s> A A <10ms> b
"""


import asyncio
import re

from keymapper.logger import logger
from keymapper.state import system_mapping


MODIFIER = 1
CHILD_MACRO = 2
SLEEP = 3
REPEAT = 4
KEYSTROKE = 5
DEBUG = 6


def is_this_a_macro(output):
    """Figure out if this is a macro."""
    if not isinstance(output, str):
        return False

    return '(' in output and ')' in output and len(output) >= 4


class _Macro:
    """Supports chaining and preparing actions.

    Calling functions on _Macro does not inject anything yet, it means that
    once .run is used it will be executed along with all other queued tasks.
    """
    def __init__(self, code, mapping):
        """Create a macro instance that can be populated with tasks.

        Parameters
        ----------
        code : string
            The original parsed code, for logging purposes.
        mapping : Mapping
            The preset object, needed for some config stuff
        """
        self.tasks = []
        self.handler = lambda *args: logger.error('No handler set')
        self.code = code
        self.mapping = mapping

        # supposed to be True between key event values 1 (down) and 0 (up)
        self.holding = False

        self.running = False

        # all required capabilities, without those of child macros
        self.capabilities = set()

        self.child_macros = []

    def get_capabilities(self):
        """Resolve all capabilities of the macro and those of its children."""
        capabilities = self.capabilities.copy()
        for macro in self.child_macros:
            capabilities.update(macro.get_capabilities())
        return capabilities

    def set_handler(self, handler):
        """Set the handler function.

        Parameters
        ----------
        handler : func
            A function that accepts keycodes as the first parameter and the
            key-press state as the second. 1 for down and 0 for up. The
            macro will write to this function once executed with `.run()`.
        """
        self.handler = handler
        for macro in self.child_macros:
            macro.set_handler(handler)

    async def run(self):
        """Run the macro."""
        self.running = True
        for _, task in self.tasks:
            coroutine = task()
            if asyncio.iscoroutine(coroutine):
                await coroutine

        # done
        self.running = False

    def press_key(self):
        """The user pressed the key down."""
        self.holding = True
        for macro in self.child_macros:
            macro.press_key()

    def release_key(self):
        """The user released the key."""
        self.holding = False
        for macro in self.child_macros:
            macro.release_key()

    def hold(self, macro):
        """Loops the execution until key release."""
        if not isinstance(macro, _Macro):
            raise ValueError(
                'Expected the param for h (hold) to be '
                f'a macro (like k(a)), but got "{macro}"'
            )

        async def task():
            while self.holding:
                await macro.run()

        self.tasks.append((REPEAT, task))

        self.child_macros.append(macro)

        return self

    def modify(self, modifier, macro):
        """Do stuff while a modifier is activated.

        Parameters
        ----------
        modifier : str
        macro : _Macro
        """
        if not isinstance(macro, _Macro):
            raise ValueError(
                'Expected the second param for m (modify) to be '
                f'a macro (like k(a)), but got {macro}'
            )

        modifier = str(modifier)
        code = system_mapping.get(modifier)

        if code is None:
            raise KeyError(f'Unknown modifier "{modifier}"')

        self.capabilities.add(code)

        self.child_macros.append(macro)

        self.tasks.append((MODIFIER, lambda: self.handler(code, 1)))
        self.add_keycode_pause()
        self.tasks.append((CHILD_MACRO, macro.run))
        self.add_keycode_pause()
        self.tasks.append((MODIFIER, lambda: self.handler(code, 0)))
        self.add_keycode_pause()
        return self

    def repeat(self, repeats, macro):
        """Repeat actions.

        Parameters
        ----------
        repeats : int
        macro : _Macro
        """
        if not isinstance(macro, _Macro):
            raise ValueError(
                'Expected the second param for r (repeat) to be '
                f'a macro (like k(a)), but got "{macro}"'
            )

        try:
            repeats = int(repeats)
        except ValueError as error:
            raise ValueError(
                'Expected the first param for r (repeat) to be '
                f'a number, but got "{repeats}"'
            ) from error

        for _ in range(repeats):
            self.tasks.append((CHILD_MACRO, macro.run))

        self.child_macros.append(macro)

        return self

    def add_keycode_pause(self):
        """To add a pause between keystrokes."""
        sleeptime = self.mapping.get('macros.keystroke_sleep_ms') / 1000

        async def sleep():
            await asyncio.sleep(sleeptime)

        self.tasks.append((SLEEP, sleep))

    def keycode(self, character):
        """Write the character."""
        character = str(character)
        code = system_mapping.get(character)

        if code is None:
            raise KeyError(f'aUnknown key "{character}"')

        self.capabilities.add(code)

        self.tasks.append((KEYSTROKE, lambda: self.handler(code, 1)))
        self.add_keycode_pause()
        self.tasks.append((KEYSTROKE, lambda: self.handler(code, 0)))
        self.add_keycode_pause()
        return self

    def wait(self, sleeptime):
        """Wait time in milliseconds."""
        try:
            sleeptime = int(sleeptime)
        except ValueError as error:
            raise ValueError(
                'Expected the param for w (wait) to be '
                f'a number, but got "{sleeptime}"'
            ) from error

        sleeptime /= 1000

        async def sleep():
            await asyncio.sleep(sleeptime)

        self.tasks.append((SLEEP, sleep))
        return self


def _extract_params(inner):
    """Extract parameters from the inner contents of a call.

    Parameters
    ----------
    inner : string
        for example 'r, r(2, k(a))' should result in ['r', 'r(2, k(a)']
    """
    inner = inner.strip()
    brackets = 0
    params = []
    start = 0
    for position, char in enumerate(inner):
        if char == '(':
            brackets += 1
        if char == ')':
            brackets -= 1
        if char == ',' and brackets == 0:
            # , potentially starts another parameter, but only if
            # the current brackets are all closed.
            params.append(inner[start:position].strip())
            # skip the comma
            start = position + 1

    # one last parameter
    params.append(inner[start:].strip())

    return params


def _count_brackets(macro):
    """Find where the first opening bracket closes."""
    openings = macro.count('(')
    closings = macro.count(')')
    if openings != closings:
        raise Exception(
            f'You entered {openings} opening and {closings} '
            'closing brackets'
        )

    brackets = 0
    position = 0
    for char in macro:
        position += 1
        if char == '(':
            brackets += 1
            continue

        if char == ')':
            brackets -= 1
            if brackets == 0:
                # the closing bracket of the call
                break

    return position


def _parse_recurse(macro, mapping, macro_instance=None, depth=0):
    """Handle a subset of the macro, e.g. one parameter or function call.

    Parameters
    ----------
    macro : string
        Just like parse
    mapping : Mapping
        The preset configuration
    macro_instance : _Macro or None
        A macro instance to add tasks to
    depth : int
    """
    # to anyone who knows better about compilers and thinks this is horrible:
    # please make a pull request. Because it probably is.
    # not using eval for security reasons ofc. And this syntax doesn't need
    # string quotes for its params.
    # If this gets more complicated than that I'd rather make a macro
    # editor GUI and store them as json.
    assert isinstance(macro, str)
    assert isinstance(depth, int)

    if macro_instance is None:
        macro_instance = _Macro(macro, mapping)
    else:
        assert isinstance(macro_instance, _Macro)

    macro = macro.strip()
    space = '  ' * depth

    # is it another macro?
    call_match = re.match(r'^(\w+)\(', macro)
    call = call_match[1] if call_match else None
    if call is not None:
        # available functions in the macro and the minimum and maximum number
        # of their parameters
        functions = {
            'm': (macro_instance.modify, 2, 2),
            'r': (macro_instance.repeat, 2, 2),
            'k': (macro_instance.keycode, 1, 1),
            'w': (macro_instance.wait, 1, 1),
            'h': (macro_instance.hold, 1, 1)
        }

        function = functions.get(call)
        if function is None:
            raise Exception(f'Unknown function {call}')

        # get all the stuff inbetween
        position = _count_brackets(macro)

        inner = macro[2:position - 1]

        # split "3, k(a).w(10)" into parameters
        string_params = _extract_params(inner)
        logger.spam('%scalls %s with %s', space, call, string_params)
        # evaluate the params
        params = [
            _parse_recurse(param.strip(), mapping, None, depth + 1)
            for param in string_params
        ]

        logger.spam('%sadd call to %s with %s', space, call, params)

        if len(params) < function[1] or len(params) > function[2]:
            if function[1] != function[2]:
                msg = (
                    f'{call} takes between {function[1]} and {function[2]}, '
                    f'not {len(params)} parameters'
                )
            else:
                msg = (
                    f'{call} takes {function[1]}, '
                    f'not {len(params)} parameters'
                )

            raise ValueError(msg)

        function[0](*params)

        # is after this another call? Chain it to the macro_instance
        if len(macro) > position and macro[position] == '.':
            chain = macro[position + 1:]
            logger.spam('%sfollowed by %s', space, chain)
            _parse_recurse(chain, mapping, macro_instance, depth)

        return macro_instance

    # probably a parameter for an outer function
    try:
        # if possible, parse as int
        macro = int(macro)
    except ValueError:
        # use as string instead
        pass

    logger.spam('%s%s %s', space, type(macro), macro)
    return macro


def parse(macro, mapping, return_errors=False):
    """parse and generate a _Macro that can be run as often as you want.

    You need to use set_handler on it before running. If it could not
    be parsed, possibly due to syntax errors, will log the error and
    return None.

    Parameters
    ----------
    macro : string
        "r(3, k(a).w(10))"
        "r(2, k(a).k(-)).k(b)"
        "w(1000).m(Shift_L, r(2, k(a))).w(10, 20).k(b)"
    mapping : Mapping
        The preset object, needed for some config stuff
    return_errors : bool
        if True, returns errors as a string or None if parsing worked
    """
    # whitespaces, tabs, newlines and such don't serve a purpose. make
    # the log output clearer and the parsing easier.
    macro = re.sub(r'\s', '', macro)

    if '"' in macro or "'" in macro:
        logger.info('Quotation marks in macros are not needed')
        macro = macro.replace('"', '').replace("'", '')

    if return_errors:
        logger.spam('checking the syntax of %s', macro)
    else:
        logger.spam('preparing macro %s for later execution', macro)

    try:
        macro_object = _parse_recurse(macro, mapping)
        return macro_object if not return_errors else None
    except Exception as error:
        logger.error('Failed to parse macro "%s": %s', macro, error)
        return str(error) if return_errors else None
