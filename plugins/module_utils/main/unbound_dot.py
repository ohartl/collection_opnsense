from ansible.module_utils.basic import AnsibleModule

from ansible_collections.ansibleguy.opnsense.plugins.module_utils.helper.main import \
    is_ip, valid_hostname, get_matching, validate_port, is_true, to_digit, \
    get_simple_existing
from ansible_collections.ansibleguy.opnsense.plugins.module_utils.base.api import \
    Session
from ansible_collections.ansibleguy.opnsense.plugins.module_utils.helper.unbound import \
    validate_domain, reload


class DnsOverTls:
    CMDS = {
        'add': 'addForward',
        'del': 'delForward',
        'set': 'setForward',
        'search': 'get',
    }
    API_KEY = 'dot'
    API_MOD = 'unbound'
    API_CONT = 'settings'
    API_CONT_REL = 'service'
    API_CMD_REL = 'reconfigure'
    CHANGE_CHECK_FIELDS = ['domain', 'target', 'enabled', 'port', 'verify']

    def __init__(self, module: AnsibleModule, result: dict, session: Session = None):
        self.m = module
        self.p = module.params
        self.r = result
        self.s = Session(module=module) if session is None else session
        self.exists = False
        self.dot = {}
        self.call_cnf = {  # config shared by all calls
            'module': self.API_MOD,
            'controller': self.API_CONT,
        }
        self.existing_dots = None

    def process(self):
        if self.p['state'] == 'absent':
            if self.exists:
                self.delete()

        else:
            if self.exists:
                self.update()

            else:
                self.create()

    def check(self):
        validate_domain(module=self.m, domain=self.p['domain'])
        validate_port(module=self.m, port=self.p['port'])

        if self.p['verify'] not in ['', None] and \
                not is_ip(self.p['verify']) and \
                not valid_hostname(self.p['verify']):
            self.m.fail_json(
                f"Verify-value '{self.p['verify']}' is neither a valid IP-Address "
                f"nor a valid hostname!"
            )

        # checking if item exists
        self._find_dot()
        self.r['diff']['after'] = self._build_diff_after()

    def _find_dot(self):
        if self.existing_dots is None:
            self.existing_dots = self._search_call()

        match = get_matching(
            module=self.m, existing_items=self.existing_dots,
            compare_item=self.p, match_fields=['domain', 'target'],
            simplify_func=self._simplify_existing,
        )

        if match is not None:
            self.dot = match
            self.exists = True
            self.r['diff']['before'] = self.dot
            self.call_cnf['params'] = [self.dot['uuid']]

    def get_existing(self) -> list:
        return get_simple_existing(
            entries=self._search_call(),
            simplify_func=self._simplify_existing
        )

    def _search_call(self) -> list:
        dots = []
        raw = self.s.get(cnf={
            **self.call_cnf, **{'command': self.CMDS['search']}
        })['unbound']['dots'][self.API_KEY]

        if len(raw) > 0:
            for uuid, dot in raw.items():
                if is_true(dot['type']['dot']['selected']):
                    dot.pop('type')
                    dot['uuid'] = uuid
                    dots.append(dot)

        return dots

    def create(self):
        self.r['changed'] = True

        if not self.m.check_mode:
            self.s.post(cnf={
                **self.call_cnf, **{
                    'command': self.CMDS['add'],
                    'data': self._build_request(),
                }
            })

    def update(self):
        # checking if changed
        for field in self.CHANGE_CHECK_FIELDS:
            if str(self.dot[field]) != str(self.p[field]):
                self.r['changed'] = True
                break

        # update if changed
        if self.r['changed']:
            if self.p['debug']:
                self.m.warn(f"{self.r['diff']}")

            if not self.m.check_mode:
                self.s.post(cnf={
                    **self.call_cnf, **{
                        'command': self.CMDS['set'],
                        'data': self._build_request(),
                    }
                })

    @staticmethod
    def _simplify_existing(dot: dict) -> dict:
        # makes processing easier
        return {
            'uuid': dot['uuid'],
            'domain': dot['domain'],
            'target': dot['server'],
            'port': int(dot['port']),
            'verify': dot['verify'],
            'enabled': is_true(dot['enabled']),
        }

    def _build_diff_after(self) -> dict:
        return {
            'uuid': self.dot['uuid'] if 'uuid' in self.dot else None,
            'domain': self.p['domain'],
            'target': self.p['target'],
            'port': self.p['port'],
            'verify': self.p['verify'],
            'enabled': self.p['enabled'],
        }

    def _build_request(self) -> dict:
        return {
            self.API_KEY: {
                'type': 'dot',
                'enabled': to_digit(self.p['enabled']),
                'domain': self.p['domain'],
                'server': self.p['target'],
                'verify': self.p['verify'],
                'port': self.p['port'],
            }
        }

    def delete(self):
        self.r['changed'] = True
        self.r['diff']['after'] = {}

        if not self.m.check_mode:
            self._delete_call()

            if self.p['debug']:
                self.m.warn(f"{self.r['diff']}")

    def _delete_call(self) -> dict:
        return self.s.post(cnf={**self.call_cnf, **{'command': self.CMDS['del']}})

    def reload(self):
        # reload running config
        reload(self)