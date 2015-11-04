from mock import Mock

import openerp.tests.common as test_common
from openerp.osv.orm import browse_record



class TestFailed(test_common.TransactionCase):
	def test_failded(self):
		self.assertEqual('42', '41')