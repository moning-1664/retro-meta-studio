import json
import shutil
import unittest
from pathlib import Path

import config as cfgmod
from api import Api
from database.shadow import ShadowConsistencyChecker


class ShadowCheckerUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path('/tmp/rmm_shadow_checker_' + self.id().split('.')[-1])
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self.log = self.tmp / 'mismatch.log'

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_off_mode_does_not_count_or_log(self):
        c = ShadowConsistencyChecker(self.log, 'off')
        self.assertTrue(c.compare('x', {'a': 1}, {'a': 2}))
        self.assertEqual(c.summary()['comparisons'], 0)
        self.assertFalse(self.log.exists() and self.log.read_text(encoding='utf-8'))

    def test_shadow_equal_scalars(self):
        c = ShadowConsistencyChecker(self.log, 'shadow')
        self.assertTrue(c.compare('scalar', '한글', '한글'))
        self.assertEqual(c.summary()['matches'], 1)

    def test_shadow_equal_nested_dict_order_independent(self):
        c = ShadowConsistencyChecker(self.log, 'shadow')
        a = {'b': {'z': 2, 'a': 1}, 'a': [1, {'x': '테스트'}]}
        b = {'a': [1, {'x': '테스트'}], 'b': {'a': 1, 'z': 2}}
        self.assertTrue(c.compare('nested', a, b))

    def test_shadow_detects_missing_field(self):
        c = ShadowConsistencyChecker(self.log, 'shadow')
        self.assertFalse(c.compare('missing', {'a': 1, 'b': 2}, {'a': 1}))
        text = self.log.read_text(encoding='utf-8')
        self.assertIn('DB_SHADOW_MISMATCH', text)
        self.assertIn('missing', text)

    def test_shadow_detects_changed_unicode(self):
        c = ShadowConsistencyChecker(self.log, 'shadow')
        self.assertFalse(c.compare('unicode', {'name': '마리오'}, {'name': '마리오 USA'}))
        self.assertIn('마리오 USA', self.log.read_text(encoding='utf-8'))

    def test_shadow_detects_list_length(self):
        c = ShadowConsistencyChecker(self.log, 'shadow')
        self.assertFalse(c.compare('media-list', ['a', 'b'], ['a']))

    def test_shadow_detects_list_order_when_semantically_significant(self):
        c = ShadowConsistencyChecker(self.log, 'shadow')
        self.assertFalse(c.compare('ordered', ['cover', 'shot'], ['shot', 'cover']))

    def test_strict_raises_on_mismatch(self):
        c = ShadowConsistencyChecker(self.log, 'strict')
        with self.assertRaises(AssertionError):
            c.compare('strict-case', {'x': 1}, {'x': 2})
        self.assertEqual(c.summary()['mismatches'], 1)

    def test_strict_allows_equal(self):
        c = ShadowConsistencyChecker(self.log, 'strict')
        self.assertTrue(c.compare('strict-ok', {'x': 1}, {'x': 1}))

    def test_mode_validation(self):
        c = ShadowConsistencyChecker(self.log, 'off')
        with self.assertRaises(ValueError):
            c.set_mode('invalid')

    def test_summary_counts(self):
        c = ShadowConsistencyChecker(self.log, 'shadow')
        c.compare('a', 1, 1)
        c.compare('b', 1, 2)
        c.compare('c', 3, 3)
        self.assertEqual(c.summary()['comparisons'], 3)
        self.assertEqual(c.summary()['matches'], 2)
        self.assertEqual(c.summary()['mismatches'], 1)


class ApiShadowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path('/tmp/rmm_api_shadow_' + self.id().split('.')[-1])
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self.orig_config = cfgmod.CONFIG_PATH
        self.orig_backup = cfgmod.BACKUP_DIR
        cfgmod.CONFIG_PATH = self.tmp / 'config.json'
        cfgmod.BACKUP_DIR = self.tmp / 'backup'
        self.api = Api()
        self.assertTrue(self.api.set_masterdb_path(str(self.tmp / 'master'))['ok'])
        self.assertTrue(self.api.set_database_debug('shadow')['ok'])

    def tearDown(self):
        try:
            if getattr(self.api, '_sqlite', None):
                self.api._sqlite.close()
            if getattr(self.api, '_shadow', None):
                self.api._shadow.close()
        finally:
            cfgmod.CONFIG_PATH = self.orig_config
            cfgmod.BACKUP_DIR = self.orig_backup
            shutil.rmtree(self.tmp, ignore_errors=True)

    def seed(self, count=1):
        for i in range(count):
            key = f'snes|Game {i}.zip'
            self.api.db.setdefault('roms', {})[key] = {
                'system': 'snes', 'rom_filename': f'Game {i}.zip',
                'default_version_id': 'v1', 'core_override': None,
                'versions': {'v1': {'created_at': '2026-01-01T00:00:00', 'source_local_id': 'setA',
                                   'uncertain_match': False,
                                   'fields': {'name': f'게임 {i}', 'desc': '설명', 'genre': 'Action', 'tags': ['A', 'B']}}},
                'media': {'covers': f'/tmp/cover{i}.png', 'screenshots': [f'/tmp/s{i}a.png', f'/tmp/s{i}b.png']}
            }
        self.api._save_db()

    def test_debug_mode_persists(self):
        self.assertEqual(self.api.get_database_debug()['data']['mode'], 'shadow')
        data = json.loads(cfgmod.CONFIG_PATH.read_text(encoding='utf-8'))
        self.assertEqual(data['database_debug']['mode'], 'shadow')

    def test_write_path_shadow_check_matches(self):
        self.seed(1)
        summary = self.api.get_database_debug()['data']
        self.assertGreaterEqual(summary['mismatches'], 0)
        self.assertGreater(summary['writesChecked'], 0)
        self.assertEqual(summary['mismatches'], 0)

    def test_read_list_runs_shadow_check(self):
        self.seed(3)
        before = self.api.get_database_debug()['data']['comparisons']
        result = self.api.list_masterdb_games()
        self.assertTrue(result['ok'])
        after = self.api.get_database_debug()['data']['comparisons']
        self.assertGreater(after, before)
        self.assertEqual(self.api.get_database_debug()['data']['mismatches'], 0)

    def test_read_detail_runs_shadow_check(self):
        self.seed(1)
        key = 'snes|Game 0.zip'
        before = self.api.get_database_debug()['data']['comparisons']
        result = self.api.get_game_detail(key, lightweight=True)
        self.assertTrue(result['ok'])
        self.assertGreater(self.api.get_database_debug()['data']['comparisons'], before)
        self.assertEqual(self.api.get_database_debug()['data']['mismatches'], 0)

    def test_detects_sqlite_rom_field_divergence_on_read(self):
        self.seed(1)
        rom_id = self.api._sqlite._rom_id('snes|Game 0.zip')
        self.api._sqlite.conn.execute('UPDATE roms SET filename=? WHERE rom_id=?', ('BROKEN.zip', rom_id))
        self.api._sqlite.conn.commit()
        result = self.api.list_masterdb_games()
        self.assertTrue(result['ok'])  # shadow mode reports, but does not break the app
        summary = self.api.get_database_debug()['data']
        self.assertEqual(summary['mismatches'], 1)
        self.assertTrue(Path(summary['logPath']).exists())
        self.assertIn('BROKEN.zip', Path(summary['logPath']).read_text(encoding='utf-8'))

    def test_detects_sqlite_metadata_divergence_on_detail(self):
        self.seed(1)
        rom_id = self.api._sqlite._rom_id('snes|Game 0.zip')
        self.api._sqlite.conn.execute('UPDATE metadata_versions SET fields_json=? WHERE rom_id=?',
                                      (json.dumps({'name': 'DB만 다른 제목'}, ensure_ascii=False), rom_id))
        self.api._sqlite.conn.commit()
        result = self.api.get_game_detail('snes|Game 0.zip', lightweight=True)
        self.assertTrue(result['ok'])
        self.assertEqual(self.api.get_database_debug()['data']['mismatches'], 1)

    def test_detects_sqlite_media_divergence(self):
        self.seed(1)
        rom_id = self.api._sqlite._rom_id('snes|Game 0.zip')
        self.api._sqlite.conn.execute('DELETE FROM media WHERE rom_id=? AND media_type=?', (rom_id, 'covers'))
        self.api._sqlite.conn.commit()
        self.api.get_game_detail('snes|Game 0.zip', lightweight=True)
        self.assertEqual(self.api.get_database_debug()['data']['mismatches'], 1)

    def test_empty_database_is_consistent(self):
        self.api._save_db()
        self.api.list_masterdb_games()
        self.assertEqual(self.api.get_database_debug()['data']['mismatches'], 0)

    def test_multiple_versions_and_media_are_consistent(self):
        self.seed(1)
        rom = self.api.db['roms']['snes|Game 0.zip']
        rom['versions']['v2'] = {'created_at': '2026-02-01T00:00:00', 'source_local_id': 'setB',
                                 'uncertain_match': True, 'fields': {'name': '두 번째 버전', 'tags': []}}
        rom['default_version_id'] = 'v2'
        rom['media']['videos'] = ['/tmp/a.mp4', '/tmp/b.mp4']
        self.api._save_db()
        self.api.get_game_detail('snes|Game 0.zip', lightweight=True)
        self.assertEqual(self.api.get_database_debug()['data']['mismatches'], 0)

    def test_special_filename_and_unicode_are_consistent(self):
        self.api.db['roms']['ps1|게임 [한] (테스트) | ?.zip'] = {
            'system': 'ps1', 'rom_filename': '게임 [한] (테스트) | ?.zip', 'default_version_id': 'x',
            'versions': {'x': {'created_at': '', 'source_local_id': '', 'uncertain_match': False,
                               'fields': {'name': '파이널 판타지 VII', 'desc': '따옴표 " 줄바꿈\n 특수문자 ✓'}}},
            'media': {}
        }
        self.api._save_db()
        self.api.list_masterdb_games()
        self.assertEqual(self.api.get_database_debug()['data']['mismatches'], 0)

    def test_no_metadata_version_is_consistent(self):
        self.api.db['roms']['nes|NoMeta.zip'] = {'system': 'nes', 'rom_filename': 'NoMeta.zip',
                                                  'default_version_id': None, 'versions': {}, 'media': {}}
        self.api._save_db()
        self.api.get_game_detail('nes|NoMeta.zip', lightweight=True)
        self.assertEqual(self.api.get_database_debug()['data']['mismatches'], 0)

    def test_core_override_null_and_empty_are_preserved(self):
        self.api.db['nes|Core.zip'] = {'system': 'nes', 'rom_filename': 'Core.zip',
                                       'default_version_id': None, 'core_override': '', 'versions': {}, 'media': {}}
        self.api._save_db()
        self.api.list_masterdb_games()
        self.assertEqual(self.api.get_database_debug()['data']['mismatches'], 0)

    def test_disable_shadow_stops_new_comparisons(self):
        self.seed(1)
        self.api.set_database_debug('off')
        before = self.api.get_database_debug()['data']['comparisons']
        self.api.list_masterdb_games()
        self.assertEqual(self.api.get_database_debug()['data']['comparisons'], before)

    def test_strict_mode_surfaces_corruption(self):
        self.seed(1)
        self.api.set_database_debug('strict')
        rom_id = self.api._sqlite._rom_id('snes|Game 0.zip')
        self.api._sqlite.conn.execute('UPDATE roms SET filename=? WHERE rom_id=?', ('BAD.zip', rom_id))
        self.api._sqlite.conn.commit()
        with self.assertRaises(AssertionError):
            self.api.list_masterdb_games()


