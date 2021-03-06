# -*- coding: utf-8 -*-
# Copyright 2018 GIG Technology NV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# @@license_version:1.4@@
import json
import re
from datetime import datetime
from functools import lru_cache
from json import JSONDecodeError
from typing import Union, Iterator, Any

import certifi
import urllib3

HUMAN_READABLE_TAG_REGEX = re.compile('(.*?)\\s*{.*\\}')
UNKNOWN = 'unknown'

poolmngr = urllib3.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())


class Measurements(object):
    ALL_USERS = 'rogerthat.all_users'
    API_CALLS = 'rogerthat.api_calls'
    CALLBACK_API = 'rogerthat.callback_api'
    CREATED_APPS = 'rogerthat.created_apps'
    RELEASED_APPS = 'rogerthat.released_apps'
    CLIENT_CALL = 'rogerthat.client_call'
    MESSAGES = 'rogerthat.messages'
    TOTAL_SERVICES = 'rogerthat.total_services'


def _get_time(value: dict) -> str:
    return datetime.utcfromtimestamp(value['timestamp']).isoformat() + 'Z'


def parse_to_human_readable_tag(tag: str) -> Union[str, None]:
    if not tag:
        return None

    if tag.startswith('{') and tag.endswith('}'):
        try:
            tag_dict = json.loads(tag)
        except (JSONDecodeError, TypeError):
            return tag
        return tag_dict.get('__rt__.tag', tag)

    m = HUMAN_READABLE_TAG_REGEX.match(tag)
    if m:
        return m.group(1)

    return tag


def callback_api(value: dict) -> Iterator[Any]:
    request_data = value.get('request_data', {})
    function_type = value.get('function') or request_data.get('method')
    timestamp = _get_time(value)
    params = request_data.get('params', {})
    user_email = UNKNOWN
    app_id = UNKNOWN
    tag = parse_to_human_readable_tag(params.get('tag'))
    if params.get('user_details'):
        if isinstance(params['user_details'], list):
            user_details = params['user_details'][0]
        else:
            user_details = params['user_details']
        app_id = user_details['app_id']
        user_email = user_details['email']
    if tag and tag.startswith('{'):
        tag = None
    tags = {
        'tag': tag,
        'app': app_id,
        'function': function_type,
    }
    if function_type == 'system.api_call':
        tags['method'] = params.get('method')
    yield {
        'measurement': Measurements.CALLBACK_API,
        'tags': tags,
        'time': timestamp,
        'fields': {
            'user': user_email,
            'service': value.get('user')
        }
    }


def app(value: dict) -> Iterator[Any]:
    # {
    #   "timestamp": 1518603982,
    #   "request_data": {
    #     "a": [
    #       "68443b87-e849-4406-b52f-d0413a433445"
    #     ],
    #     "c": [],
    #     "r": [
    #       {
    #         "s": "success",
    #         "r": {
    #           "received_timestamp": 1518603981
    #         },
    #         "av": 1,
    #         "ci": "7ff631c7-1171-11e8-972f-316b0a392f23",
    #         "t": 1518603981
    #       }
    #     ],
    #     "av": 1
    #   },
    #   "type": "app",
    #   "response_data": {
    #     "a": [
    #       "7ff631c7-1171-11e8-972f-316b0a392f23"
    #     ],
    #     "ap": "https://rogerthat-server.appspot.com/json-rpc",
    #     "av": 1,
    #     "t": 1518603982,
    #     "more": false
    #   },
    #   "user": "c356f0adc203397a9d89ff9e1a6e6b54:em-be-idola"
    # }
    request_data = value.get('request_data', {})
    # Sometimes, a log line of type 'channel' is too long so it has to 'type' property, so we need to ignore those here
    if value.get('type') is None and type(request_data) is str:
        return
    user = value.get('user', UNKNOWN)
    if ':' in user:
        user, app_id = user.split(':', 1)
    elif user:
        app_id = 'rogerthat'
    else:
        app_id = UNKNOWN
    # Results
    for request in request_data.get('r', []):
        if request.get('item', {}).get('r'):
            if request['item']['r'].keys() == ['received_timestamp']:
                yield {
                    'measurement': Measurements.MESSAGES,
                    'tags': {
                        'app': app_id,
                    },
                    'time': _get_time(value),
                    'fields': {
                        'user': user
                    }
                }
    client_calls = value.get('response_data', {}).get('c', []) + request_data.get('c', [])
    for call in client_calls:
        if 't' in call:
            yield {
                'measurement': Measurements.CLIENT_CALL,
                'tags': {
                    'app': app_id,
                    'type': call.get('f', UNKNOWN)
                },
                'time': datetime.utcfromtimestamp(int(call['t'])).isoformat() + 'Z',
                'fields': {
                    'user': user
                }
            }


