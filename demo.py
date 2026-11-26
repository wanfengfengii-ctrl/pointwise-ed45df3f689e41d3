import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support import LocalGallery, gallery_input, open_gallery, panel_operation


def _observe(result):
    return {
        'status': result['status'],
        'rule': result.get('rule_id'),
        'audio': result.get('clip', {}).get('audio_id'),
        'requests': [source['request_id'] for source in result.get('sources', [])],
    }


def _correction_scenario(gallery):
    client = gallery.client
    data = gallery_input('atlas')
    session = open_gallery(client, data, mode='correctable')['session_id']
    client.post('tick', session_id=session, tick=1)
    left = panel_operation(client, 'touch', session, 'L', 1, 'left')
    right = panel_operation(client, 'touch', session, 'R', 1, 'right')
    panel_operation(client, 'seal', session, 'L', 1, 'left-seal')
    panel_operation(client, 'seal', session, 'R', 1, 'right-seal')
    # R1 is withdrawn first. Its stale body is delivered before the final
    # authorization, and L1 arrives only after the authorization has been received.
    withdrawn = client.post('retract', session_id=session, board_id='R', tick=1,
                            press_id=right['delivery_id'], request_id='retract-right')
    stale = client.deliver(right)
    before = client.get('inspect', session_id=session, group_id='atlas', tick=1)
    assert before['status'] == 'pending'
    assert client.get('plays', session_id=session)['starts'] == []
    authorized = client.post('authorize', session_id=session, group_id='atlas', tick=1,
                             request_id='authorize-atlas')
    assert authorized['rule_id'] == 'ridge-alone'
    assert authorized['press_ids'] == {'L': left['delivery_id']}
    authorization = client.get('delivery', delivery_id=authorized['delivery_id'])
    client.post('receive', evidence=authorization)
    still_pending = client.get('inspect', session_id=session, group_id='atlas', tick=1)
    assert still_pending['status'] == 'pending'
    assert client.get('plays', session_id=session)['starts'] == []
    fresh = client.deliver(left)
    assert stale['status'] == 'received' and fresh['status'] == 'received'
    authorized = client.post('authorize', session_id=session, group_id='atlas', tick=1,
                             request_id='authorize-atlas')
    assert authorized['rule_id'] == 'ridge-alone'
    assert authorized['press_ids'] == {'L': left['delivery_id']}
    authorization = client.get('delivery', delivery_id=authorized['delivery_id'])
    client.post('receive', evidence=authorization)
    after = client.get('inspect', session_id=session, group_id='atlas', tick=1)
    assert after['status'] == 'started' and after['rule_id'] == 'ridge-alone'
    assert [source['request_id'] for source in after['sources']] == ['left']
    assert client.get('plays', session_id=session)['starts'] == [after]
    assert client.get('delivery', delivery_id=right['delivery_id'])['request_id'] == 'right'
    protected = client.post('retract', session_id=session, board_id='L', tick=1,
                            press_id=left['delivery_id'], request_id='retract-left')
    assert protected['status'] == 'protected'
    assert client.post('close', session_id=session) == {'session_id': session, 'last_tick': 1}
    report = client.post('report', session_id=session)
    assert report['status'] == 'published' and report['report_id'] == 1
    entries = [[entry['tick'], entry['group_id'], _observe(entry)] for entry in report['entries']]
    gallery.restart()
    client = gallery.client
    assert client.post('authorize', session_id=session, group_id='atlas', tick=1,
                       request_id='authorize-atlas') == authorized
    assert client.post('retract', session_id=session, board_id='R', tick=1,
                       press_id=right['delivery_id'], request_id='retract-right') == withdrawn
    assert client.post('report', report_id=report['report_id']) == report
    return {
        'case_id': 'correction',
        'input': {'mode': 'correctable', 'tick': 1, 'pressed': ['left', 'right'],
                  'sealed': ['L', 'R'], 'withdrawn': 'right',
                  'delivery_order': ['right (stale)', 'left', 'authorization']},
        'actual': {'withdrawn': withdrawn['status'], 'before': _observe(before),
                   'authorization': {'authorization_id': authorized['authorization_id'],
                                     'rule_id': authorized['rule_id'],
                                     'press_boards': sorted(authorized['press_ids'])},
                   'after_authorization': _observe(still_pending), 'after': _observe(after),
                   'protected': protected['status'],
                   'starts': len(client.get('plays', session_id=session)['starts']),
                   'entries': entries, 'report_id': report['report_id'],
                   'stale_replay': client.get('delivery', delivery_id=right['delivery_id']),
                   'retract_replay': withdrawn},
        'expected': {'withdrawn': 'withdrawn', 'before': {'status': 'pending', 'rule': None,
                                                          'audio': None, 'requests': []},
                     'authorization': {'rule_id': 'ridge-alone', 'press_boards': ['L']},
                     'after_authorization': {'status': 'pending', 'rule': None, 'audio': None,
                                             'requests': []},
                     'after': {'status': 'started', 'rule': 'ridge-alone',
                               'audio': 'ridge', 'requests': ['left']},
                     'protected': 'protected', 'starts': 1,
                     'entries': [[1, 'atlas', {'status': 'started', 'rule': 'ridge-alone',
                                               'audio': 'ridge', 'requests': ['left']}]],
                     'report_id': 1},
        'code_paths': ['panel/correction.py', 'narration/correction.py',
                       'narration/intake.py', 'narration/playback.py', 'review/publish.py'],
        'oracle': 'Withdrawing R1 leaves the L-only rule effective. Authorization adopts L, but '
                  'the group stays pending until its body is received. Then exactly one ridge '
                  'start has the left source, the stale right body and the withdrawn result still '
                  'replay, and the closed report keeps one entry.',
    }


