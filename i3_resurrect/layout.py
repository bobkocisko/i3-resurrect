from asyncio.subprocess import PIPE
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
import tempfile
import os

import i3ipc

from . import treeutils
from . import util


def save(workspace, numeric, directory, profile, swallow_criteria):
    """
    Save an i3 workspace layout to a file.
    """
    workspace_id = util.filename_filter(workspace)
    filename = f'workspace_{workspace_id}_layout.json'
    if profile is not None:
        filename = f'{profile}_layout.json'
    layout_file = Path(directory) / filename

    app_filename = f'workspace_{workspace_id}_apps.json'
    app_file = Path(directory) / app_filename

    workspace_tree = treeutils.get_workspace_tree(workspace, numeric)

    # Build new workspace tree suitable for restoring and write it to a
    # file.
    app_specific = {}
    tree = build_layout(workspace_tree, swallow_criteria, app_specific)

    # Find out the cwd of each session so we can restore that properly
    #tmpfile = subprocess.check_output(['mktemp'], text=True).strip()
    for session_name, s_entry in app_specific['kakoune_sessions'].items():
        with tempfile.NamedTemporaryFile('w+') as tf:
            # echo "echo %sh{pwd > tmpfile}" | kak -p 78177
            input = r'echo %sh{pwd > ' + tf.name + r'}'
            subprocess.run(['kak', '-p', session_name], 
                input=input, check=True, text=True)
            # Wait for the async process to write to the file
            # (yes I know something like pyinotify would be better here
            #  but I couldn't figure out how to install it... :=O)
            while os.path.getsize(tf.name) == 0:
                pass
            server_cwd = tf.read().strip()
            # print(server_cwd)
            s_entry['server_working_directory'] = server_cwd
            
        # print(input, flush=True)
        # p = subprocess.Popen(['kak', '-p', session_name], text=True, stdin=PIPE)
        # p.stdin.write(input + "\n")
        # p.stdin.close()
        # # p.communicate(input=input)
        # if p.wait() != 0:
        #     util.eprint("Asking kak for the cwd failed")
        #     sys.exit(1)
        # with open('/home/bob-k/data') as f:
        #     server_cwd = f.read()
        #     print(server_cwd)
        #     s_entry['server_working_directory'] = server_cwd


    with layout_file.open('w') as f:
        f.write(json.dumps(tree, indent=2))

    # print(app_specific, flush=True)
    with app_file.open('w') as f:
        f.write(json.dumps(app_specific, indent=2))


def read(workspace, directory, profile):
    """
    Read saved layout file.
    """
    workspace_id = util.filename_filter(workspace)
    filename = f'workspace_{workspace_id}_layout.json'
    if profile is not None:
        filename = f'{profile}_layout.json'
    layout_file = Path(directory) / filename

    layout = None
    try:
        layout = json.loads(layout_file.read_text())
    except FileNotFoundError:
        if profile is not None:
            util.eprint(f'Could not find saved layout for profile "{profile}"')
        else:
            util.eprint('Could not find saved layout for workspace '
                        f'"{workspace}"')
        sys.exit(1)
    return layout


def restore(workspace_name, layout):
    """
    Restore an i3 workspace layout.
    """
    if layout == {}:
        return
    window_ids = []
    placeholder_window_ids = []

    # Get ids of all placeholder or normal windows in workspace.
    ws = treeutils.get_workspace_tree(workspace_name, False)
    windows = treeutils.get_leaves(ws)
    for con in windows:
        window_id = con['window']
        if is_placeholder(con):
            # If window is a placeholder, add it to list of placeholder
            # windows.
            placeholder_window_ids.append(window_id)
        else:
            # Otherwise, add it to the list of regular windows.
            window_ids.append(window_id)

    # Unmap all non-placeholder windows in workspace.
    for window_id in window_ids:
        xdo_unmap_window(window_id)

    # Remove any remaining placeholder windows in workspace so that we don't
    # have duplicates.
    for window_id in placeholder_window_ids:
        xdo_kill_window(window_id)

    try:
        i3 = i3ipc.Connection()

        # append_layout can only insert nodes so we must separately change the
        # layout mode of the workspace node.
        ws_layout_mode = layout.get('layout', 'default')
        tree = i3.get_tree()
        focused = tree.find_focused()
        workspace_node = focused.workspace()
        workspace_node.command(f'layout {ws_layout_mode}')

        # We don't want to pass the whole layout file because we don't want to
        # append a new workspace. append_layout requires a file path so we must
        # extract the part of the json that we want and store it in a tempfile.
        restorable_layout = (
            layout.get('nodes', []) + layout.get('floating_nodes', []),
        )
        restorable_layout_file = tempfile.NamedTemporaryFile(
            mode='w',
            prefix='i3-resurrect_',
        )
        restorable_layout_file.write(json.dumps(restorable_layout))
        restorable_layout_file.flush()

        # Create fresh placeholder windows by appending layout to workspace.
        i3.command(f'append_layout {restorable_layout_file.name}')

        # Delete tempfile.
        restorable_layout_file.close()
    except Exception as e:
        util.eprint('Error occurred restoring workspace layout. Note that if '
                    'the layout was saved by a version prior to 1.4.0 it must '
                    'be recreated.')
        util.eprint(str(e))
    finally:
        # Map all unmapped windows. We use finally because we don't want the
        # user to lose their windows no matter what.
        for window_id in window_ids:
            xdo_map_window(window_id)


def build_layout(tree, swallow, app_specific):
    """
    Builds a restorable layout tree with basic Python data structures which are
    JSON serialisable.
    """
    processed = treeutils.process_node(tree, swallow, app_specific)
    return processed


def is_placeholder(container):
    """
    Check if a container is a placeholder window.

    Args:
        container: The container to check.
    """
    return container['swallows'] not in [[], None]


def xdo_unmap_window(window_id):
    command = shlex.split(f'xdotool windowunmap {window_id}')
    subprocess.call(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )


def xdo_map_window(window_id):
    command = shlex.split(f'xdotool windowmap {window_id}')
    subprocess.call(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )


def xdo_kill_window(window_id):
    command = shlex.split(f'xdotool windowkill {window_id}')
    subprocess.call(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