def api(value: dict) -> Iterator[Any]:
    # value = {
    #     u'function': u'system.get_identity',
    #     u'success': True,
    #     u'user': u'5c31adac01cad92a435c44f514798d88',
    #     u'type': u'api',
    #     u'request_data': {},
    #     u'response_data': {...},
    #     u'timestamp': 1518583750
    # }
    tags = {
        'method': value.get('function'),
    }
    fields = {
        'success': value.get('success', True)
    }

    if 'user' in value:
        tags['app_id'] = _get_app_id_by_service_hash(value['user'])
        fields['service'] = value['user']
    yield {
        'measurement': Measurements.API_CALLS,
        'tags': tags,
        'time': _get_time(value),
        'fields': fields
    }


def web(value: dict) -> Iterator[dict]:
    # We actually don't care for this
    yield from []


def web_channel(value: dict) -> Iterator[dict]:
    # We actually don't care for this
    yield from []


@lru_cache(maxsize=1000)
def _get_app_id_by_service_hash(service_hash: str) -> Union[str, None]:
    url = 'https://rogerth.at/unauthenticated/service-app'
    fields = {'user': service_hash}
    res = poolmngr.request('GET', url, fields)  # type: urllib3.HTTPResponse
    if res.status != 200:
        raise Exception('Failed to get app_id for service hash %s', service_hash)
    return json.loads(res.data)['app_id']


def created_apps(value: dict) -> Iterator[dict]:
    # value = {
    #     "request_data": {
    #         "YSAAA": {"BE": 1},
    #         "Enterprise": {"BE": 4},
    #         "Rogerthat": {"BE": 1},
    #         "City app": {"BE": 24, "CD": 1}
    #     },
    #     "timestamp": 1520985600.0,
    #     "type": "rogerthat.created_apps"
    # }
    for app_type, values in value.get('request_data', {}).items():
        for country_code, amount in values.items():
            yield {
                'measurement': Measurements.CREATED_APPS,
                'tags': {
                    'type': app_type,
                    'country': country_code
                },
                'time': _get_time(value),
                'fields': {
                    'amount': amount
                }
            }


def released_apps(value: dict) -> Iterator[dict]:
    # value = {
    #     "request_data": {
    #         "YSAAA": {"BE": 1},
    #         "Rogerthat": {"BE": 1},
    #         "City app": {"BE": 1, "CD": 1}
    #     },
    #     "timestamp": 1520985600.0,
    #     "type": "rogerthat.released_apps"
    # }
    for app_type, values in value.get('request_data', {}).items():
        for country_code, amount in values.items():
            yield {
                'measurement': Measurements.RELEASED_APPS,
                'tags': {
                    'type': app_type,
                    'country': country_code
                },
                'time': _get_time(value),
                'fields': {
                    'amount': amount
                }
            }


def all_users(value: dict) -> Iterator[dict]:
    for app_id, amount in value.get('request_data', {}).items():
        yield {
            'measurement': Measurements.ALL_USERS,
            'tags': {
                'app': app_id,
            },
            'time': _get_time(value),
            'fields': {
                'amount': amount
            }
        }


def total_services(value: dict) -> Iterator[dict]:
    for app_id, values in value.get('request_data', {}).items():
        for organization_type, amount in values.items():
            yield {
                'measurement': Measurements.TOTAL_SERVICES,
                'tags': {
                    'type': organization_type,
                    'app': app_id
                },
                'time': _get_time(value),
                'fields': {
                    'amount': amount
                }
            }
