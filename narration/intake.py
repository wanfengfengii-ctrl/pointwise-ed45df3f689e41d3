from narration.decide import settle_group_tick
from narration.facts import merge_evidence
from panel.evidence import PressEvidence, SealEvidence
from session.scope import resolve_board_tick, resolve_group_tick


def receive(db, evidence: PressEvidence | SealEvidence):
    scope = resolve_board_tick(db, evidence.session_id, evidence.board_id, evidence.tick)
    confirmation = merge_evidence(db, scope, evidence)
    group_tick = resolve_group_tick(db, scope.session_id, scope.group_id, scope.tick)
    settle_group_tick(db, group_tick)
    return confirmation
