import tempfile
import unittest
from pathlib import Path
from telegram_scooter_bot import IdentityStore, classify_server_score, parse_play


class ParsePlayTests(unittest.TestCase):
    def test_example_and_optional_bot_suffix(self):
        self.assertEqual(parse_play('/play @kuzhh_89 800-1000'), ('kuzhh_89', 800, 1000))
        self.assertEqual(parse_play('/play@my_game_bot scooter_1 9000-11000'), ('scooter_1', 9000, 11000))

    def test_invalid_syntax_and_alias_length(self):
        for text in ('/play 800-1000', '/play @ab 1-2', '/play @name 1-2 extra'):
            with self.subTest(text=text):
                self.assertIsNone(parse_play(text))
        with self.assertRaisesRegex(ValueError, 'upper score bound'):
            parse_play('/play @rider 1000-800')


class ServerScoreTests(unittest.TestCase):
    def test_out_of_range_server_score_is_not_a_success(self):
        self.assertEqual(classify_server_score(54, 8504, 8500, 10000), 'out_of_range')
        self.assertEqual(classify_server_score(8504, 8504, 8500, 10000), 'match')
        self.assertEqual(classify_server_score(8510, 8504, 8500, 10000), 'in_range_mismatch')
        self.assertEqual(classify_server_score(None, 8504, 8500, 10000), 'missing')


class IdentityStoreTests(unittest.TestCase):
    def test_name_is_bound_once_and_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = IdentityStore(Path(tmp) / 'ids.sqlite3')
            self.assertIsNone(store.get('100'))
            self.assertIsNone(store.owner('Rider_1'))
            store.bind('100', 'Rider_1')
            self.assertEqual(store.get('100'), 'Rider_1')
            self.assertEqual(store.owner('rider_1'), '100')
            with self.assertRaises(Exception):
                store.bind('200', 'Rider_1')
            store.close()


if __name__ == '__main__':
    unittest.main()