if __name__ == '__main__':
    unittest.main()

class ShadowStressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path('/tmp/rmm_shadow_stress_' + self.id().split('.')[-1])
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        self.orig_config = cfgmod.CONFIG_PATH
        self.orig_backup = cfgmod.BACKUP_DIR
        cfgmod.CONFIG_PATH = self.tmp / 'config.json'
        cfgmod.BACKUP_DIR = self.tmp / 'backup'
        self.api = Api()
        self.api.set_masterdb_path(str(self.tmp / 'master'))
        self.api.set_database_debug('shadow')

    def tearDown(self):
        if getattr(self.api, '_sqlite', None):
            self.api._sqlite.close()
        if getattr(self.api, '_shadow', None):
            self.api._shadow.close()
        cfgmod.CONFIG_PATH = self.orig_config
        cfgmod.BACKUP_DIR = self.orig_backup
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_250_rom_mixed_fixture_roundtrip(self):
        """Stress: 빈 metadata부터 다중 version/media/Unicode filename까지 한 번에 검증."""
        systems = ['nes', 'snes', 'ps1', 'ps2', 'msx', 'megadrive']
        for i in range(250):
            system = systems[i % len(systems)]
            suffix = ' 한글 ✓' if i % 17 == 0 else (' [K]' if i % 13 == 0 else '')
            filename = f'Game_{i:03d}{suffix}.zip'
            key = f'{system}|{filename}'
            versions = {}
            if i % 7 != 0:
                for v in range((i % 4) + 1):
                    versions[f'v{i}_{v}'] = {
                        'created_at': f'2026-01-{(v+1):02d}T00:00:00',
                        'source_local_id': f'set{i % 3}',
                        'uncertain_match': (v == 1 and i % 5 == 0),
                        'fields': {
                            'name': '' if i % 19 == 0 and v == 0 else f'게임 {i} / 버전 {v}',
                            'desc': '설명\n' if i % 11 == 0 else '',
                            'genre': 'RPG' if i % 3 == 0 else '',
                            'tags': [] if i % 9 == 0 else ['A', 'B'],
                        }
                    }
            media = {}
            if i % 2 == 0:
                media['covers'] = f'/fixture/{i}.png'
            if i % 3 == 0:
                media['screenshots'] = [f'/fixture/{i}_1.png', f'/fixture/{i}_2.png']
            if i % 5 == 0:
                media['videos'] = [f'/fixture/{i}.mp4']
            self.api.db['roms'][key] = {
                'system': system,
                'rom_filename': filename,
                'default_version_id': next(iter(versions), None),
                'core_override': '' if i % 23 == 0 else (f'core{i % 4}' if i % 10 == 0 else None),
                'versions': versions,
                'media': media,
            }
        self.api._save_db()
        self.api.list_masterdb_games()
        summary = self.api.get_database_debug()['data']
        self.assertEqual(summary['mismatches'], 0)
        self.assertGreater(summary['writesChecked'], 0)
        self.assertEqual(self.api._sqlite.count_roms(), 250)



if __name__ == '__main__':
    unittest.main()
