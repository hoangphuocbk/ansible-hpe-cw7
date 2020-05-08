#!/usr/bin/python

DOCUMENTATION = """
---

module: comware_install_config2
short_description: Execute CLI commands on Comware 7 devices from an input file
description:
    - Execute CLI commands on Comware 7 devices
version_added: 1.8
category: Feature (RW)
notes:
    - This module is not idempotent
    - config_file MUST be a valid FULL config file for a given device.
options:
    type:
        description:
            - State whether the commands are display (user view)
              or configure (system view) commands.  Display and
              show are the same thing.
        required: true
        default: null
        choices: ['display', 'config', 'show']
        aliases: []
    config_file:
        description:
            - File that will be sent to the device.  Relative path is
              location of Ansible playbook.  Recommended to use
              absolute path.
        required: true
        default: null
        choices: []
        aliases: []
    port:
        description:
            - NETCONF port number
        required: false
        default: 830
        choices: []
        aliases: []
    hostname:
        description:
            - IP Address or hostname of the Comware 7 device that has
              NETCONF enabled
        required: true
        default: null
        choices: []
        aliases: []
    username:
        description:
            - Username used to login to the switch
        required: true
        default: null
        choices: []
        aliases: []
    password:
        description:
            - Password used to login to the switch
        required: true
        default: null
        choices: []
        aliases: []

"""

EXAMPLES = """

# install config file that will be installed
- comware_install_config2:
    config_file: "/home/ansible/projects/pyhpecw7comware/newconfig.cfg"
    type: config
    username: "{{ username }}"
    password: "{{ password }}"
    hostname: "{{ inventory_hostname }}"

"""

import difflib
import os
import socket
import sys

try:
    HAS_PYHP = True
    from pyhpecw7.comware import HPCOM7
    from pyhpecw7.errors import *
except ImportError as ie:
    HAS_PYHP = False


def safe_fail(module, device=None, **kwargs):
    if device:
        device.close()
    module.fail_json(**kwargs)


def safe_exit(module, device=None, **kwargs):
    if device:
        device.close()
    module.exit_json(**kwargs)


def process_diff(previous_config, current_config):
    changed_commands = []
    list_diff = []
    diff = difflib.unified_diff(
        previous_config,
        current_config,
        fromfile="previous_config",
        tofile="current_config")
    last_line = ''
    for line in list(diff)[2:]:
        line.strip()
        if line[0] == '-' and line[1:].startswith('service-instance'):
            changed_commands.append(last_line[1:])
            changed_commands.append('undo ' + line[1:])
            changed_commands.append('quit\n')
        if line[0] == '-' and line[1:].startswith('ip route-static vpn-instance'):
            changed_commands.append('undo ' + line[1:])
        if line[0] == '-' and line[1:].startswith('vsi'):
            changed_commands.append('undo ' + line[1:])
        if line[0] == '-' and line[1:].startswith('ip vpn-instance'):
            if last_line[1:].startswith('bgp'):
                changed_commands.append(last_line[1:])
                changed_commands.append('undo ' + line[1:])
                changed_commands.append('quit\n')
            else:
                changed_commands.append('undo ' + line[1:])
        if line[0] == '-' and line[1:].startswith('interface Vsi-interface'):
            changed_commands.append('undo ' + line[1:])
        if line[0] == '-' and line[1:].startswith('interface Tunnel'):
            changed_commands.append('undo ' + line[1:])
        last_line = line

        if line[0] in ['-', '+'] and len(line) > 1:
            list_diff.append(line)
    return list_diff, changed_commands


def main():
    module = AnsibleModule(
        argument_spec=dict(
            type=dict(required=True, choices=['display', 'show', 'config']),
            config_file=dict(required=True, type='str'),
            previous_config_file=dict(required=False, type='str'),
            previous_config_content=dict(required=False, type='str'),
            port=dict(default=830, type='int'),
            hostname=dict(required=True),
            username=dict(required=True),
            password=dict(required=True),
            is_delete=dict(required=True)
        ),
        supports_check_mode=True
    )

    if not HAS_PYHP:
        safe_fail(module, msg='There was a problem loading from the pyhpecw7 '
                              + 'module.', error=str(ie), path=str(sys.path))

    username = module.params['username']
    password = module.params['password']
    port = module.params['port']
    hostname = socket.gethostbyname(module.params['hostname'])

    device_args = dict(host=hostname, username=username,
                       password=password, port=port)

    device = HPCOM7(**device_args)

    ctype = module.params['type']
    config_file = module.params['config_file']
    previous_config_file = module.params['previous_config_file']
    previous_config_content = module.params['previous_config_content']
    is_delete = module.params['is_delete']

    changed = False
    config_file_exists = False
    if os.path.isfile(config_file):
        config_file_exists = True
    else:
        safe_fail(module, msg='Cannot find/access config_file:\n{0}'.format(
            config_file))

    try:
        device.open()
    except ConnectionError as e:
        safe_fail(module, device, msg=str(e),
                  descr='error during device open')

    commands = []
    list_diff = []
    # This part is used to update virtual interface, vsi and ip vpn-instance
    if str(is_delete).lower() == 'false':
        previous_config = ''
        if previous_config_content:
            previous_config = previous_config_content.split('\n')
        elif os.path.isfile(previous_config_file):
            with open(previous_config_file, 'r') as pf:
                previous_config = pf.read().splitlines()

        with open(config_file, 'r') as cf:
            current_config = cf.read().splitlines()

        list_diff, changed_commands = process_diff(previous_config, current_config)
        commands += changed_commands

    if config_file_exists:
        if str(is_delete).lower() == 'true':
            with open(config_file) as fp:
                for line in fp:
                    commands.append(line.rstrip())

        elif str(is_delete).lower() == 'false' and len(list_diff) > 0:
            with open(config_file) as fp:
                for line in fp:
                    commands.append(line.rstrip())
        else:
            # When there are no changes, we don't need to add configuration
            commands.append("# There are no changes")

    response = None

    proposed = dict(type=ctype, command=commands)

    if isinstance(commands, list):
        config_string = ';'.join(commands)
    else:
        config_string = commands

    if module.check_mode:
        safe_exit(module, device, changed=True,
                  config_string=config_string)

    try:
        if ctype in ['show', 'display']:
            response = device.cli_display(commands)
        elif ctype in ['config']:
            response = device.cli_config(commands)
    except PYHPError as e:
        safe_fail(module, device, msg=str(e),
                  descr='error during execution')

    changed = True

    results = {}
    results['proposed'] = proposed
    results['config_string'] = config_string
    results['changed'] = changed
    results['end_state'] = 'N/A for this module.'
    results['response'] = response
    results['commands'] = commands
    results['list_diff'] = list_diff

    safe_exit(module, device, **results)


from ansible.module_utils.basic import *

main()


