#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2017, cytopia <cytopia@everythingcli.org>
#
# This module is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this software.  If not, see <http://www.gnu.org/licenses/>.
#
tesla_debuglog = ''

ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'supported_by': 'community',
                    'status': ['preview']}

DOCUMENTATION = '''
---
module: tesla
author: David Taylor (@syspimp)

short_description: Ansible module to abstract the Tesla API
description:
    - Anisble implementation of the Tesla Public API
version_added: "2.4"
options:
    source:
        description:
            - The source input to tesla. Can be a string, contents of a file or output from a command, depending on I(source_type).
        required: true
        default: null
        aliases: []

    target:
        description:
            - The target input to tesla. Can be a string, contents of a file or output from a command, depending on I(target_type).
        required: true
        default: null
        aliases: []

    source_type:
        description:
            - Specify the input type of I(source).
        required: true
        default: string
        choices: [ string, file, command ]
        aliases: []

    target:
        description:
            - Specify the input type of I(target).
        required: true
        default: string
        choices: [ string, file, command ]
        aliases: []
'''

EXAMPLES = '''
# Tesla compare two strings
- tesla:
    source: "foo"
    target: "bar"
    source_type: string
    target_type: string

# Tesla compare variable against template file (as strings)
- tesla:
    source: "{{ lookup('template', tpl.yml.j2) }}"
    target: "{{ my_var }}"
    source_type: string
    target_type: string

# Tesla compare string against command output
- tesla:
    source: "/bin/bash"
    target: "which bash"
    source_type: string
    target_type: command

# Tesla compare file against command output
- tesla:
    source: "/etc/hostname"
    target: "hostname"
    source_type: file
    target_type: command
'''

RETURN = '''
tesla:
    description: tesla output
    returned: success
    type: string
    sample: + this line was added
'''
from ansible.module_utils.basic import *
import argparse
import base64
import json
import os
import random
import requests
import time
import sys
from datetime import datetime, timedelta
# Only used for debugging.
from pprint import pprint


# Global vars for use by various functions.
base_url = 'https://owner-api.teslamotors.com/api/1/vehicles'
oauth_url = 'https://owner-api.teslamotors.com/oauth/token'
SETTINGS = {
    'DEBUG': False,
    'tesla_email': '',
    'tesla_password': '',
    'tesla_access_token': '',
    'tesla_refresh_token': '',
    'tesla_vin': '',
    # If these two stop working, updated ones can be found linked from this page:
    # https://tesla-api.timdorr.com/api-basics/authentication
    'TESLA_CLIENT_ID': '81527cff06843c8634fdc09e8ac0abefb46ac849f38fe1e431c2ef2106796384',
    'TESLA_CLIENT_SECRET': 'c7257eb71a564034f9419ee651c7d0e5f7aa6bfbd18bafb5c5c033b093bb2fa3',
}
date_format = '%Y-%m-%d %H:%M:%S'
# This dict stores the data that will be written to /tmp/tesla_api.json.
# we load its contents from disk at the start of the script, and save them back
# to the disk whenever the contents change.
tesla_api_json = {
    'access_token': '',
    'refresh_token': '',
    'id': 0,
    'vehicle_id': 0,
    'token_created_at': datetime.strptime('1970-01-01 12:00:00', date_format)
}

def _execute_request(url=None, method=None, data=None, require_vehicle_online=True):
    """
    Wrapper around requests to the Tesla REST Service which ensures the vehicle is online before proceeding
    :param url: the url to send the request to
    :param method: the request method ('GET' or 'POST')
    :param data: the request data (optional)
    :return: JSON response
    """
    if require_vehicle_online:
        vehicle_online = False
        while not vehicle_online:
            _log("Attempting to wake up Vehicle (ID:{})".format(tesla_api_json['id']))
            result = _rest_request(
                '{}/{}/wake_up'.format(base_url, tesla_api_json['id']),
                method='POST'
            )

            # Tesla REST Service sometimes misbehaves... this seems to be caused by an invalid/expired auth token
            # TODO: Remove auth token and retry?
            if result['response'] is None:
                output = dict(
                    changed=False,
                    msg="Fatal Error: Tesla REST Service returned an invalid response",
                    skipped=True
                )
                module.exit_json(**output)

            vehicle_online = result['response']['state'] == "online"
            if vehicle_online:
                _log("Vehicle (ID:{}) is Online".format(tesla_api_json['id']))
            else:
                _log("Vehicle (ID:{}) is Asleep; Waiting 5 seconds before retry...".format(tesla_api_json['id']))
                time.sleep(5)

    if url is None:
        return result['response']['state']

    json_response = _rest_request(url, method, data)

    # Error handling
    error = json_response.get('error')
    if error:
        # Log error and die
        #_error(json.dumps(json_response, indent=2))
        #sys.exit(1)
        output = dict(
             changed=False,
             msg="Fatal Error: Tesla REST Service returned an error response",
             skipped=True
        )
        module.exit_json(**output)

    return json_response

