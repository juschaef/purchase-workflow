import openerp.tests.common as test_common


class TestFailed(test_common.TransactionCase):
    def test_failded(self):
        self.assertEqual('42', '41')
