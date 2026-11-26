from tests.support import GalleryTest, gallery_input, open_gallery


class ProgramTests(GalleryTest):
    def test_release_and_open(self):
        data = gallery_input()
        issued = self.client.post('issue', **data['show'])
        self.assertEqual(issued['audio'], data['show']['audio'])
        self.assertEqual([r['rule_id'] for r in issued['groups'][0]['rules']], ['two-boards', 'ridge-alone'])
        self.assertEqual(self.client.get('show', show_id=issued['show_id']), issued)
        opened = self.client.post('open', show_id=issued['show_id'], bindings=data['bindings'])
        self.assertEqual(opened['show_id'], issued['show_id'])
        self.assertEqual(opened['bindings'], data['bindings'])
        self.assertEqual((opened['last_tick'], opened['closed_tick']), (0, None))
        self.assertEqual(self.client.get('session', session_id=opened['session_id']), opened)

    def test_cross_group_rule_rejected(self):
        data = gallery_input()
        data['show']['groups'][0]['rules'][0]['requires'] = ['M']
        self.rejected('cross_group_rule', 'issue', status=400, **data['show'])
        self.rejected('unknown_show', 'show', method='get', status=404, show_id=1)
        self.assertEqual(self.client.post('issue', **gallery_input()['show'])['show_id'], 1)

    def test_invalid_priority(self):
        data = gallery_input()
        rules = data['show']['groups'][0]['rules']
        for priority in (rules[0]['priority'], True, -1):
            with self.subTest(priority=priority):
                rules[1]['priority'] = priority
                self.rejected('invalid_priority', 'issue', status=400, **data['show'])
        self.rejected('unknown_show', 'show', method='get', status=404, show_id=1)

    def test_unknown_audio(self):
        data = gallery_input()
        data['show']['groups'][0]['rules'][0]['audio_id'] = 'missing-clip'
        self.rejected('unknown_audio', 'issue', status=400, **data['show'])
        self.rejected('unknown_show', 'show', method='get', status=404, show_id=1)

    def test_invalid_binding(self):
        data = gallery_input()
        show = self.client.post('issue', **data['show'])['show_id']
        good = data['bindings']
        bad_bindings = (
            good[:-1], good + [good[0]],
            [{**good[0], 'group_id': 'minerals'}, *good[1:]],
            [{**good[0], 'position': good[1]['position']}, *good[1:]],
        )
        for bindings in bad_bindings:
            with self.subTest(bindings=bindings):
                self.rejected('invalid_binding', 'open', status=400, show_id=show, bindings=bindings)
        self.rejected('unknown_show', 'open', status=404, show_id=show + 1, bindings=good)
        self.rejected('unknown_session', 'session', method='get', status=404, session_id=1)
        self.assertEqual(self.client.post('open', show_id=show, bindings=good)['session_id'], 1)

    def test_pinned_after_reissue(self):
        data = gallery_input('atlas')
        old = self.client.post('issue', **data['show'])
        old_session = self.client.post('open', show_id=old['show_id'], bindings=data['bindings'])
        data['show']['audio'][0].update(name='修订山脊', length_ticks=8)
        new = open_gallery(self.client, data)
        reused = self.client.post('open', show_id=old['show_id'], bindings=data['bindings'])
        for session, expected in (
            (old_session, {'audio_id': 'ridge', 'name': '触摸山脊', 'length_ticks': 2}),
            (new, {'audio_id': 'ridge', 'name': '修订山脊', 'length_ticks': 8}),
            (reused, {'audio_id': 'ridge', 'name': '触摸山脊', 'length_ticks': 2}),
        ):
            session_id = session['session_id']
            self.tick(session_id, 1)
            self.client.deliver(self.panel('touch', session_id, 'L', 1, 'left'))
            self.client.deliver(self.panel('seal', session_id, 'R', 1, 'right-seal'))
            self.assertEqual(self.inspect(session_id, 1)['clip'], expected)
        self.assertEqual(self.client.get('show', show_id=old['show_id']), old)

    def test_initialize_preserves_user_data(self):
        self.rejected('unknown_show', 'show', method='get', status=404, show_id=1)
        data = gallery_input('minerals')
        data['show']['audio'][2]['name'] = '布展员自定矿石讲解'
        issued = self.client.post('issue', **data['show'])
        opened = self.client.post('open', show_id=issued['show_id'], bindings=data['bindings'])
        for _ in range(2):
            self.gallery.restart()
            self.assertEqual(self.client.get('show', show_id=issued['show_id']), issued)
            self.assertEqual(self.client.get('session', session_id=opened['session_id']), opened)
        second = self.client.post('issue', **data['show'])
        self.assertEqual(second['show_id'], issued['show_id'] + 1)