def _rest_request(url, method=None, data=None):
    """
    Executes a REST request
    :param url: the url to send the request to
    :param method: the request method ('GET' or 'POST')
    :param data: the request data (optional)
    :return: JSON response
    """
    # set default method value
    if method is None:
        method = 'GET'
    # set default data value
    if data is None:
        data = {}
    headers = {
      'Authorization': 'Bearer {}'.format(_get_api_token()),
      'User-Agent': 'github.com/marcone/teslausb',
    }

    _log("Sending {} Request: {}; Data: {}".format(method, url, data))
    if method.upper() == 'GET':
        response = requests.get(url, headers=headers)
    elif method.upper() == 'POST':
        response = requests.post(url, headers=headers, data=data)
    else:
        raise ValueError('Unsupported Request Method: {}'.format(method))
    if not response.text:
        output = dict(
             changed=False,
             msg="Fatal Error: Tesla REST Service failed to return a response, access token may have expired",
             skipped=True
        )
        module.exit_json(**output)
    json_response = response.json()

    # log full JSON response for debugging
    _log(json.dumps(json_response, indent=2))

    return json_response

def _get_api_token():
    """
    Retrieves the API access token, either from /tmp/tesla_api.json,
    SETTINGS, or from the Tesla API by using the credentials in SETTINGS.
    If those are also not available, kill the script, since it can't continue.
    """
    # If the token was already saved, work with that.
    if tesla_api_json['access_token']:
        # Due to what appears to be a bug with the fake-hwclock service,
        # sometimes the system thinks it's still November 2016. If that's the
        # case, we can't accurately determine the age of the token, so we just
        # use it. Later executions of the script should run after the date has
        # updated correctly, at which point we can properly compare the dates.
        now = datetime.now()
        if now.year < 2019: # This script was written in 2019.
            return tesla_api_json['access_token']

        # If it's been 30 days since the token was created, refresh it.
        if now >= tesla_api_json['token_created_at'] + timedelta(days=30):
            _refresh_api_token(tesla_api_json['refresh_token'])
        return tesla_api_json['access_token']

    # If there's no token in tesla_api_json, but the user provided a
    # token in teslausb_setup_variables.conf, refresh the provided token to save
    # the most up-to-date API data into tesla_api_json.
    elif SETTINGS['tesla_access_token']:
        _refresh_api_token(SETTINGS['tesla_refresh_token'])
        return tesla_api_json['access_token']

    # If the access token is not already stored in tesla_api_json AND the
    # user didn't provide a token pair in the teslausb_setup_variables.conf,
    # attempt to use the login credentials from teslausb_setup_variables.conf
    # to create a new token pair, if they exist.
    elif SETTINGS['tesla_email'] and SETTINGS['tesla_password']:
        # Create a new pair of tokens from the OAuth API.
        data = {
          'grant_type': 'password',
          'client_id': SETTINGS['TESLA_CLIENT_ID'],
          'client_secret': SETTINGS['TESLA_CLIENT_SECRET'],
          'email': SETTINGS['tesla_email'],
          'password': SETTINGS['tesla_password']
        }
        headers = {
            'User-Agent': 'github.com/marcone/teslausb',
        }
        _log('Retrieving new API token...')
        # Useful for debugging credential issues
        _log("data = {}".format(data))
        response = requests.post(oauth_url, headers=headers, data=data)
        result = response.json()

        if 'access_token' not in result:
            _error('Unable to create access token:')
            _error(result)
            sys.exit(1)
        _log('Success! New Tokens:\naccess: {}\nrefresh: {}'.format(
            result['access_token'], result['refresh_token']
        ))
        # Write the tokens to tesla_api_json, which is where the rest of the
        # code retrieves them from.
        tesla_api_json['access_token'] = result['access_token']
        tesla_api_json['refresh_token'] = result['refresh_token']
        tesla_api_json['token_created_at'] = datetime.now()
        _write_tesla_api_json()
        return tesla_api_json['access_token']

    _error('Unable to perform Tesla API functions: no credentials or token.')
    sys.exit(1)

