from dataclasses import dataclass
from itertools import product

from narration.facts import ReceivedBoard, read_group_facts
from narration.playback import commit_result, read_result
from program.rules import Rule, select_rule
from session.scope import GroupTick


@dataclass(frozen=True)
class Decision:
    rule: Rule | None
    sources: tuple[dict, ...] = ()


def _possible_states(board: ReceivedBoard):
    if board.first_press is not None:
        return (True,)
    if board.seal is not None:
        return (bool(board.seal.press_ids),)
    return False, True


def decide_group_tick(scope: GroupTick, facts: dict[str, ReceivedBoard]):
    boards = scope.group.boards
    winners = set()
    for states in product(*(_possible_states(facts[board]) for board in boards)):
        pressed = {board for board, down in zip(boards, states) if down}
        winners.add(select_rule(scope.group, pressed))
        if len(winners) > 1:
            return None
    rule = winners.pop()
    if rule is None:
        return Decision(None)
    sources = []
    for board in rule.requires:
        press = facts[board].first_press
        if press is None:
            return None
        sources.append({
            'board_id': press.board_id, 'session_id': press.session_id, 'tick': press.tick,
            'event_id': press.event_id, 'request_id': press.request_id,
            'position': scope.session.bindings[board].position,
        })
    return Decision(rule, tuple(sources))


def settle_group_tick(db, scope: GroupTick):
    original = read_result(db, scope)
    if original is not None:
        return original
    decision = decide_group_tick(scope, read_group_facts(db, scope))
    if decision is None:
        return None
    if decision.rule is None:
        return commit_result(db, scope)
    clip = scope.show.draft.audio[decision.rule.audio_id]
    return commit_result(db, scope, rule_id=decision.rule.rule_id, clip=clip, sources=decision.sources)
