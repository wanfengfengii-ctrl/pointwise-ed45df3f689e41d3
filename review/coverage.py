from session.closing import ClosedRange


def find_pending_ticks(closed: ClosedRange, group_ids, results):
    settled = {(result.tick, result.group_id) for result in results}
    groups = sorted(group_ids)
    return [
        {'tick': tick, 'group_id': group}
        for tick in closed.ticks()
        for group in groups
        if (tick, group) not in settled
    ]
