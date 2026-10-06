import unittest
from research_automation.gui_backend import metadata_update_notice


class MetadataOutcomeTests(unittest.TestCase):
    def test_success_unchanged_partial_and_all_failure_states(self):
        for status in ('failed','rejected','deferred','blocked'):
            with self.subTest(status=status):
                outcome={'files':[{'source':'한글 파일.csv','status':status,'reason':'test reason'}]}
                notice=metadata_update_notice(outcome,'fallback.csv')
                self.assertFalse(notice['success']); self.assertIn('한글 파일.csv',notice['message'])
                self.assertIn('test reason',notice['message']); self.assertIn('새 결과 0개',notice['message'])
        notice=metadata_update_notice({'files':[{'status':'completed'},{'source':'other.csv','status':'failed'}]},'one.csv')
        self.assertFalse(notice['success']); self.assertIn('부분 갱신',notice['message']);self.assertIn('other.csv',notice['message'])
        self.assertTrue(metadata_update_notice({'status':'completed'},'one.csv')['success'])
        notice=metadata_update_notice({'status':'unchanged'},'one.csv')
        self.assertTrue(notice['success']); self.assertIn('새 결과를 생성하지 않았습니다',notice['message'])
        self.assertFalse(metadata_update_notice({'files':[]},'one.csv')['success'])
