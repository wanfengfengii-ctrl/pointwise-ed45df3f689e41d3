from tests.support import GalleryTest


class ReviewTests(GalleryTest):
    def test_closed_report_reopen(self):
        session = self.open_gallery('atlas')
        self.tick(session, 1)
        self.tick(session, 2)
        left = self.panel('touch', session, 'L', 1, 'left-one')
        right_seal = self.panel('seal', session, 'R', 1, 'right-one-seal')
        self.client.deliver(self.panel('seal', session, 'L', 2, 'left-two-seal'))
        self.assertEqual(self.inspect(session, 2)['status'], 'silent')
        self.assertEqual(self.inspect(session, 1)['status'], 'pending')
        self.client.deliver(left)
        self.client.deliver(right_seal)
        self.client.post('close', session_id=session)
        report = self.client.post('report', session_id=session)
        self.assertEqual((report['status'], report['session_id'], report['last_tick']), ('published', session, 2))
        self.assertEqual([(e['tick'], e['group_id'], e['status']) for e in report['entries']],
                         [(1, 'atlas', 'started'), (2, 'atlas', 'silent')])
        first, second = report['entries']
        self.assertEqual(first['clip'], {'audio_id': 'ridge', 'name': '触摸山脊', 'length_ticks': 2})
        self.assert_sources(first, left)
        self.assertEqual(second, {'group_id': 'atlas', 'tick': 2, 'status': 'silent'})
        started, = self.plays(session)
        self.assertEqual(first, {key: value for key, value in started.items() if key != 'session_id'})
        self.gallery.restart()
        self.assertEqual(self.client.post('report', session_id=session), report)
        self.assertEqual(self.client.post('report', report_id=report['report_id']), report)
        self.rejected('unknown_report', 'report', status=404, report_id=report['report_id'] + 1)

    def test_close_with_pending_tick(self):
        session = self.open_gallery()
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'atlas-left')
        right = self.panel('touch', session, 'R', 1, 'atlas-right-held')
        mineral = self.panel('touch', session, 'M', 1, 'ore-left')
        self.client.deliver(mineral)
        self.client.deliver(left)
        self.client.deliver(self.panel('seal', session, 'R', 1, 'atlas-right-seal'))
        self.rejected('session_not_closed', 'report', session_id=session)
        closed = self.client.post('close', session_id=session)
        self.assertEqual(closed, {'session_id': session, 'last_tick': 1})
        self.assertEqual(self.client.post('report', session_id=session), {
            'status': 'pending', 'session_id': session, 'last_tick': 1,
            'pending': [{'tick': 1, 'group_id': 'atlas'}],
        })
        self.rejected('unknown_report', 'report', status=404, report_id=1)
        self.rejected('session_closed', 'tick', session_id=session, tick=2)
        self.client.deliver(self.panel('touch', session, 'N', 1, 'ore-late'))
        self.assertEqual(self.client.post('close', session_id=session), closed)
        self.client.deliver(right)
        report = self.client.post('report', session_id=session)
        self.assertEqual(report['report_id'], 1)
        self.assertEqual([(e['tick'], e['group_id'], e['clip']['audio_id']) for e in report['entries']],
                         [(1, 'atlas', 'relief'), (1, 'minerals', 'ore')])
        self.assert_sources(report['entries'][0], left, right)
        self.assert_sources(report['entries'][1], mineral)
        self.assertEqual(self.client.post('close', session_id=session), closed)
        self.assertEqual(self.client.post('report', session_id=session), report)

    def test_empty_closed_range(self):
        session = self.open_gallery('atlas')
        self.rejected('session_not_closed', 'report', session_id=session)
        closed = self.client.post('close', session_id=session)
        self.assertEqual(closed, {'session_id': session, 'last_tick': 0})
        report = self.client.post('report', session_id=session)
        self.assertEqual(report, {'status': 'published', 'report_id': 1, 'session_id': session,
                                  'last_tick': 0, 'entries': []})
        self.rejected('invalid_report_selector', 'report', status=400, session_id=session, report_id=1)
        self.assertEqual(self.plays(session), [])
