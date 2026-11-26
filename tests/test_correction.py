from concurrent.futures import ThreadPoolExecutor

from tests.support import GalleryTest, gallery_input, open_gallery


class CorrectionTests(GalleryTest):
    def open_correctable(self, *groups, mode='correctable'):
        return self.open_gallery(*groups, mode=mode)

    def deliver_delivery(self, delivery_id):
        evidence = self.client.get('delivery', delivery_id=delivery_id)
        return self.client.post('receive', evidence=evidence)

    def retract(self, session, board, tick, press, request):
        return self.client.post('retract', session_id=session, board_id=board, tick=tick,
                                press_id=press, request_id=request)

    def authorize(self, session, tick, request, group='atlas', proposal_id=None):
        payload = {'session_id': session, 'group_id': group, 'tick': tick, 'request_id': request}
        if proposal_id is not None:
            payload['proposal_id'] = proposal_id
        return self.client.post('authorize', **payload)

    def test_retraction_before_authorization_uses_left_rule(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        right = self.panel('touch', session, 'R', 1, 'right')
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        withdrawn = self.retract(session, 'R', 1, right['delivery_id'], 'retract-right')
        self.assertEqual(withdrawn, {
            'session_id': session, 'board_id': 'R', 'tick': 1,
            'press_id': right['delivery_id'], 'status': 'withdrawn',
        })
        self.deliver_delivery(right['delivery_id'])
        self.deliver_delivery(left['delivery_id'])
        self.assertEqual(self.inspect(session, 1)['status'], 'pending')
        self.assertEqual(self.plays(session), [])

        authorized = self.authorize(session, 1, 'authorize-atlas')
        self.assertEqual((authorized['status'], authorized['rule_id']), ('authorized', 'ridge-alone'))
        self.assertEqual(authorized['press_ids'], {'L': left['delivery_id']})
        self.deliver_delivery(authorized['delivery_id'])
        result = self.inspect(session, 1)
        self.assertEqual((result['status'], result['rule_id'], result['clip']['audio_id']),
                         ('started', 'ridge-alone', 'ridge'))
        self.assert_sources(result, left)
        self.assertEqual(self.plays(session), [result])

        # The withdrawn press stays protected from adoption, but its original delivery remains.
        self.assertEqual(self.retract(session, 'R', 1, right['delivery_id'], 'retract-right'),
                         withdrawn)
        self.assertEqual(self.authorize(session, 1, 'authorize-atlas'), authorized)
        self.assertEqual(self.client.get('delivery', delivery_id=right['delivery_id'])['kind'],
                         'press')
        self.deliver_delivery(right['delivery_id'])
        self.deliver_delivery(authorized['delivery_id'])
        self.assertEqual(self.inspect(session, 1), result)
        self.assertEqual(self.plays(session), [result])

        self.assertEqual(self.retract(session, 'L', 1, left['delivery_id'], 'retract-left')['status'],
                         'protected')
        self.client.post('close', session_id=session)
        report = self.client.post('report', session_id=session)
        self.assertEqual(report['status'], 'published')
        self.assertEqual([(entry['tick'], entry['status']) for entry in report['entries']],
                         [(1, 'started')])

    def test_unadopted_press_still_retractable_after_authorization(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left_one = self.panel('touch', session, 'L', 1, 'left-one')
        left_two = self.panel('touch', session, 'L', 1, 'left-two')
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        authorized = self.authorize(session, 1, 'authorize')
        self.assertEqual(authorized['press_ids'], {'L': left_one['delivery_id']})
        self.assertEqual(self.retract(session, 'L', 1, left_one['delivery_id'],
                                      'retract-adopted')['status'], 'protected')
        withdrawn = self.retract(session, 'L', 1, left_two['delivery_id'], 'retract-unadopted')
        self.assertEqual(withdrawn['status'], 'withdrawn')
        self.deliver_delivery(authorized['delivery_id'])
        self.deliver_delivery(left_one['delivery_id'])
        result = self.inspect(session, 1)
        self.assertEqual(result['rule_id'], 'ridge-alone')
        self.assert_sources(result, left_one)
        self.assertEqual(self.plays(session), [result])
        # The withdrawal of an unadopted press does not disturb the fixed authorization.
        self.deliver_delivery(left_two['delivery_id'])
        self.assertEqual(self.inspect(session, 1), result)

    def test_second_press_on_same_board_replaces_withdrawn(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        right_one = self.panel('touch', session, 'R', 1, 'right-one')
        right_two = self.panel('touch', session, 'R', 1, 'right-two')
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        withdrawn = self.retract(session, 'R', 1, right_one['delivery_id'], 'drop-right-one')
        self.assertEqual(withdrawn['status'], 'withdrawn')

        proposal = self.client.post('propose', session_id=session, group_id='atlas', tick=1,
                                    request_id='proposal-old', rule_id='two-boards',
                                    press_ids={'L': left['delivery_id'],
                                               'R': right_one['delivery_id']})
        self.rejected('proposal_conflict', 'authorize', session_id=session, group_id='atlas',
                      tick=1, request_id='authorize-with-proposal',
                      proposal_id=proposal['proposal_id'])
        authorized = self.authorize(session, 1, 'authorize-with-proposal')
        self.assertEqual(authorized['rule_id'], 'two-boards')
        self.assertEqual(authorized['press_ids'],
                         {'L': left['delivery_id'], 'R': right_two['delivery_id']})

        self.deliver_delivery(authorized['delivery_id'])
        self.deliver_delivery(left['delivery_id'])
        self.assertEqual(self.inspect(session, 1)['status'], 'pending')
        self.deliver_delivery(right_two['delivery_id'])
        result = self.inspect(session, 1)
        self.assertEqual((result['rule_id'], result['clip']['audio_id']), ('two-boards', 'relief'))
        self.assert_sources(result, left, right_two)
        self.assertEqual(self.plays(session), [result])
        self.assertEqual(self.retract(session, 'R', 1, right_one['delivery_id'],
                                      'drop-right-one-again'), withdrawn)
        self.assertEqual(self.retract(session, 'R', 1, right_two['delivery_id'],
                                      'drop-right-two')['status'], 'protected')
        # The stale body of the first press cannot be promoted to a source.
        self.deliver_delivery(right_one['delivery_id'])
        self.assertEqual(self.inspect(session, 1), result)

    def test_proposal_is_persisted_and_never_starts(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        self.panel('seal', session, 'L', 1, 'left-seal')
        proposal = self.client.post('propose', session_id=session, group_id='atlas', tick=1,
                                    request_id='proposal-left', rule_id='ridge-alone',
                                    press_ids={'L': left['delivery_id']})
        self.assertEqual(proposal['rule_id'], 'ridge-alone')
        self.assertEqual(proposal['press_ids'], {'L': left['delivery_id']})
        self.deliver_delivery(left['delivery_id'])
        self.assertEqual(self.inspect(session, 1)['status'], 'pending')
        self.assertEqual(self.plays(session), [])
        pending = self.authorize(session, 1, 'authorize')
        self.assertEqual(pending['status'], 'pending')
        self.panel('seal', session, 'R', 1, 'right-seal')
        authorized = self.authorize(session, 1, 'authorize', proposal_id=proposal['proposal_id'])
        self.assertEqual(authorized['status'], 'authorized')
        self.assertEqual(authorized['press_ids'], {'L': left['delivery_id']})
        self.assertEqual(self.authorize(session, 1, 'authorize'),
                         self.authorize(session, 1, 'authorize', proposal_id=proposal['proposal_id']))

    def test_silent_authorization(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        proposal = self.client.post('propose', session_id=session, group_id='atlas', tick=1,
                                    request_id='proposal-silent', rule_id=None, press_ids={})
        authorized = self.authorize(session, 1, 'authorize-silent',
                                    proposal_id=proposal['proposal_id'])
        self.assertEqual((authorized['status'], authorized['rule_id']), ('authorized', None))
        self.assertEqual(authorized['press_ids'], {})
        self.deliver_delivery(authorized['delivery_id'])
        self.assertEqual(self.inspect(session, 1), {
            'session_id': session, 'group_id': 'atlas', 'tick': 1, 'status': 'silent',
        })
        self.assertEqual(self.plays(session), [])

    def test_authorize_waits_for_undecided_board(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        pending = self.authorize(session, 1, 'authorize-wait')
        self.assertEqual(pending, {'status': 'pending', 'session_id': session,
                                   'group_id': 'atlas', 'tick': 1})
        self.panel('seal', session, 'L', 1, 'left-seal')
        pending = self.authorize(session, 1, 'authorize-wait')
        self.assertEqual(pending['status'], 'pending')
        self.panel('seal', session, 'R', 1, 'right-seal')
        authorized = self.authorize(session, 1, 'authorize-wait')
        self.assertEqual(authorized['press_ids'], {'L': left['delivery_id']})

    def test_authorization_then_body_later(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        authorized = self.authorize(session, 1, 'authorize')
        self.deliver_delivery(authorized['delivery_id'])
        self.assertEqual(self.inspect(session, 1)['status'], 'pending')
        self.assertEqual(self.plays(session), [])
        self.gallery.restart()
        self.assertEqual(self.inspect(session, 1)['status'], 'pending')
        self.deliver_delivery(left['delivery_id'])
        result = self.inspect(session, 1)
        self.assertEqual((result['status'], result['rule_id']), ('started', 'ridge-alone'))
        self.assert_sources(result, left)
        self.assertEqual(self.plays(session), [result])
        self.assertEqual(self.authorize(session, 1, 'authorize'),
                         self.authorize(session, 1, 'authorize'))

    def test_normal_session_keeps_v1_behaviour(self):
        session = self.open_correctable('atlas', mode='normal')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        self.rejected('not_correctable', 'retract', session_id=session, board_id='L', tick=1,
                      press_id=left['delivery_id'], request_id='retract')
        self.rejected('not_correctable', 'authorize', session_id=session, group_id='atlas',
                      tick=1, request_id='authorize')
        self.rejected('not_correctable', 'propose', session_id=session, group_id='atlas', tick=1,
                      request_id='propose', rule_id='ridge-alone',
                      press_ids={'L': left['delivery_id']})
        self.deliver_delivery(left['delivery_id'])
        self.deliver_delivery(self.panel('seal', session, 'R', 1, 'right-seal')['delivery_id'])
        self.assertEqual(self.inspect(session, 1)['rule_id'], 'ridge-alone')

    def test_correction_validation(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        self.rejected('invalid_mode', 'open', status=400, show_id=1, bindings=gallery_input()['bindings'],
                      mode='sometimes')
        self.rejected('unknown_press', 'retract', status=404, session_id=session, board_id='L',
                      tick=1, press_id='not-a-press', request_id='r1')
        self.rejected('unknown_rule', 'propose', status=404, session_id=session, group_id='atlas',
                      tick=1, request_id='p1', rule_id='no-such-rule', press_ids={})
        self.rejected('invalid_press_ids', 'propose', status=400, session_id=session,
                      group_id='atlas', tick=1, request_id='p2', rule_id='ridge-alone',
                      press_ids={'L': 'x', 'R': 'y'})
        self.rejected('invalid_press_ids', 'propose', status=400, session_id=session,
                      group_id='atlas', tick=1, request_id='p3', rule_id=None,
                      press_ids={'L': 'x'})
        self.rejected('unknown_group', 'propose', status=404, session_id=session,
                      group_id='minerals', tick=1, request_id='p4', rule_id=None, press_ids={})
        self.rejected('unknown_proposal', 'authorize', status=404, session_id=session,
                      group_id='atlas', tick=1, request_id='a1', proposal_id=7)

    def test_retract_conflicts_and_cross_board(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        self.retract(session, 'L', 1, left['delivery_id'], 'withdraw-left')
        self.rejected('request_conflict', 'retract', session_id=session, board_id='R', tick=1,
                      press_id=left['delivery_id'], request_id='withdraw-left')
        self.rejected('unknown_press', 'retract', status=404, session_id=session, board_id='R',
                      tick=1, press_id=left['delivery_id'], request_id='wrong-board')
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        self.assertEqual(self.authorize(session, 1, 'authorize')['rule_id'], None)

    def test_lost_authorize_reply_and_restart(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        args = {'session_id': session, 'group_id': 'atlas', 'tick': 1, 'request_id': 'authorize'}
        lost = self.gallery.lose_reply('authorize', **args)
        self.gallery.restart()
        self.assertEqual(self.client.post('authorize', **args), lost)
        self.assertEqual(self.authorize(session, 1, 'authorize-again'), lost)
        self.deliver_delivery(left['delivery_id'])
        self.assertEqual(self.inspect(session, 1)['status'], 'pending')
        self.gallery.restart()
        self.deliver_delivery(lost['delivery_id'])
        result = self.inspect(session, 1)
        self.assertEqual((result['status'], result['rule_id']), ('started', 'ridge-alone'))
        self.assert_sources(result, left)
        self.client.post('close', session_id=session)
        report = self.client.post('report', session_id=session)
        self.assertEqual(report['status'], 'published')
        self.gallery.restart()
        self.assertEqual(self.client.post('report', report_id=report['report_id']), report)

    def test_lost_retract_reply_and_restart(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        right = self.panel('touch', session, 'R', 1, 'right')
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        args = {'session_id': session, 'board_id': 'R', 'tick': 1,
                'press_id': right['delivery_id'], 'request_id': 'retract-right'}
        lost = self.gallery.lose_reply('retract', **args)
        self.assertEqual(lost['status'], 'withdrawn')
        self.gallery.restart()
        self.assertEqual(self.client.post('retract', **args), lost)
        authorized = self.authorize(session, 1, 'authorize')
        self.assertEqual(authorized['press_ids'], {'L': left['delivery_id']})
        self.deliver_delivery(authorized['delivery_id'])
        self.deliver_delivery(left['delivery_id'])
        result = self.inspect(session, 1)
        self.assertEqual(result['rule_id'], 'ridge-alone')
        self.assert_sources(result, left)
        self.assertEqual(self.plays(session), [result])
        self.client.post('close', session_id=session)
        report = self.client.post('report', session_id=session)
        self.assertEqual(report['status'], 'published')
        self.gallery.restart()
        self.assertEqual(self.client.post('report', report_id=report['report_id']), report)
        self.assertEqual(self.client.post('report', session_id=session), report)

    def test_duplicate_authorization_delivery_starts_once(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        self.panel('touch', session, 'L', 1, 'left-second')
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        authorized = self.authorize(session, 1, 'authorize')
        self.deliver_delivery(authorized['delivery_id'])
        self.assertEqual(self.inspect(session, 1)['status'], 'pending')
        acknowledgements = [self.deliver_delivery(left['delivery_id']) for _ in range(3)]
        self.assertEqual(acknowledgements, [acknowledgements[0]] * 3)
        first = self.inspect(session, 1)
        self.assertEqual(first['status'], 'started')
        self.assert_sources(first, left)
        self.deliver_delivery(authorized['delivery_id'])
        self.assertEqual(self.inspect(session, 1), first)
        self.assertEqual(self.plays(session), [first])

    def test_lost_authorization_receive_reply(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        authorized = self.authorize(session, 1, 'authorize')
        evidence = self.client.get('delivery', delivery_id=authorized['delivery_id'])
        acknowledgement = self.gallery.lose_reply('receive', evidence=evidence)
        self.assertEqual(acknowledgement['status'], 'received')
        self.gallery.restart()
        self.assertEqual(self.client.post('receive', evidence=evidence), acknowledgement)
        self.deliver_delivery(left['delivery_id'])
        result = self.inspect(session, 1)
        self.assertEqual((result['status'], result['rule_id']), ('started', 'ridge-alone'))
        self.assert_sources(result, left)
        self.assertEqual(self.plays(session), [result])
        self.client.post('close', session_id=session)
        report = self.client.post('report', session_id=session)
        self.assertEqual(report['status'], 'published')
        self.gallery.restart()
        self.assertEqual(self.client.post('report', report_id=report['report_id']), report)

    def test_lost_press_body_reply_under_authorization(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        authorized = self.authorize(session, 1, 'authorize')
        self.deliver_delivery(authorized['delivery_id'])
        evidence = self.client.get('delivery', delivery_id=left['delivery_id'])
        lost = self.gallery.lose_reply('receive', evidence=evidence)
        self.assertEqual(lost['status'], 'received')
        result = self.inspect(session, 1)
        self.assertEqual((result['status'], result['rule_id']), ('started', 'ridge-alone'))
        self.assert_sources(result, left)
        self.gallery.restart()
        self.assertEqual(self.client.post('receive', evidence=evidence), lost)
        self.assertEqual(self.inspect(session, 1), result)
        self.assertEqual(self.plays(session), [result])
        self.client.post('close', session_id=session)
        report = self.client.post('report', session_id=session)
        self.assertEqual(report['status'], 'published')
        self.assertEqual(self.plays(session), [result])

    def test_wrong_authorization_body_rejected(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        self.panel('touch', session, 'L', 1, 'left')
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        authorized = self.authorize(session, 1, 'authorize')
        evidence = self.client.get('delivery', delivery_id=authorized['delivery_id'])
        for change in ({'rule_id': 'two-boards'}, {'press_ids': {'L': 'x'}},
                       {'tick': 2}, {'group_id': 'minerals'}, {'event_id': 'unissued'}):
            with self.subTest(change=change):
                self.rejected('evidence_conflict', 'receive',
                              evidence={**evidence, **change})

    def test_report_close_cycle(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        self.client.post('close', session_id=session)
        pending = self.client.post('report', session_id=session)
        self.assertEqual(pending['status'], 'pending')
        self.assertEqual(pending['pending'], [{'tick': 1, 'group_id': 'atlas'}])
        authorized = self.authorize(session, 1, 'authorize')
        self.deliver_delivery(authorized['delivery_id'])
        report = self.client.post('report', session_id=session)
        self.assertEqual(report['status'], 'published')
        self.assertEqual(report['entries'],
                         [{'group_id': 'atlas', 'tick': 1, 'status': 'silent'}])
        self.gallery.restart()
        self.assertEqual(self.client.post('report', report_id=report['report_id']), report)
        self.assertEqual(self.client.post('report', session_id=session), report)

    def test_concurrent_receive_starts_once(self):
        session = self.open_correctable('atlas')
        self.tick(session, 1)
        left = self.panel('touch', session, 'L', 1, 'left')
        self.panel('seal', session, 'L', 1, 'left-seal')
        self.panel('seal', session, 'R', 1, 'right-seal')
        authorized = self.authorize(session, 1, 'authorize')
        deliveries = [authorized['delivery_id'], authorized['delivery_id'],
                      left['delivery_id'], left['delivery_id']]
        client = self.client
        with ThreadPoolExecutor(max_workers=4) as pool:
            acknowledgements = list(pool.map(self.deliver_delivery, deliveries))
        self.assertEqual(len({tuple(sorted(item.items())) for item in acknowledgements}), 2)
        result = self.inspect(session, 1)
        self.assertEqual((result['status'], result['rule_id']), ('started', 'ridge-alone'))
        self.assert_sources(result, left)
        self.assertEqual(self.plays(session), [result])
