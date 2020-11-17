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


"""Quite some code that is not used anymore, but might be in the future.

Currently it is not needed to create symbols files in xkb. Very sad.

Resources:
[1] https://wiki.archlinux.org/index.php/Keyboard_input
[2] http://people.uleth.ca/~daniel.odonnell/Blog/custom-keyboard-in-linuxx11
[3] https://www.x.org/releases/X11R7.7/doc/xorg-docs/input/XKB-Enhancing.html
"""


import os
import re
import stat

from keymapper.paths import get_usr_path, KEYCODES_PATH, DEFAULT_SYMBOLS, \
    X11_SYMBOLS
from keymapper.logger import logger
from keymapper.data import get_data_path
from keymapper.mapping import custom_mapping, system_mapping, Mapping


permissions = stat.S_IREAD | stat.S_IWRITE | stat.S_IRGRP | stat.S_IROTH

MAX_KEYCODE = 255
MIN_KEYCODE = 8


def create_preset(device, name=None):
    """Create an empty preset and return the potentially incremented name.

    Automatically avoids file conflicts by adding a number to the name
    if needed.
    """
    if name is None:
        name = 'new preset'

    # find a name that is not already taken
    if os.path.exists(get_usr_path(device, name)):
        i = 2
        while os.path.exists(get_usr_path(device, f'{name} {i}')):
            i += 1
        name = f'{name} {i}'

    path = get_usr_path(device, name)
    if not os.path.exists(path):
        logger.info('Creating new file %s', path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.mknod(path)

    # add the same permissions as other symbol files, only root may write.
    os.chmod(path, permissions)

    return name


def create_setxkbmap_config(device, preset):
    """Generate a config file for setxkbmap.

    Parameters
    ----------
    device : string
    preset : string
    """
    if len(custom_mapping) == 0:
        logger.debug('Got empty mappings')
        return None

    create_identity_mapping()
    create_default_symbols()

    device_path = get_usr_path(device)
    if not os.path.exists(device_path):
        logger.info('Creating directory "%s"', device_path)
        os.makedirs(device_path, exist_ok=True)

    preset_path = get_usr_path(device, preset)
    if not os.path.exists(preset_path):
        logger.info('Creating config file "%s"', preset_path)
        os.mknod(preset_path)

    logger.info('Writing key mappings to %s', preset_path)
    with open(preset_path, 'w') as f:
        contents = generate_symbols(get_preset_name(device, preset))
        if contents is not None:
            f.write(contents)


def get_preset_name(device, preset=None):
    """Get the name for that preset that is used for the setxkbmap command."""
    # It's the relative path starting from X11/xkb/symbols and must not
    # contain spaces
    name = get_usr_path(device, preset)[len(X11_SYMBOLS) + 1:]
    assert ' ' not in name
    return name


DEFAULT_SYMBOLS_NAME = get_preset_name('default')
EMPTY_SYMBOLS_NAME = get_preset_name('empty')


def create_identity_mapping():
    """Because the concept of "reasonable symbolic names" [3] doesn't apply
    when mouse buttons are all over the place. Create an identity mapping
    to make generating "symbols" files easier. Keycode 10 -> "<10>"

    This has the added benefit that keycodes reported by xev can be
    identified in the symbols file.

    The identity mapping is provided to '-keycodes' of setxkbmap.
    """
    if os.path.exists(KEYCODES_PATH):
        logger.debug('Found the keycodes file at %s', KEYCODES_PATH)
        return

    xkb_keycodes = []
    for keycode in range(MIN_KEYCODE, MAX_KEYCODE + 1):
        xkb_keycodes.append(f'<{keycode}> = {keycode};')

    template_path = get_data_path('xkb_keycodes_template')
    with open(template_path, 'r') as template_file:
        template = template_file.read()

    result = template.format(
        minimum=MIN_KEYCODE,
        maximum=MAX_KEYCODE,
        xkb_keycodes='\n    '.join(xkb_keycodes)
    )

    if not os.path.exists(KEYCODES_PATH):
        logger.debug('Creating "%s"', KEYCODES_PATH)
        os.makedirs(os.path.dirname(KEYCODES_PATH), exist_ok=True)
        os.mknod(KEYCODES_PATH)
        os.chmod(KEYCODES_PATH, permissions)

    with open(KEYCODES_PATH, 'w') as keycodes:
        keycodes.write(result)


def generate_symbols(
        name, include=DEFAULT_SYMBOLS_NAME, mapping=custom_mapping
):
    """Create config contents to be placed in /usr/share/X11/xkb/symbols.

    It's the mapping of the preset as expected by X. This function does not
    create the file.

    Parameters
    ----------
    name : string
        Usually what `get_preset_name` returns
    include : string or None
        If another preset should be included. Defaults to the default
        preset. Use None to avoid including.
    mapping : Mapping
        If you need to create a symbols file for some other mapping you can
        pass it to this parameter. By default the custom mapping will be
        used that is also displayed in the user interface.
    """
    if len(mapping) == 0:
        raise ValueError('Mapping is empty')

    # If the symbols file contains key codes that are not present in
    # the keycodes file, THE WHOLE X SESSION WILL CRASH!
    if not os.path.exists(KEYCODES_PATH):
        raise FileNotFoundError('Expected the keycodes file to exist')

    with open(KEYCODES_PATH, 'r') as f:
        keycodes = re.findall(r'<.+?>', f.read())

    xkb_symbols = []
    for system_keycode, (target_keycode, character) in mapping:
        if f'<{system_keycode}>' not in keycodes:
            logger.error(f'Unknown code <{system_keycode}> for "{character}"')
            # don't append that one, otherwise X would crash when loading
            continue

        # key-mapper will write target_keycode into /dev, while
        # system_keycode should do nothing to avoid a duplicate keystroke.
        print('writing', system_keycode, target_keycode, character)
        if target_keycode is not None:
            if f'<{target_keycode}>' not in keycodes:
                logger.error(f'Unknown code <{target_keycode}> for "{character}"')
                # don't append that one, otherwise X would crash when loading
                continue
            xkb_symbols.append(
                f'key <{system_keycode}> {{ [ ] }}; '
            )
            xkb_symbols.append(
                f'key <{target_keycode}> {{ [ {character} ] }}; '
                f'// {system_keycode}'
            )
            continue

        xkb_symbols.append(
            f'key <{system_keycode}> {{ [ {character} ] }}; '
        )

    if len(xkb_symbols) == 0:
        logger.error('Failed to populate xkb_symbols')
        return None

    template_path = get_data_path('xkb_symbols_template')
    with open(template_path, 'r') as template_file:
        template = template_file.read()

    result = template.format(
        name=name,
        xkb_symbols='\n    '.join(xkb_symbols),
        include=f'include "{include}"' if include else ''
    )

    return result


def parse_symbols_file(device, preset):
    """Parse a symbols file populate the mapping.

    Existing mappings are overwritten if there are conflicts.
    """
    path = get_usr_path(device, preset)

    if not os.path.exists(path):
        logger.debug(
            'Tried to load non existing preset "%s" for %s',
            preset, device
        )
        custom_mapping.empty()
        custom_mapping.changed = False
        return

    with open(path, 'r') as f:
        # from "key <12> { [ 1 ] };" extract 12 and 1,
        # from "key <12> { [ a, A ] };" extract 12 and [a, A]
        # avoid lines that start with special characters
        # (might be comments)
        # And only find those lines that have a system-keycode written
        # after them, because I need that one to show in the ui. (Might
        # be deprecated.)
        content = f.read()
        result = re.findall(
            r'\n\s+?key <(.+?)>.+?\[\s+(.+?)\s+\]\s+?}; // (\d+)',
            content
        )
        logger.debug('Found %d mappings in preset "%s"', len(result), preset)
        for target_keycode, character, system_keycode in result:
            custom_mapping.change(
                previous_keycode=None,
                new_keycode=system_keycode,
                character=character
            )
        custom_mapping.changed = False


def create_default_symbols():
    """Parse the output of xmodmap and create a default symbols file.

    Since xmodmap may print mappings that have already been modified by
    key-mapper, this should be done only once after the installation.

    This is needed because all our keycode aliases in the symbols files
    are "<int>", whereas the others are <AB01> and such, so they are not
    compatible.
    """
    if os.path.exists(DEFAULT_SYMBOLS):
        logger.debug('Found the default mapping at %s', DEFAULT_SYMBOLS)
        return

    contents = generate_symbols(DEFAULT_SYMBOLS_NAME, None, system_mapping)

    if not os.path.exists(DEFAULT_SYMBOLS):
        logger.info('Creating %s', DEFAULT_SYMBOLS)
        os.makedirs(os.path.dirname(DEFAULT_SYMBOLS), exist_ok=True)
        os.mknod(DEFAULT_SYMBOLS)
        os.chmod(DEFAULT_SYMBOLS, permissions)

    with open(DEFAULT_SYMBOLS, 'w') as f:
        if contents is not None:
            logger.info('Updating default mappings')
            f.write(contents)
        else:
            logger.error('Failed to write default mappings')