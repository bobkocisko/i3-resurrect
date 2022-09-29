import json
import re
import shlex
import subprocess
# import psutil

from . import config
# from . import programs

# The tree node attributes that we want to save.
REQUIRED_ATTRIBUTES = [
    'border',
    'current_border_width',
    'floating',
    'fullscreen_mode',
    'geometry',
    'layout',
    'marks',
    'name',
    'orientation',
    'percent',
    'scratchpad_state',
    'sticky',
    'title_format',
    'type',
    'workspace_layout',
]


def process_node(original, swallow, app_specific = {}):
    """
    Recursive function which traverses a layout tree and builds a new tree from
    it which can be restored using append_layout and only contains attributes
    necessary for accurately restoring the layout.
    """
    processed = {}

    # Base case.
    if original is None or original == {}:
        return processed

    # Set attributes.
    for attribute in REQUIRED_ATTRIBUTES:
        if attribute in original:
            processed[attribute] = original[attribute]

    # Keep rect attribute for floating nodes.
    if 'type' in original and original['type'] == 'floating_con':
        processed['rect'] = original['rect']

    # Set swallow criteria if the node is a window.
    if 'window_properties' in original:
        processed['swallows'] = [{}]
        # Local variable for swallow criteria.
        swallow_criteria = swallow
        # Get swallow criteria from config.
        window_swallow_mappings = config.get('window_swallow_criteria', {})
        window_class = original['window_properties'].get('class', '')
        # Swallow criteria from config override the command line parameters
        # if present.
        if window_class in window_swallow_mappings:
            swallow_criteria = window_swallow_mappings[window_class]
        for criterion in swallow_criteria:
            if criterion in original['window_properties']:
                orig_prop = original['window_properties'][criterion]
                escaped = None
                if criterion == 'title':
                    kak_match = re.fullmatch(r"(.+) (\d+):(\d+) (?:\[\+\])? \d+ sel(?:s)?(?: \(\d+\))? - (.+)@\[(.+)\] - Kakoune", orig_prop)
                    if kak_match:
                        # we can assume that this is being run by a terminal
                        # so we need to get the working directory from the 
                        # child process of the terminal
                        # pid = programs.get_window_pid(original)
                        # procinfo = psutil.Process(pid)
                        # working_directory = procinfo.children()[0].cwd()
                        
                        file_path = kak_match.group(1)
                        line = kak_match.group(2)
                        column = kak_match.group(3)
                        client_name = kak_match.group(4)
                        session_name = kak_match.group(5)
                        app_specific\
                            .setdefault('kakoune_sessions', {})\
                            .setdefault(session_name, {})\
                            .setdefault('clients', {})\
                            [client_name] = {
                                # 'working_directory': working_directory,
                                'path': file_path,
                                'line': line,
                                'column': column
                            }
                        escaped = re.escape(file_path) + " " + line + ":" + column + r"  \d+ sel(?:s)?(?: \(\d+\))? - " + client_name + r"@\[" + session_name + r"\] - Kakoune"
                    else:
                        # Escape special characters in swallow criteria.
                        escaped = re.escape(orig_prop)
                else:
                    # Escape special characters in swallow criteria.
                    escaped = re.escape(orig_prop)
                # Regex formatting.
                value = f'^{escaped}$'
                processed['swallows'][0][criterion] = value

    # Recurse over child nodes (normal and floating).
    for node_type in ['nodes', 'floating_nodes']:
        if node_type in original and original[node_type] != []:
            processed[node_type] = []
            for child in original[node_type]:
                # Step case.
                processed[node_type].append(process_node(child, swallow, app_specific))

    return processed


def get_workspace_tree(workspace, numeric):
    """
    Get full workspace layout tree from i3.
    """
    root = json.loads(
        subprocess.check_output(shlex.split('i3-msg -t get_tree'))
    )
    for output in root['nodes']:
        for container in output['nodes']:
            if container['type'] != 'con':
                pass
            for ws in container['nodes']:
                # Select workspace and trigger name and num field
                if numeric:
                    if (workspace.isdigit()
                            and 'num' in ws
                            and ws['num'] == int(workspace)):
                        return ws
                elif ws['name'] == workspace:
                    return ws
    return {}


def get_leaves(container):
    """
    Recursive generator for retrieving a list of a container's leaf nodes.

    Args:
        container: The container to traverse.
    """
    # Base cases.
    if container is None:
        return

    nodes = container.get('nodes', []) + container.get('floating_nodes', [])

    # Step case.
    for node in nodes:
        if 'window_properties' in node:
            yield node
        yield from get_leaves(node)
