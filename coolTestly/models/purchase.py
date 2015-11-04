from openerp import models, fields

class PurchaseOrder(models.Model):
	_inherit = 'purchase.order'

	couleur = fields.String('color')
	