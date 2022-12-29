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
import time

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

    # Switch to a different workspace for loading all the apps so that they
    # don't get squished while loading on top of the pre-loaded layout
    i3 = i3ipc.Connection()
    i3.command(f'workspace "_load_{workspace_name}"')

    # We can assume that every workspace has its own browser profile that should
    # be restored using the name of the workspace
    subprocess.Popen([os.path.expanduser('~/.local/bin/qutebrowser-profile'),
      '--load', workspace_name])
    # We give it some time to restore so that its windows are hopefully open by
    # the time we start restoring kakoune.  That should help getting things to
    # restore in the relatively right places, hopefully!
    # time.sleep(2.0)

    # Here are the details about where alacritty sockets are created...we're
    # following this to ensure that we participate in the global connectivity
    # between terminals (at least I think they use their name format to find
    # each other)
    # https://github.com/alacritty/alacritty/blob/master/alacritty/src/ipc.rs
    first_terminal = True
    socket_path = os.path.expandvars(fr'/run/user/{os.getuid()}/Alacritty-$DISPLAY-{workspace_name}.sock')
    
    # Kakoune: First, clear any dead sessions
    command = ['kak', '-clear']
    os.spawnvp(os.P_NOWAIT, command[0], command)

    # For some reason it seems we need to start the servers before adding clients
    # and (or?) add a small wait in between to avoid a race condition
    for session_name, s_entry in saved_apps.setdefault('kakoune_sessions', {}).items():
        # Start a kakoune background server for this session
        # in the server working directory
        # Kakoune's system is interesting: all the clients for a given server
        # use the server's working directory when they display the current file
        # in the title bar.  Since we only have window titles to work with for
        # resurrecting, we need to make sure we restore the proper server
        # directory first before we attempt to restore the individual clients'
        # files because those files will all be relative to that directory.
        server_working_directory = os.path.expanduser(s_entry['server_working_directory'])
        os.chdir(server_working_directory)
        server_command = ['kak', '-s', session_name, '-d']
        os.spawnvp(os.P_NOWAIT, server_command[0], server_command)
        time.sleep(0.1)


    for session_name, s_entry in saved_apps.setdefault('kakoune_sessions', {}).items():
        server_working_directory = os.path.expanduser(s_entry['server_working_directory'])
        # os.chdir(server_working_directory)

        # Now fire up each client connecting to the same session
        # in the same working directory
        for client_name, c_entry in s_entry['clients'].items():
            path = os.path.expanduser(c_entry['path'])
            line = c_entry['line']
            column = c_entry['column']
            first_terminal = run_terminal(first_terminal, socket_path, \
              ['--working-directory', server_working_directory, '-e', 'sh', '-c', \
               fr'kak -c {session_name} "{path}" +{line}:{column} -e "rename-client {client_name}"'])
            # I've had issues with the machine just grinding to a halt if too many
            # are open back-to-back.  Let's try to fix that by delaying a little:
            time.sleep(0.5)

    for a_entry in saved_apps.setdefault('alacritty', []):
        working_directory = os.path.expanduser(a_entry['path'])
        # os.chdir(working_directory)
        first_terminal = run_terminal(first_terminal, socket_path, \
          ['--working-directory', working_directory])


# Alacritty...
# 1. It has an issue where each instance hogs extra X server resources, so we
#    cut down on the instances by doing just one per workspace, and using its
#    IPC support to open new windows in the same instance.
#    https://github.com/alacritty/alacritty/issues/2735
# 2. You must wait a small amount of time after opening the first terminal
#    window before attempting any alacritty msg command or else it will
#    say that the socket doesn't exist.
# 3. Running the initial alacritty terminal should not be waited for but
#    I prefer to wait for the msg commands to give the system a litle
#    breathing room (though it doesn't seem necessary in my testing)
# 4. When creating a new window from an existing terminal, it will ignore
#    the working directory of the launching process and copy the working
#    directory from the existing terminal, so if you don't want that you
#    need to specify --working-directory <working_directory> as the first
#    of the extra_args
def run_terminal(first_terminal, socket_path, extra_args):
  command = None
  wait = None
  if first_terminal:
    command = ['alacritty', '--socket', socket_path] + extra_args
    wait = os.P_NOWAIT
  else:
    command = ['alacritty', 'msg', '--socket', socket_path, 'create-window'] + extra_args
    wait = os.P_WAIT

  # print(command)
  os.spawnvp(wait, command[0], command)

  if first_terminal:
    # You must wait a little bit after opening the first terminal before
    # attempting to connect to its socket or else the others
    # won't be able to see the socket
    time.sleep(0.1)

  # Once we do the first terminal once it's not going to be any more
  return False

