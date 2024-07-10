from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Literal, get_args

import fire
from dataclasses_json import dataclass_json
from hcloud import Client, APIException
from hcloud.firewalls import FirewallRule

DIRECTIONS = Literal['in', 'out']
PROTOCOLS = Literal['udp', 'tcp']


@dataclass_json
@dataclass
class SerializableRule:
    direction: str
    protocol: str
    source_ips: list[str]
    port: str | None = None,
    destination_ips: list[str] | None = None,
    description: str | None = None,

    @classmethod
    def from_rule(cls, rule: FirewallRule) -> SerializableRule:
        return cls(**{slot: getattr(rule, slot) for slot in rule.__slots__})

    def to_rule(self) -> FirewallRule:
        return FirewallRule(**{slot: getattr(self, slot) for slot in FirewallRule.__slots__})


class HetznerFirewall:
    def __init__(self, client: Client, firewall_name='dns-filtered-fw'):
        self._firewall = client.firewalls.get_by_name(firewall_name)

    def save(self, dir: str):
        file_path = f'{os.path.join(dir, self._firewall.name)}_rules.json'
        sr = list(map(lambda r: SerializableRule.from_rule(r), self._firewall.rules))
        with open(file_path, 'w') as json_file:
            json.dump(list(map(lambda x: x.to_dict(), sr)), json_file)
        print(f'written {len(sr)} rules to {file_path}')

    def merge_update(self, rules_file: str,
                     description: str,
                     direction: DIRECTIONS,
                     protocols: list[PROTOCOLS],
                     source_ips: list[str],
                     port: str | None = None,
                     destination_ips: list[str] = (),
                     ):

        if direction not in get_args(DIRECTIONS):
            raise ValueError(f'direction must be one of {get_args(DIRECTIONS)}, was: {direction}')
        if len(protocols) < 1 or any(p not in get_args(PROTOCOLS) for p in protocols):
            raise ValueError(f'protocols must be one of {get_args(PROTOCOLS)}, was: {protocols}')
        if not isinstance(port, str):
            port = str(port)

        rules = self._load_rules(rules_file)

        print(f'loaded {len(rules)} rules from {rules_file}')

        new_rules = list(filter(lambda r: r.description != description, rules))
        for protocol in protocols:
            new_rules.append(
                SerializableRule(description=description, direction=direction, protocol=protocol, source_ips=source_ips,
                                 port=port, destination_ips=destination_ips))
        self._update_rules(new_rules)

    def file_update(self, rules_file: str):
        rules = self._load_rules(rules_file)
        print(f'loaded {len(rules)} rules from {rules_file}')
        self._update_rules(rules)

    def _update_rules(self, rules):
        print(f'updating {self._firewall.name} with {len(rules)} rules')

        try:
            actions = self._firewall.set_rules(list(map(lambda r: r.to_rule(), rules)))
            for action in actions:
                print(f'{action.command}: {action.status}')
        except APIException as e:
            print(f'ERROR performing firewall update: {e.code}')
            print(e.message)
            print(e.details)

    def _load_rules(self, rules_file: str):
        with open(rules_file, 'r') as json_file:
            json_list = json.load(json_file)
            return list(map(lambda x: SerializableRule.from_dict(x), json_list))



class HetznerServer:
    def __init__(self):
        self._client = Client(token=os.getenv('API_TOKEN'))
        self.firewall = HetznerFirewall(self._client)


if __name__ == '__main__':
    fire.Fire(HetznerServer)
