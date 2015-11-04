from openerp import tests

class TestFailed(TransactionCase):
	def test_failded(self):
		self.assertEqual('42', '41')