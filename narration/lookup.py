from narration.playback import PlayResult, read_result, read_session_results
from session.scope import resolve_group_tick


def inspect(db, session_id, group_id, tick):
    scope = resolve_group_tick(db, session_id, group_id, tick)
    result = read_result(db, scope)
    if result is None:
        result = PlayResult(*scope.key(), 'pending')
    return result.payload()


def read_review_results(db, session_id):
    return read_session_results(db, session_id)