def _refresh_api_token(refresh_token):
    """
    Given the specified refresh token, perform a refresh and store the new
    access_token and refresh_token into tesla_api_json.
    """
    # Refresh the token.
    data = {
      'grant_type': 'refresh_token',
      'client_id': SETTINGS['TESLA_CLIENT_ID'],
      'client_secret': SETTINGS['TESLA_CLIENT_SECRET'],
      'refresh_token': refresh_token,
    }
    headers = {
        'User-Agent': 'github.com/marcone/teslausb',
    }
    _log('Refreshing API token...')
    response = requests.post(oauth_url, headers=headers, data=data)
    result = response.json()
    if 'access_token' not in result:
        _error('Unable to refresh access token:')
        _error(result)
        sys.exit(1)
    _log('Success! New Tokens:\naccess: {}\nrefresh: {}'.format(
        result['access_token'], result['refresh_token']
    ))
    tesla_api_json['access_token'] = result['access_token']
    tesla_api_json['refresh_token'] = result['refresh_token']
    tesla_api_json['token_created_at'] = datetime.now()
    _write_tesla_api_json()

def _get_id():
    """
    Put the vehicle's ID into tesla_api_json['id'].
    """
    # If it was already set by _load_tesla_api_json(), and a new
    # VIN or name wasn't specified on the command line, we're done.
    if tesla_api_json['id'] and tesla_api_json['vehicle_id']:
      if SETTINGS['tesla_name'] == '' and SETTINGS['tesla_vin'] == '':
        return

    # Call list_vehicles() and use the provided name or VIN to get the vehicle ID.
    result = list_vehicles()
    for vehicle_dict in result['response']:
        if ( vehicle_dict['vin'] == SETTINGS['tesla_vin']
          or vehicle_dict['display_name'] == SETTINGS['tesla_name']
          or ( SETTINGS['tesla_vin'] == '' and SETTINGS['tesla_name'] == '')):
            tesla_api_json['id'] = vehicle_dict['id_s']
            tesla_api_json['vehicle_id'] = vehicle_dict['vehicle_id']
            _log('Retrieved Vehicle ID from Tesla API.')
            _write_tesla_api_json()
            return

    _error('Unable to retrieve vehicle ID: Unknown name or VIN. Cannot continue.')
    sys.exit(1)


def _load_tesla_api_json():
    """
    Load the data stored in /tmp/tesla_api.json, if it exists.
    If it doesn't exist, write a file to that location with default values.
    """
    try:
        with open('/tmp/tesla_api.json', 'r') as f:
            _log('Loading tmp data from disk...')
            json_string = f.read()
    except FileNotFoundError:
        # Write a dict with the default data to the file.
        _log("Mutable data didn't exist, writing defaults...")
        _write_tesla_api_json()
    else:
        def datetime_parser(dct):
            # Converts any string with the appropriate format in the parsed JSON
            # dict into a datetime object.
            for k, v in dct.items():
                try:
                    dct[k] = datetime.strptime(v, date_format)
                except (TypeError, ValueError):
                    pass
            return dct


def _write_tesla_api_json():
    """
    Write the contents of the tesla_api_json dict to /tmp/tesla_api.json.
    """
    def convert_dt(obj):
        # Converts datetime objects into 'YYYY-MM-DD HH:MM:SS' strings, since
        # json.dumps() can't serialize them itself.
        if isinstance(obj, datetime):
            return obj.strftime(date_format)

    with open('/tmp/tesla_api.json', 'w') as f:
        _log('Writing /tmp/tesla_api.json...')
        json_string = json.dumps(tesla_api_json, indent=2, default=convert_dt)
        f.write(json_string)


