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


if __name__ == '__main__':
    main()
