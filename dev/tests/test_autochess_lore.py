import json
import unittest

import autocombat_backend as backend
import autochess_lore as ac_lore


class AutoChessLoreTests(unittest.TestCase):
    def setUp(self):
        self.client = backend.app.test_client()

    def test_catalog_contains_all_19_unit_lore_profiles_and_lean_story_index(self):
        resp = self.client.get('/api/ui/autochess/catalog')
        self.assertEqual(resp.status_code, 200)
        self.assertLess(len(resp.data), 160 * 1024, 'catalog response must not embed huge long-form stories')

        payload = resp.get_json()
        wiki_units = payload['wiki_units']
        story_index = payload['story_index']
        index_by_id = {s['id']: s for s in story_index}

        for idx in range(1, 20):
            serial = f'Y{idx}'
            self.assertIn(serial, wiki_units)
            lore = wiki_units[serial].get('lore')
            self.assertIsInstance(lore, dict, f'{serial} missing lore')
            self.assertTrue(lore['profile_fields'], f'{serial} missing profile_fields')

        # Inline short stories (Y1-Y8, Y12)
        for serial in ('Y1', 'Y2', 'Y3', 'Y4', 'Y5', 'Y6', 'Y7', 'Y8', 'Y12'):
            lore = wiki_units[serial]['lore']
            self.assertEqual(lore['story_mode'], 'inline', serial)
            self.assertTrue(lore['story_text'], serial)
            self.assertIn(lore['story_id'], index_by_id)

        # Profile-only units without backstory text (Y9, Y10, Y11, Y13)
        for serial in ('Y9', 'Y10', 'Y11', 'Y13'):
            lore = wiki_units[serial]['lore']
            self.assertEqual(lore['story_mode'], 'none', serial)
            self.assertIsNone(lore['story_id'], serial)
            self.assertNotIn(f'unit_{serial}', index_by_id)

        # Long stories with jump mode (Y14-Y19)
        for serial in ('Y14', 'Y15', 'Y16', 'Y17', 'Y18', 'Y19'):
            lore = wiki_units[serial]['lore']
            self.assertEqual(lore['story_mode'], 'jump', serial)
            self.assertEqual(lore['story_text'], '', serial)
            self.assertTrue(lore['story_excerpt'], serial)
            self.assertIn(lore['story_id'], index_by_id)

        # Y8 friends deduplication check
        y8_friends = next(f['value'] for f in wiki_units['Y8']['lore']['profile_fields'] if f['label'] == '友人')
        self.assertNotIn('比哈米', y8_friends)

        # Strict card-only profile checks on Y18 & Y19
        forbidden = {'学校', '班级', '年级', '社团', '成为魔法少女的时间', '退出魔法少女的时间', '友人', '讨厌的人'}
        for serial in ('Y18', 'Y19'):
            labels = {f['label'] for f in wiki_units[serial]['lore']['profile_fields']}
            self.assertFalse(labels & forbidden, f'{serial} leaked non-card fields: {labels & forbidden}')

        y18_name = next(f['value'] for f in wiki_units['Y18']['lore']['profile_fields'] if f['label'] == '原名')
        y19_name = next(f['value'] for f in wiki_units['Y19']['lore']['profile_fields'] if f['label'] == '原名')
        self.assertEqual(y18_name, '张诗谣')
        self.assertIn('石津', y19_name)

        # Y18 standalone prequel reference
        extra = wiki_units['Y18']['lore'].get('extra_stories') or []
        self.assertTrue(any(ex['id'] == 'y18_prequel' for ex in extra))
        self.assertIn('y18_prequel', index_by_id)
        self.assertEqual(index_by_id['y18_prequel']['category'], 'prequel')
        self.assertEqual(index_by_id['y18_prequel']['chapter_count'], 5)

        # Opening story index check
        self.assertIn('opening_fuzhe', index_by_id)
        self.assertEqual(index_by_id['opening_fuzhe']['category'], 'opening')
        self.assertEqual(index_by_id['opening_fuzhe']['chapter_count'], 10)

        # Ensure index payload does not contain raw paragraph lists
        for item in story_index:
            for ch in item['chapters']:
                self.assertNotIn('paragraphs', ch)

    def test_stories_endpoints_and_ooc_cleanup(self):
        list_resp = self.client.get('/api/ui/autochess/stories')
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(len(list_resp.get_json()['stories']), 17)

        # Opening story fetches only ch_01 by default or when requested
        ch1_resp = self.client.get('/api/ui/autochess/stories/opening_fuzhe?chapter=ch_01')
        self.assertEqual(ch1_resp.status_code, 200)
        st = ch1_resp.get_json()['story']
        self.assertEqual(st['active_chapter_id'], 'ch_01')
        self.assertEqual(len(st['chapters']), 10)
        self.assertTrue(st['chapters'][0].get('paragraphs'))
        self.assertNotIn('paragraphs', st['chapters'][1])

        # Second chapter on demand
        ch2_resp = self.client.get('/api/ui/autochess/stories/opening_fuzhe?chapter=ch_02')
        self.assertEqual(ch2_resp.status_code, 200)
        st2 = ch2_resp.get_json()['story']
        self.assertEqual(st2['active_chapter_id'], 'ch_02')
        self.assertNotIn('paragraphs', st2['chapters'][0])
        self.assertTrue(st2['chapters'][1].get('paragraphs'))

        # Y16 dual-chapter (prequel + main)
        y16_resp = self.client.get('/api/ui/autochess/stories/unit_Y16')
        self.assertEqual(y16_resp.status_code, 200)
        y16 = y16_resp.get_json()['story']
        self.assertEqual(len(y16['chapters']), 2)
        self.assertIn('夜空之下', y16['chapters'][0]['title'])
        self.assertIn('林白', y16['chapters'][1]['title'])
        self.assertGreater(y16['word_count'], 3000)

        # Y18 standalone prequel OOC cleanup
        pre_resp = self.client.get('/api/ui/autochess/stories/y18_prequel')
        self.assertEqual(pre_resp.status_code, 200)
        pre = pre_resp.get_json()['story']
        self.assertEqual(len(pre['chapters']), 5)
        all_pre_text = '\n'.join(
            p['text'] for ch in pre['chapters'] for p in ch.get('paragraphs', [])
        )
        for ooc in ('ds的概括', 'pl的九岁习作', '1d6=1'):
            self.assertNotIn(ooc, all_pre_text)

        # Y15 & Y17 OOC cleanup
        y15 = ac_lore.get_story_detail('unit_Y15')
        y15_txt = '\n'.join(p['text'] for ch in y15['chapters'] for p in ch['paragraphs'])
        self.assertNotIn('pl个人层面', y15_txt)
        y17_prof = json.dumps(ac_lore.get_unit_lore('Y17')['profile_fields'], ensure_ascii=False)
        self.assertNotIn('我设计的初衷就是这个', y17_prof)

        # 404 boundaries
        self.assertEqual(self.client.get('/api/ui/autochess/stories/does_not_exist').status_code, 404)
        self.assertEqual(
            self.client.get('/api/ui/autochess/stories/opening_fuzhe?chapter=bad_ch').status_code,
            404,
        )