def _get_log_timestamp():
    # I can't figure out how to get a timezone aware version of now() in
    # Python 2.7 without pytz, so I kludged this together. It outputs the
    # same timestamp format as the other logging done by TeslaUSB's code.
    zone = time.tzname[time.daylight]
    return datetime.now().strftime('%a %d %b %H:%M:%S {} %Y'.format(zone))


def _log(msg, flush=True):
    global tesla_debuglog
    if SETTINGS['DEBUG']:
        tesla_debuglog = tesla_debuglog + msg
        #tmpdebug=print("{}: {}".format(_get_log_timestamp(), msg), flush=flush)
        #if msg:
        #  print("%s" % msg)
        #  tesla_debuglog = msg


def _error(msg, flush=True):
    """
    It's _log(), but for errors, so it always prints.
    """
    print("{}: {}".format(_get_log_timestamp(), msg), file=sys.stderr, flush=flush)

######################################
# API GET Functions
######################################
def list_vehicles():
    return _execute_request(base_url, None, None, False)


def get_service_data():
    return _execute_request(
        '{}/{}/service_data'.format(base_url, tesla_api_json['id'])
    )


def get_vehicle_summary():
    return _execute_request(
        '{}/{}'.format(base_url, tesla_api_json['id'])
    )


def get_vehicle_legacy_data():
    return _execute_request(
        '{}/{}/data'.format(base_url, tesla_api_json['id'])
    )


def get_nearby_charging():
    return _execute_request(
        '{}/{}//nearby_charging_sites'.format(base_url, tesla_api_json['id'])
    )


def get_vehicle_data():
    return _execute_request(
        '{}/{}/vehicle_data'.format(base_url, tesla_api_json['id'])
    )


def get_vehicle_online_state():
    return get_vehicle_data()['response']['state']


def is_vehicle_online():
    return get_vehicle_online_state() == "online"


def get_charge_state():
    return _execute_request(
        '{}/{}/data_request/charge_state'.format(base_url, tesla_api_json['id'])
    )


def get_climate_state():
    return _execute_request(
        '{}/{}/data_request/climate_state'.format(base_url, tesla_api_json['id'])
    )


def get_drive_state():
    return _execute_request(
        '{}/{}/data_request/drive_state'.format(base_url, tesla_api_json['id'])
    )


def get_gui_settings():
    return _execute_request(
        '{}/{}/data_request/gui_settings'.format(base_url, tesla_api_json['id'])
    )


def get_vehicle_state():
    return _execute_request(
        '{}/{}/data_request/vehicle_state'.format(base_url, tesla_api_json['id'])
    )


######################################
# Custom Functions
######################################
def get_odometer():
    data = get_vehicle_state()
    return int(data['response']['odometer'])


def is_car_locked():
    data = get_vehicle_state()
    return data['response']['locked']


def is_sentry_mode_enabled():
    data = get_vehicle_state()
    return data['response']['sentry_mode']


'''
This accesses the streaming endpoint, but doesn't
stick around to wait for continuous results.
'''
def streaming_ping():
    # the car needs to be awake for the streaming endpoint to work
    wake_up_vehicle()

    headers = {
      'User-Agent': 'github.com/marcone/teslausb',
      'Authorization': 'Bearer {}'.format(_get_api_token()),
      'Connection': 'Upgrade',
      'Upgrade': 'websocket',
      'Sec-WebSocket-Key': base64.b64encode(bytes([random.randrange(0, 256) for _ in range(0, 13)])).decode('utf-8'),
      'Sec-WebSocket-Version': '13',
    }

    url = 'https://streaming.vn.teslamotors.com/connect/{}'.format(tesla_api_json['vehicle_id'])

    _log("Sending streaming request")
    response = requests.get(url, headers=headers, stream=True)
    if not response:
        _error("Fatal Error: Tesla REST Service failed to return a response, access token may have expired")
        sys.exit(1)

    return response

######################################
# API POST Functions
######################################
def wake_up_vehicle():
    _log('Sending wakeup API command...')
    return _execute_request()


def set_charge_limit(percent):
    return _execute_request(
        '{}/{}/command/set_charge_limit'.format(base_url, tesla_api_json['id']),
        method='POST',
        data={'percent': percent}
    )

