from concurrent.futures import ThreadPoolExecutor

from tests.support import GalleryTest, gallery_input, open_gallery


class PlaybackTests(GalleryTest):
    def test_press_with_confirmed_empty(self):
        session = self.open_gallery('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        right_seal = self.panel('seal', session, 'R', 1, 'right-seal')
        self.client.deliver(left)
        self.assertEqual(self.inspect(session, 1)['status'], 'pending')
        self.assertEqual(self.plays(session), [])
        self.client.deliver(right_seal)
        actual = self.inspect(session, 1)
        self.assertEqual((actual['status'], actual['rule_id']), ('started', 'ridge-alone'))
        self.assertEqual(actual['clip'], {'audio_id': 'ridge', 'name': '触摸山脊', 'length_ticks': 2})
        self.assert_sources(actual, left)
        self.assertEqual(self.plays(session), [actual])

    def test_delayed_press_after_seal(self):
        session = self.open_gallery('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        right = self.panel('touch', session, 'R', 1, 'right')
        right_seal = self.panel('seal', session, 'R', 1, 'right-seal')
        self.client.deliver(left)
        acknowledgement = self.client.deliver(right_seal)
        self.assertEqual(self.inspect(session, 1), {
            'session_id': session, 'group_id': 'atlas', 'tick': 1, 'status': 'pending',
        })
        self.assertEqual(self.plays(session), [])
        self.client.deliver(right)
        actual = self.inspect(session, 1)
        self.assertEqual((actual['status'], actual['rule_id']), ('started', 'two-boards'))
        self.assertEqual(actual['clip'], {'audio_id': 'relief', 'name': '山脊与河谷', 'length_ticks': 4})
        self.assert_sources(actual, left, right)
        self.assertEqual(self.client.deliver(right_seal), acknowledgement)
        self.assertEqual(self.inspect(session, 1), actual)
        self.assertEqual(self.plays(session), [actual])

    def test_unneeded_panel_missing(self):
        session = self.open_gallery()
        self.tick(session, 1)
        left = self.panel('touch', session, 'M', 1, 'minerals-left')
        held = self.panel('seal', session, 'N', 1, 'minerals-right')
        self.client.deliver(left)
        actual = self.inspect(session, 1, 'minerals')
        self.assertEqual((actual['status'], actual['rule_id'], actual['clip']['audio_id']),
                         ('started', 'ore-face', 'ore'))
        self.assert_sources(actual, left)
        self.assertEqual(self.inspect(session, 1, 'atlas')['status'], 'pending')
        self.assertEqual(self.plays(session), [actual])
        self.client.deliver(held)
        self.assertEqual(self.inspect(session, 1, 'minerals'), actual)
        self.assertEqual(self.plays(session), [actual])

    def test_certain_silence(self):
        data = gallery_input()
        data['show']['groups'][1]['rules'] = []
        session = open_gallery(self.client, data)['session_id']
        self.tick(session, 1)
        self.assertEqual(self.inspect(session, 1, 'minerals'), {
            'session_id': session, 'group_id': 'minerals', 'tick': 1, 'status': 'silent',
        })
        self.assertEqual(self.inspect(session, 1)['status'], 'pending')
        self.client.deliver(self.panel('seal', session, 'L', 1, 'left-empty'))
        self.assertEqual(self.inspect(session, 1), {
            'session_id': session, 'group_id': 'atlas', 'tick': 1, 'status': 'silent',
        })
        self.client.deliver(self.panel('touch', session, 'R', 1, 'right-late'))
        self.assertEqual(self.inspect(session, 1)['status'], 'silent')
        self.assertEqual(self.plays(session), [])

    def test_isolate_original_tick(self):
        session = self.open_gallery('atlas')
        self.tick(session, 1)
        left_one = self.panel('touch', session, 'L', 1, 'left-one')
        right_one = self.panel('touch', session, 'R', 1, 'right-one')
        self.client.deliver(left_one)
        self.client.deliver(right_one)
        first = self.inspect(session, 1)
        self.assert_sources(first, left_one, right_one)
        self.tick(session, 2)
        left_two = self.panel('touch', session, 'L', 2, 'left-two')
        right_two = self.panel('touch', session, 'R', 2, 'right-two')
        self.client.deliver(left_two)
        self.client.deliver(self.panel('seal', session, 'R', 2, 'right-two-seal'))
        self.assertEqual(self.inspect(session, 2)['status'], 'pending')
        self.assertEqual(self.plays(session), [first])
        self.client.deliver(right_two)
        second = self.inspect(session, 2)
        self.assertEqual(second['rule_id'], 'two-boards')
        self.assert_sources(second, left_two, right_two)
        self.assertEqual(self.plays(session), [first, second])

    def test_reject_conflicting_replay(self):
        session = self.open_gallery('atlas')
        self.tick(session, 1)
        self.tick(session, 2)
        right = self.panel('touch', session, 'R', 1, 'right-held')
        seal = self.panel('seal', session, 'R', 1, 'right-seal')
        acknowledgement = self.client.deliver(seal)
        evidence = self.client.get('delivery', delivery_id=seal['delivery_id'])
        for changes in ({'press_ids': []}, {'tick': 2}, {'board_id': 'L'}, {'event_id': 'unissued'}):
            with self.subTest(changes=changes):
                self.rejected('evidence_conflict', 'receive', evidence={**evidence, **changes})
        self.rejected('unknown_board', 'touch', status=404, session_id=session,
                      board_id='M', tick=1, request_id='wrong-board')
        self.rejected('unknown_group', 'inspect', method='get', status=404, session_id=session,
                      group_id='minerals', tick=1)
        left = self.panel('touch', session, 'L', 1, 'left')
        self.client.deliver(left)
        self.assertEqual(self.inspect(session, 1)['status'], 'pending')
        self.assertEqual(self.inspect(session, 2)['status'], 'pending')
        self.assertEqual(self.client.deliver(seal), acknowledgement)
        self.client.deliver(right)
        self.assert_sources(self.inspect(session, 1), left, right)

    def test_first_received_press_is_the_source(self):
        session = self.open_gallery('atlas')
        self.tick(session, 1)
        first_accepted = self.panel('touch', session, 'L', 1, 'left-first')
        first_delivered = self.panel('touch', session, 'L', 1, 'left-second')
        self.client.deliver(self.panel('seal', session, 'L', 1, 'left-seal'))
        self.client.deliver(self.panel('seal', session, 'R', 1, 'right-seal'))
        self.assertEqual(self.inspect(session, 1)['status'], 'pending')
        self.client.deliver(first_delivered)
        result = self.inspect(session, 1)
        self.assertEqual(result['rule_id'], 'ridge-alone')
        self.assert_sources(result, first_delivered)
        self.client.deliver(first_accepted)
        self.assertEqual(self.inspect(session, 1), result)
        self.assertEqual(self.plays(session), [result])

    def test_resume_after_lost_seal_reply(self):
        session = self.open_gallery('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        loss_args = {'session_id': session, 'board_id': 'L', 'tick': 1, 'request_id': 'left-seal'}
        lost = self.gallery.lose_reply('seal', **loss_args)
        self.assertEqual(lost['status'], 'sealed')
        self.client.deliver(left)
        self.client.deliver(self.panel('seal', session, 'R', 1, 'right-seal'))
        result = self.inspect(session, 1)
        self.assertEqual(result['rule_id'], 'ridge-alone')
        self.assert_sources(result, left)
        self.client.post('close', session_id=session)
        report = self.client.post('report', session_id=session)
        self.gallery.restart()
        self.assertEqual(self.client.get('receipt', session_id=session, request_id='left-seal'), lost)
        self.assertEqual(self.client.post('seal', **loss_args), lost)
        self.assertEqual(self.panel('touch', session, 'L', 1, 'left'), left)
        self.rejected('panel_sealed', 'touch', **{**loss_args, 'request_id': 'new-press'})
        self.rejected('unknown_receipt', 'receipt', method='get', status=404,
                      session_id=session, request_id='new-press')
        self.rejected('request_conflict', 'touch', **{**loss_args, 'request_id': 'left', 'board_id': 'R'})
        self.rejected('request_conflict', 'touch', **loss_args)
        resealed = self.panel('seal', session, 'L', 1, 'seal-again')
        self.assertEqual(resealed['delivery_id'], lost['delivery_id'])
        self.assertEqual(self.client.get('delivery', delivery_id=lost['delivery_id'])['press_ids'],
                         [left['delivery_id']])
        self.client.deliver(resealed)
        self.client.deliver(left)
        self.assertEqual(self.inspect(session, 1), result)
        self.assertEqual(self.plays(session), [result])
        self.assertEqual(self.client.post('report', report_id=report['report_id']), report)

    def test_tick_gap_after_reopen(self):
        session = self.open_gallery('atlas')
        self.tick(session, 1)
        self.gallery.restart()
        self.rejected('tick_out_of_sequence', 'tick', session_id=session, tick=3)
        self.rejected('tick_out_of_sequence', 'tick', session_id=session, tick=1)
        self.rejected('tick_not_open', 'touch', session_id=session, board_id='L', tick=3, request_id='early')
        self.tick(session, 2)
        self.assertEqual(self.client.get('session', session_id=session)['last_tick'], 2)

    def test_concurrent_delivery_starts_once(self):
        session = self.open_gallery('minerals')
        self.tick(session, 1)
        left = self.panel('touch', session, 'M', 1, 'left')
        client = self.client
        with ThreadPoolExecutor(max_workers=4) as pool:
            acknowledgements = list(pool.map(client.deliver, [left] * 4))
        self.assertEqual(acknowledgements, [acknowledgements[0]] * 4)
        self.assertEqual(acknowledgements[0]['status'], 'received')
        result = self.inspect(session, 1, 'minerals')
        self.assertEqual(result['status'], 'started')
        self.assert_sources(result, left)
        self.assertEqual(self.plays(session), [result])
