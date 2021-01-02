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


"""Keeps injecting keycodes in the background based on the mapping."""


import re
import asyncio
import time
import subprocess
import multiprocessing

import evdev
from evdev.ecodes import EV_KEY, EV_REL

from keymapper.logger import logger
from keymapper.getdevices import get_devices, map_abs_to_rel
from keymapper.dev.keycode_mapper import handle_keycode
from keymapper.dev import utils
from keymapper.dev.event_producer import EventProducer
from keymapper.dev.macros import parse, is_this_a_macro
from keymapper.state import system_mapping
from keymapper.mapping import DISABLE_CODE


DEV_NAME = 'key-mapper'
CLOSE = 0


# TODO joystick unmodified? forward abs_rel and abs_rel in capabilities


def is_numlock_on():
    """Get the current state of the numlock."""
    try:
        xset_q = subprocess.check_output(['xset', 'q']).decode()
        num_lock_status = re.search(
            r'Num Lock:\s+(.+?)\s',
            xset_q
        )

        if num_lock_status is not None:
            return num_lock_status[1] == 'on'

        return False
    except subprocess.CalledProcessError:
        # tty
        return None


def set_numlock(state):
    """Set the numlock to a given state of True or False."""
    if state is None:
        return

    value = {
        True: 'on',
        False: 'off'
    }[state]

    try:
        subprocess.check_output(['numlockx', value])
    except subprocess.CalledProcessError:
        # might be in a tty
        pass
    except FileNotFoundError:
        # doesn't seem to be installed everywhere
        logger.debug('numlockx not found')


def ensure_numlock(func):
    """Decorator to reset the numlock to its initial state afterwards."""
    def wrapped(*args, **kwargs):
        # for some reason, grabbing a device can modify the num lock state.
        # remember it and apply back later
        numlock_before = is_numlock_on()

        result = func(*args, **kwargs)

        set_numlock(numlock_before)

        return result
    return wrapped


def is_in_capabilities(key, capabilities):
    """Are this key or one of its sub keys in the capabilities?

    Parameters
    ----------
    key : Key
    """
    for sub_key in key:
        if sub_key[1] in capabilities.get(sub_key[0], []):
            return True

    return False