def actuate_trunk():
    result = _execute_request(
        '{}/{}/command/actuate_trunk'.format(base_url, tesla_api_json['id']),
        method='POST',
        data={'which_trunk': 'rear'}
    )
    return result['response']['result']

def actuate_frunk():
    result = _execute_request(
        '{}/{}/command/actuate_trunk'.format(base_url, tesla_api_json['id']),
        method='POST',
        data={'which_trunk': 'front'}
    )
    return result['response']['result']

def flash_lights():
    result = _execute_request(
        '{}/{}/command/flash_lights'.format(base_url, tesla_api_json['id']),
        method='POST'
    )
    return result['response']['result']

def set_sentry_mode(enabled: bool):
    """
    Activates or deactivates Sentry Mode based on the 'enabled' parameter
    :param enabled: True to Enable Sentry Mode; False to Disable Sentry Mode
    :return: True if the command was successful
    """
    _log("Setting Sentry Mode Enabled: {}".format(enabled))
    result = _execute_request(
        '{}/{}/command/set_sentry_mode'.format(base_url, tesla_api_json['id']),
        method='POST',
        data={'on': enabled}
    )
    return result['response']['result']


def enable_sentry_mode():
    """
    Enables Sentry Mode
    :return: Human-friendly String indicating command success/failure
    """
    if True == set_sentry_mode(True):
        return "Success: Sentry Mode Enabled"
    else:
        return "Failed to Enable Sentry Mode"


def disable_sentry_mode():
    """
    Disables Sentry Mode
    :return: Human-friendly String indicating command success/failure
    """
    if True == set_sentry_mode(False):
        return "Success: Sentry Mode Disabled"
    else:
        return "Failed to Disable Sentry Mode"


def toggle_sentry_mode():
    """
    Activates Sentry Mode if it is currently off, disables it if it is currently on
    :return: True if the command was successful
    """
    if is_sentry_mode_enabled():
        return disable_sentry_mode()
    else:
        return enable_sentry_mode()


######################################
# Utility Functions
######################################
def _get_api_functions():
    # Build the list of available Tesla API function names by getting the
    # callables from globals() and skipping the non-API functions.
    non_api_names = ['main', 'pprint', 'datetime', 'timedelta']
    function_names = []
    for name, func in globals().items():
        if (callable(func)
                and not name.startswith('_')
                and name not in non_api_names):
            function_names.append(name)
    function_names.sort()
    function_names_string = '\n'.join(function_names)

    return function_names_string

def _get_arg_parser():
    # Parse the CLI arguments.
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'function',
        help="The name of the function to run. Available functions are:\n {}".format(_get_api_functions()))
    parser.add_argument(
        '--arguments',
        help="Add arguments to the function by passing comma-separated key:value pairs."
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print debug output."
    )
    parser.add_argument(
        "--email",
        help="Tesla account email."
    )
    parser.add_argument(
        "--password",
        help="Tesla account password."
    )
    parser.add_argument(
        "--vin",
        help="VIN number of the car."
    )
    parser.add_argument(
        "--name",
        help="name of the car."
    )
    parser.add_argument(
        "--accesstoken",
        help="Access token to use instead of email/password"
    )
    parser.add_argument(
        "--refreshtoken",
        help="Token to refresh access token"
    )

    return parser


