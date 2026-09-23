import unittest
from utils.saavn import is_saavn_match
from utils.ytdl import extract_expected_artist, get_search_candidates

class TestSaavnMatching(unittest.TestCase):
    def test_artist_contradiction_rejected(self):
        # When Darshan Raval is expected, Shahid Mallya should be rejected
        matched = is_saavn_match(
            query="Ye Baarish",
            song_title="Ye Baarish Roz Aa Jaye",
            singers="Shahid Mallya, Munish Yadav",
            expected_artist="Darshan Raval"
        )
        self.assertFalse(matched)

    def test_correct_artist_accepted(self):
        matched = is_saavn_match(
            query="Ye Baarish",
            song_title="Ye Baarish",
            singers="Darshan Raval",
            expected_artist="Darshan Raval"
        )
        self.assertTrue(matched)

    def test_extract_expected_artist(self):
        artist1 = extract_expected_artist("Ye Baarish | Darshan Raval | Official 2017 | Love Song")
        self.assertEqual(artist1, "Darshan Raval")

        artist2 = extract_expected_artist("Zaeden - kya karoon?", "Zaeden")
        self.assertEqual(artist2, "Zaeden")

        # Label channel should be ignored in favor of title segment
        artist3 = extract_expected_artist(
            "Maine Khud Ko Ragini MMS 2 Song With Lyrics | Sunny Leone | Mustafa Zahid",
            "T-Series"
        )
        self.assertEqual(artist3, "Sunny Leone")

    def test_candidate_generation_does_not_drop_artist(self):
        cands = get_search_candidates("Ye Baarish | Darshan Raval | Official 2017 | Love Song")
        # Ensure single naked "Ye Baarish" is NOT in candidates when artist was in segment
        self.assertNotIn("Ye Baarish", cands)
        self.assertIn("Ye Baarish Darshan Raval", cands)

if __name__ == '__main__':
    unittest.main()