class KeycodeInjector:
    """Keeps injecting keycodes in the background based on the mapping.

    Is a process to make it non-blocking for the rest of the code and to
    make running multiple injector easier. There is one procss per
    hardware-device that is being mapped.
    """
    regrab_timeout = 0.5

    def __init__(self, device, mapping):
        """Start injecting keycodes based on custom_mapping.

        Parameters
        ----------
        device : string
            the name of the device as available in get_device
        mapping : Mapping
        """
        self.device = device
        self.mapping = mapping
        self._process = None
        self._msg_pipe = multiprocessing.Pipe()
        self._key_to_code = self._map_keys_to_codes()
        self.stopped = False
        self._event_producer = None

    def _map_keys_to_codes(self):
        """To quickly get target keycodes during operation.

        Returns a mapping of one or more 3-tuples to ints.
        Examples:
            ((1, 2, 1),): 3
            ((1, 5, 1), (1, 4, 1)): 4
        """
        key_to_code = {}
        for key, output in self.mapping:
            if is_this_a_macro(output):
                continue

            target_code = system_mapping.get(output)
            if target_code is None:
                logger.error('Don\'t know what %s is', output)
                continue

            for permutation in key.get_permutations():
                if permutation.keys[-1][-1] not in [-1, 1]:
                    logger.error(
                        'Expected values to be -1 or 1 at this point: %s',
                        permutation.keys
                    )
                key_to_code[permutation.keys] = target_code

        return key_to_code

    def start_injecting(self):
        """Start injecting keycodes."""
        if self.stopped or self._process is not None:
            # So that there is less concern about integrity when putting
            # stuff into self. Each injector object can only be
            # started once.
            raise Exception('Please construct a new injector instead')

        if self.device not in get_devices():
            logger.error('Cannot inject for unknown device "%s"', self.device)
            return

        self._process = multiprocessing.Process(target=self._start_injecting)
        self._process.start()

    def _prepare_device(self, path):
        """Try to grab the device, return if not needed/possible.

        Also return if ABS events are changed to REL mouse movements,
        because the capabilities of the returned device are changed
        so this cannot be checked later anymore.
        """
        try:
            device = evdev.InputDevice(path)
        except FileNotFoundError:
            return None, False

        capabilities = device.capabilities(absinfo=False)

        needed = False
        for key, _ in self.mapping:
            if is_in_capabilities(key, capabilities):
                needed = True
                break

        abs_to_rel = map_abs_to_rel(capabilities)

        if abs_to_rel:
            needed = True

        if not needed:
            # skipping reading and checking on events from those devices
            # may be beneficial for performance.
            logger.debug('No need to grab %s', path)
            return None, False

        attempts = 0
        while True:
            try:
                # grab to avoid e.g. the disabled keycode of 10 to confuse
                # X, especially when one of the buttons of your mouse also
                # uses 10. This also avoids having to load an empty xkb
                # symbols file to prevent writing any unwanted keys.
                device.grab()
                logger.debug('Grab %s', path)
                break
            except IOError:
                attempts += 1
                # it might take a little time until the device is free if
                # it was previously grabbed.
                logger.debug('Failed attemts to grab %s: %d', path, attempts)

            if attempts >= 4:
                logger.error('Cannot grab %s, it is possibly in use', path)
                return None, False

            time.sleep(self.regrab_timeout)

        return device, abs_to_rel

    def _modify_capabilities(self, macros, input_device, abs_to_rel):
        """Adds all used keycodes into a copy of a devices capabilities.

        A device with those capabilities can do exactly the stuff it needs
        to perform all mappings and macros.

        Prameters
        ---------
        macros : dict
            maping of int to _Macro
        input_device : evdev.InputDevice
        abs_to_rel : bool
            if ABS capabilities should be removed in favor of REL
        """
        ecodes = evdev.ecodes

        # copy the capabilities because the uinput is going
        # to act like the device.
        capabilities = input_device.capabilities(absinfo=False)

        if (self._key_to_code or macros) and capabilities.get(EV_KEY) is None:
            capabilities[EV_KEY] = []

        # Furthermore, support all injected keycodes
        for code in self._key_to_code.values():
            if code == DISABLE_CODE:
                continue

            if code not in capabilities[EV_KEY]:
                capabilities[EV_KEY].append(code)

        # and all keycodes that are injected by macros
        for macro in macros.values():
            capabilities[EV_KEY] += list(macro.get_capabilities())

        if abs_to_rel:
            # REL_WHEEL was also required to recognize the gamepad
            # as mouse, even if no joystick is used as wheel.
            capabilities[EV_REL] = [
                evdev.ecodes.REL_X,
                evdev.ecodes.REL_Y,
                evdev.ecodes.REL_WHEEL,
                evdev.ecodes.REL_HWHEEL,
            ]

            if capabilities.get(EV_KEY) is None:
                capabilities[EV_KEY] = []

            if ecodes.BTN_MOUSE not in capabilities[EV_KEY]:
                # to be able to move the cursor, this key capability is
                # needed
                capabilities[EV_KEY].append(ecodes.BTN_MOUSE)

        # just like what python-evdev does in from_device
        if ecodes.EV_SYN in capabilities:
            del capabilities[ecodes.EV_SYN]
        if ecodes.EV_FF in capabilities:
            del capabilities[ecodes.EV_FF]
        if ecodes.EV_ABS in capabilities:
            # EV_KEY events are ignoerd by the os when EV_ABS capabilities
            # are present
            del capabilities[ecodes.EV_ABS]

        return capabilities

    async def _msg_listener(self, loop):
        """Wait for messages from the main process to do special stuff."""
        while True:
            frame_available = asyncio.Event()
            loop.add_reader(self._msg_pipe[0].fileno(), frame_available.set)
            await frame_available.wait()
            frame_available.clear()
            msg = self._msg_pipe[0].recv()
            if msg == CLOSE:
                logger.debug('Received close signal')
                # stop the event loop and cause the process to reach its end
                # cleanly. Using .terminate prevents coverage from working.
                loop.stop()
                return

    def _start_injecting(self):
        """The injection worker that keeps injecting until terminated.

        Stuff is non-blocking by using asyncio in order to do multiple things
        somewhat concurrently.

        Use this function as starting point in a process. It creates
        the loops needed to read and map events and keeps running them.
        """
        # create a new event loop, because somehow running an infinite loop
        # that sleeps on iterations (event_producer) in one process causes
        # another injection process to screw up reading from the grabbed
        # device.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        numlock_state = is_numlock_on()

        loop = asyncio.get_event_loop()
        coroutines = []

        logger.info('Starting injecting the mapping for "%s"', self.device)

        paths = get_devices()[self.device]['paths']

        self._event_producer = EventProducer(self.mapping)

        # Watch over each one of the potentially multiple devices per hardware
        for path in paths:
            source, abs_to_rel = self._prepare_device(path)
            if source is None:
                # this path doesn't need to be grabbed for injection, because
                # it doesn't provide the events needed to execute the mapping
                continue

            # each device needs own macro instances to add a custom handler
            logger.debug('Parsing macros for %s', path)
            macros = {}
            for key, output in self.mapping:
                if is_this_a_macro(output):
                    macro = parse(output, self.mapping)
                    if macro is None:
                        continue

                    for permutation in key.get_permutations():
                        macros[permutation.keys] = macro

            if len(macros) == 0:
                logger.debug('No macros configured')

            # certain capabilities can have side effects apparently. with an
            # EV_ABS capability, EV_REL won't move the mouse pointer anymore.
            # so don't merge all InputDevices into one UInput device.
            uinput = evdev.UInput(
                name=f'{DEV_NAME} {self.device}',
                phys=DEV_NAME,
                events=self._modify_capabilities(macros, source, abs_to_rel)
            )

            logger.spam(
                'Injected capabilities for "%s": %s',
                path, uinput.capabilities(verbose=True)
            )

            def handler(*args, uinput=uinput):
                # this ensures that the right uinput is used for macro_write,
                # because this is within a loop
                self._macro_write(*args, uinput)

            for macro in macros.values():
                macro.set_handler(handler)

            # actual reading of events
            coroutines.append(self._event_consumer(
                macros,
                source,
                uinput
            ))

            # The event source of the current iteration will deliver events
            # that are needed for this. It is that one that will be mapped
            # to a mouse-like devnode.
            if abs_to_rel:
                self._event_producer.set_max_abs_from(source)
                self._event_producer.set_mouse_uinput(uinput)

        if len(coroutines) == 0:
            logger.error('Did not grab any device')
            return

        coroutines.append(self._msg_listener(loop))

        # set the numlock state to what it was before injecting, because
        # grabbing devices screws this up
        set_numlock(numlock_state)

        # run besides this stuff
        coroutines.append(self._event_producer.run())

        try:
            loop.run_until_complete(asyncio.gather(*coroutines))
        except RuntimeError:
            # stopped event loop most likely
            pass
        except OSError as error:
            logger.error(str(error))

        if len(coroutines) > 0:
            logger.debug('asyncio coroutines ended')

    def _macro_write(self, code, value, uinput):
        """Handler for macros."""
        logger.spam('macro writes code:%s value:%d', code, value)
        uinput.write(EV_KEY, code, value)
        uinput.syn()

    async def _event_consumer(self, macros, source, uinput):
        """Reads input events to inject keycodes or talk to the event_producer.

        Can be stopped by stopping the asyncio loop. This loop
        reads events from a single device only. Other devnodes may be
        present for the hardware device, in which case this needs to be
        started multiple times.

        Parameters
        ----------
        macros : int: _Macro
            macro with a handler that writes to the provided uinput
        source : evdev.InputDevice
            where to read keycodes from
        uinput : evdev.UInput
            where to write keycodes to
        """
        logger.debug(
            'Started injecting into %s, fd %s',
            uinput.device.path, uinput.fd
        )

        async for event in source.async_read_loop():
            self._event_producer.notify(event)
            if utils.should_map_event_as_btn(source, event, self.mapping):
                handle_keycode(
                    self._key_to_code,
                    macros,
                    event,
                    uinput
                )

                if not utils.is_wheel(event):
                    # if not up event needs to be simulated, the iteration
                    # is done at this point.
                    continue

                # TODO test
                self._event_producer.debounce(
                    id=(event.type, event.code, event.value),
                    func=handle_keycode,
                    args=(
                        self._key_to_code,
                        macros,
                        evdev.InputEvent(0, 0, event.type, event.code, 0),
                        uinput
                    ),
                    ticks=3
                )
                continue

            if self._event_producer.is_handled(event):
                # the event_producer will take care of it
                continue

            # forward the rest
            uinput.write(event.type, event.code, event.value)
            # this already includes SYN events, so need to syn here again

        logger.error(
            'The injector for "%s" stopped early',
            uinput.device.path
        )

    @ensure_numlock
    def stop_injecting(self):
        """Stop injecting keycodes."""
        logger.info('Stopping injecting keycodes for device "%s"', self.device)
        self._msg_pipe[1].send(CLOSE)
        self.stopped = True
