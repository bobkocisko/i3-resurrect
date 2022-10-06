import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import i3ipc
import psutil
import os
import re

from . import config
from . import treeutils
from . import util



def read(workspace, directory, profile):
    """
    Read saved programs file.
    """
    workspace_id = util.filename_filter(workspace)
    filename = f'workspace_{workspace_id}_apps.json'
    if profile is not None:
        filename = f'{profile}_apps.json'
    apps_file = Path(directory) / filename

    apps = None
    try:
        apps = json.loads(apps_file.read_text())
    except FileNotFoundError:
        if profile is not None:
            util.eprint('Could not find saved apps for profile '
                        f'"{profile}"')
        else:
            util.eprint('Could not find saved apps for workspace '
                        f'"{workspace}"')
        sys.exit(1)
    return apps


def restore(workspace, workspace_name, directory, profile):
    """
    Restore the running programs from an i3 workspace.
    """
    saved_apps = read(workspace, directory, profile)

    i3 = i3ipc.Connection()
    for session_name, s_entry in saved_apps.setdefault('kakoune_sessions', {}).items():
        # Start a kakoune background server for this session
        # in the server working directory
        server_working_directory = os.path.expanduser(s_entry['server_working_directory'])
        server_command = ['kak', '-s', session_name, '-d']
        # print(server_command, server_working_directory, flush=True)
        os.chdir(server_working_directory)
        os.spawnvp(os.P_NOWAIT, server_command[0], server_command)

        # Now fire up each client connecting to the same session
        # in the same working directory
        for client_name, c_entry in s_entry['clients'].items():
            path = os.path.expanduser(c_entry['path'])
            line = c_entry['line']
            column = c_entry['column']
            command = ['alacritty', '-e', 'sh', '-c', fr'kak -c {session_name} "{path}" +{line}:{column} -e "rename-client {client_name}"']
            # print(command, working_directory, flush=True)
            os.spawnvp(os.P_NOWAIT, command[0], command)

    for a_entry in saved_apps.setdefault('alacritty', []):
        working_directory = os.path.expanduser(a_entry['path'])
        command = ['alacritty']
        os.chdir(working_directory)
        os.spawnvp(os.P_NOWAIT, command[0], command)



