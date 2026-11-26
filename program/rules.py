from dataclasses import dataclass

from contract import array, fail, fields, integer, text
from program.audio import AudioClip


@dataclass(frozen=True)
class Rule:
    rule_id: str
    priority: int
    requires: tuple[str, ...]
    audio_id: str


@dataclass(frozen=True)
class GroupRules:
    group_id: str
    boards: tuple[str, ...]
    rules: tuple[Rule, ...]


def compile_groups(entries, catalog: dict[str, AudioClip]):
    groups = {}
    used_boards = set()
    for entry in array(entries, 'groups'):
        fields(entry, ('group_id', 'boards', 'rules'))
        group_id = text(entry['group_id'], 'group_id')
        if group_id in groups:
            fail(400, 'duplicate_group', f'Group {group_id} appears twice')
        boards = tuple(text(board, 'board_id') for board in array(entry['boards'], 'boards'))
        if len(boards) > 2 or len(set(boards)) != len(boards) or used_boards.intersection(boards):
            fail(400, 'invalid_boards', 'A group has at most two boards and each board belongs to one group')
        used_boards.update(boards)
        rules = _compile_rules(entry['rules'], boards, catalog)
        groups[group_id] = GroupRules(group_id, boards, rules)
    return groups


def _compile_rules(entries, boards, catalog):
    rules = []
    priorities = set()
    identities = set()
    for entry in array(entries, 'rules'):
        fields(entry, ('rule_id', 'priority', 'requires', 'audio_id'))
        rule_id = text(entry['rule_id'], 'rule_id')
        priority = integer(entry['priority'], 'priority', minimum=0, code='invalid_priority')
        if priority in priorities:
            fail(400, 'invalid_priority', 'Rule priorities must be distinct within a group')
        if rule_id in identities:
            fail(400, 'duplicate_rule', f'Rule {rule_id} appears twice in the group')
        requires = tuple(text(board, 'requires') for board in array(entry['requires'], 'requires'))
        if not requires or len(requires) != len(set(requires)):
            fail(400, 'invalid_rule_boards', 'A rule must name distinct required boards')
        if not set(requires).issubset(boards):
            fail(400, 'cross_group_rule', f'Rule {rule_id} refers to a board outside its group')
        audio_id = text(entry['audio_id'], 'audio_id')
        if audio_id not in catalog:
            fail(400, 'unknown_audio', f'Rule {rule_id} refers to unknown audio {audio_id}')
        rules.append(Rule(rule_id, priority, requires, audio_id))
        priorities.add(priority)
        identities.add(rule_id)
    return tuple(sorted(rules, key=lambda rule: rule.priority))


def select_rule(group: GroupRules, pressed: set[str]) -> Rule | None:
    for rule in group.rules:
        if pressed.issuperset(rule.requires):
            return rule
    return None