def main():
    with TemporaryDirectory() as directory, LocalGallery(Path(directory) / 'gallery.sqlite3') as gallery:
        client = gallery.client
        session = open_gallery(client, gallery_input())['session_id']
        client.post('tick', session_id=session, tick=1)
        left = panel_operation(client, 'touch', session, 'L', 1, 'atlas-left')
        right = panel_operation(client, 'touch', session, 'R', 1, 'atlas-right')
        seal = panel_operation(client, 'seal', session, 'R', 1, 'atlas-seal')
        mineral = panel_operation(client, 'touch', session, 'M', 1, 'ore-left')
        held = panel_operation(client, 'seal', session, 'N', 1, 'ore-empty')
        client.deliver(left)
        client.deliver(seal)
        client.deliver(mineral)
        before = client.get('inspect', session_id=session, group_id='atlas', tick=1)
        early = client.get('inspect', session_id=session, group_id='minerals', tick=1)
        starts_before = client.get('plays', session_id=session)['starts']
        assert [row['group_id'] for row in starts_before] == ['minerals']
        client.post('close', session_id=session)
        pending = client.post('report', session_id=session)
        expected_pending = [{'tick': 1, 'group_id': 'atlas'}]
        assert pending['status'] == 'pending' and pending['pending'] == expected_pending
        client.deliver(right)
        after = client.get('inspect', session_id=session, group_id='atlas', tick=1)
        client.deliver(held)
        client.deliver(right)
        actual = {'before': _observe(before), 'after': _observe(after), 'independent': _observe(early)}
        expected = {
            'before': {'status': 'pending', 'rule': None, 'audio': None, 'requests': []},
            'after': {'status': 'started', 'rule': 'two-boards', 'audio': 'relief',
                      'requests': ['atlas-left', 'atlas-right']},
            'independent': {'status': 'started', 'rule': 'ore-face', 'audio': 'ore',
                            'requests': ['ore-left']},
        }
        assert actual == expected, (actual, expected)
        starts = client.get('plays', session_id=session)['starts']
        assert starts == [early, after]
        report = client.post('report', session_id=session)
        assert report['status'] == 'published'
        downstream = {
            'pending': pending['pending'],
            'entries': [[entry['tick'], entry['group_id'], _observe(entry)] for entry in report['entries']],
            'atlas_starts': sum(row['group_id'] == 'atlas' for row in starts),
        }
        downstream_expected = {
            'pending': expected_pending,
            'entries': [[1, 'atlas', expected['after']], [1, 'minerals', expected['independent']]],
            'atlas_starts': 1,
        }
        assert downstream == downstream_expected
        gallery.restart()
        assert gallery.client.post('report', report_id=report['report_id']) == report
        result = {
            'case_id': 'v4',
            'input': {'tick': 1, 'accepted_boards': ['L', 'R', 'M'], 'empty_board': 'N',
                      'delivery_order': ['atlas-left', 'atlas-seal', 'ore-left', 'atlas-right', 'ore-empty']},
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream,
            'code_paths': ['panel/seal.py', 'narration/facts.py', 'narration/decide.py',
                           'narration/playback.py', 'review/coverage.py', 'review/publish.py'],
            'oracle': 'Compare the two atlas rules by priority and the one minerals rule by hand. '
                      'The closed report has both groups in group order and one atlas start.',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(result, ensure_ascii=False, sort_keys=True))

    with TemporaryDirectory() as directory, LocalGallery(Path(directory) / 'gallery.sqlite3') as gallery:
        correction = _correction_scenario(gallery)
        print('POINTWISE_SCENARIO ' + json.dumps(correction, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
