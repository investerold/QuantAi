"""
Smoke / unit tests for news_watchdog without hitting any real APIs.
Run: python -m unittest tests.test_news_watchdog
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Stub bot.send_telegram_message before importing news_watchdog
sys.modules.setdefault('bot', mock.MagicMock())

import news_watchdog as nw  # noqa: E402


class ClassifyErrorTests(unittest.TestCase):
    def test_hard_quota_limit_zero(self):
        err = (
            "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
            "'You exceeded your current quota ... limit: 0, model: gemini-2.0-flash "
            "GenerateRequestsPerDayPerProjectPerModel-FreeTier ... retryDelay 1s'}}"
        )
        kind, _ = nw._classify_gemini_error(err)
        self.assertEqual(kind, 'hard_quota')

    def test_transient_short_retry(self):
        err = "429 RESOURCE_EXHAUSTED retryDelay: 5s"
        kind, delay = nw._classify_gemini_error(err)
        self.assertEqual(kind, 'transient')
        self.assertEqual(delay, 5)

    def test_auth_error(self):
        err = "API key not valid. Please pass a valid API key."
        kind, _ = nw._classify_gemini_error(err)
        self.assertEqual(kind, 'auth')

    def test_other_error(self):
        kind, _ = nw._classify_gemini_error("random network blip")
        self.assertEqual(kind, 'other')


class RuleBasedTests(unittest.TestCase):
    def test_strong_signal_triggers(self):
        out = nw._rule_based_analysis('NVDA', 'Nvidia beats estimates on Q4 earnings', '')
        self.assertIn('🚨', out)
        self.assertIn('財報', out)

    def test_noise_skipped(self):
        out = nw._rule_based_analysis('NVDA', 'Analyst raises price target', 'just a chatter piece')
        self.assertEqual(out, 'SKIP')

    def test_empty_skipped(self):
        self.assertEqual(nw._rule_based_analysis('X', '', ''), 'SKIP')


class AnalyzeFallbackTests(unittest.TestCase):
    def setUp(self):
        nw._gemini_disabled_for_run = False
        nw._gemini_disabled_reason = ''
        # 清除 admin 通知 flag
        try:
            os.remove(nw.QUOTA_ADMIN_NOTIFIED_FLAG)
        except OSError:
            pass

    @mock.patch.dict(os.environ, {'GEMINI_API_KEY': 'fake', 'ANALYSIS_MODE': 'auto'})
    def test_hard_quota_disables_run_and_falls_back(self):
        nw.GEMINI_API_KEY = 'fake'
        nw.ANALYSIS_MODE = 'auto'

        fake_genai = mock.MagicMock()
        fake_client = mock.MagicMock()

        class FakeQuotaError(Exception):
            pass

        fake_client.models.generate_content.side_effect = FakeQuotaError(
            "429 RESOURCE_EXHAUSTED limit: 0 free_tier"
        )
        fake_genai.Client.return_value = fake_client

        with mock.patch.dict(sys.modules, {'google': mock.MagicMock(genai=fake_genai),
                                           'google.genai': fake_genai}):
            # 第一單會觸發 hard_quota
            out1 = nw.analyze_news_gemini('NVDA', 'Nvidia beats estimates', 'big quarter')
            # 第二單應該直接 fallback,唔再 call Gemini
            out2 = nw.analyze_news_gemini('TSLA', 'Tesla recall announced', '')

        self.assertTrue(nw._gemini_disabled_for_run)
        self.assertEqual(fake_client.models.generate_content.call_count, 1,
                         "硬性配額後唔應該再試 Gemini")
        self.assertIn('🚨', out1)  # rule fallback hit
        self.assertIn('🚨', out2)

    @mock.patch.dict(os.environ, {'GEMINI_API_KEY': 'fake'})
    def test_rules_mode_skips_gemini_entirely(self):
        nw.GEMINI_API_KEY = 'fake'
        nw.ANALYSIS_MODE = 'rules'
        with mock.patch('news_watchdog.requests') as _:
            out = nw.analyze_news_gemini('NVDA', 'Nvidia tops estimates', '')
        self.assertIn('🚨', out)


if __name__ == '__main__':
    unittest.main()
