from narration.correction import merge_authorization, settle
from narration.facts import merge_evidence
from panel.evidence import AuthorizationEvidence, PressEvidence, SealEvidence
from session.scope import resolve_board_tick, resolve_group_tick


def receive(db, evidence: PressEvidence | SealEvidence, fixed_lookup):
    scope = resolve_board_tick(db, evidence.session_id, evidence.board_id, evidence.tick)
    confirmation = merge_evidence(db, scope, evidence)
    group_tick = resolve_group_tick(db, scope.session_id, scope.group_id, scope.tick)
    settle(db, group_tick, fixed_lookup(group_tick))
    return confirmation


def receive_authorized(db, evidence: AuthorizationEvidence, fixed_lookup):
    group_tick = resolve_group_tick(db, evidence.session_id, evidence.group_id, evidence.tick)
    fixed = fixed_lookup(group_tick)
    confirmation = merge_authorization(db, evidence, fixed)
    settle(db, group_tick, fixed)
    return confirmation