def shell_exec(command):
    '''
    Execute raw shell command and return exit code and output
    '''
    cpt = subprocess.Popen(command, shell=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    output = []
    for line in iter(cpt.stdout.readline, ''):
        output.append(line)

    # Wait until process terminates (without using p.wait())
    while cpt.poll() is None:
        # Process hasn't exited yet, let's wait some
        time.sleep(0.5)

    # Get return code from process
    return_code = cpt.returncode

    # Return code and output
    return return_code, output


def tesla_module_validation(module):
    '''
    Validate for correct module call/usage in ansible.
    '''
    tesla_email = module.params.get('tesla_email')
    tesla_password = module.params.get('tesla_password')
    tesla_vin = module.params.get('tesla_vin')
    tesla_name = module.params.get('tesla_name')

    # Validate creds were passed in
    if tesla_password == '' or tesla_email == '':
        module.fail_json(msg="provide the tesla email and password, and vin if you have more than one car")

    return module


def main():
    '''
    Main function
    '''
    global tesla_debuglog
    module = AnsibleModule(
        argument_spec=dict(
            tesla_email=dict(required=False, default=None, type='str'),
            tesla_password=dict(required=False, default=None, type='str'),
            tesla_vin=dict(required=False, default=None, type='str'),
            tesla_name=dict(required=False, default=None, type='str'),
            tesla_accesstoken=dict(required=False, default=None, type='str'),
            tesla_refreshtoken=dict(required=False, default=None, type='str'),
            tesla_arguments=dict(required=False, default=None, type='str'),
            tesla_debug=dict(required=False, default=None, type='str'),
            tesla_function=dict(required=True, default=None, type='str'),
        ),
        supports_check_mode=True
    )

    # Validate module
    module = tesla_module_validation(module)

    # Get ansible arguments
    tesla_email = module.params.get('telsa_email')
    tesla_password = module.params.get('tesla_password')
    tesla_vin = module.params.get('tesla_vin')
    tesla_name = module.params.get('tesla_name')
    tesla_accesstoken = module.params.get('tesla_accesstoken')
    tesla_refreshtoken = module.params.get('tesla_refreshtoken')
    tesla_arguments = module.params.get('telsa_arguments')
    tesla_debug = module.params.get('tesla_debug')
    tesla_function = module.params.get('tesla_function')

    SETTINGS['DEBUG'] = tesla_debug


    if tesla_email:
        SETTINGS['tesla_email'] = tesla_email
    else:
        SETTINGS['tesla_email'] = os.environ.get('TESLA_EMAIL', '')

    if tesla_password:
        SETTINGS['tesla_password'] = tesla_password
    else:
        SETTINGS['tesla_password'] = os.environ.get('TESLA_PASSWORD', '')

    if tesla_vin:
        SETTINGS['tesla_vin'] = tesla_vin
    else:
        SETTINGS['tesla_vin'] = os.environ.get('TESLA_VIN', '')

    if tesla_name:
        SETTINGS['tesla_name'] = tesla_name
    else:
        SETTINGS['tesla_name'] = os.environ.get('TESLA_NAME', '')

    if tesla_accesstoken:
        SETTINGS['tesla_access_token'] = tesla_accesstoken
    else:
        SETTINGS['tesla_access_token'] = os.environ.get('TESLA_ACCESS_TOKEN', '')

    if tesla_refreshtoken:
        SETTINGS['tesla_refresh_token'] = tesla_refreshtoken
    else:
        SETTINGS['tesla_refresh_token'] = os.environ.get('TESLA_REFRESH_TOKEN', '')

    # We call this now so DEBUG will be set correctly.
    _load_tesla_api_json()

    # Apply any arguments that the user may have provided.
    kwargs = {}
    if tesla_arguments:
        for kwarg_string in [arg.strip() for arg in tesla_arguments.split(',')]:
            key, value = kwarg_string.split(':')
            kwargs[key] = value
    # Render the arguments as a POST body.
    kwargs_string = ''
    if kwargs:
        kwargs_string = ', '.join(
            '{}={}'.format(key, value) for key, value in kwargs.items()
        )

    # We need to call this before calling any API function, because those need
    # to know the ID before they call _execute_request()
    _get_id()

    # Get the function by name from the globals() dict and call it with the
    # specified args.
    function = globals()[tesla_function]
    _log('Calling {}({})...'.format(tesla_function, kwargs_string))
    result = function(**kwargs)

    # Write the output of the API call to stdout, if DEBUG is true.
    is_json = False
    try:
        # check to see if result is json
        if isinstance(result, str):
            json.loads(result)
            is_json = True
    except ValueError as e:
        pass

    if is_json:
        _log(json.dumps(result, indent=2))

    if tesla_debug:
      # Ansible module returned variables
      output = dict(
          msg=tesla_debuglog,
          changed=True,
          skipped=False
      )
    else:
      # Ansible module returned variables
      output = dict(
          msg=result,
          changed=True,
          skipped=False
      )

    # Exit ansible module call
    module.exit_json(**output)


if __name__ == '__main__':
    main()

