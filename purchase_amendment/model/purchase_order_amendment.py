# -*- coding: utf-8 -*-
#
#
#    Authors: Guewen Baconnier
#    Copyright 2015 Camptocamp SA
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#

from functools import partial
import openerp.addons.decimal_precision as dp
from openerp import models, fields, api, exceptions, _
from openerp.tools import html2plaintext, float_compare


class PurchaseOrderAmendment(models.TransientModel):
    _name = 'purchase.order.amendment'

    purchase_id = fields.Many2one(comodel_name='purchase.order',
                                  string='Purchase Order',
                                  required=True,
                                  readonly=True)
    item_ids = fields.One2many(comodel_name='purchase.order.amendment.item',
                               inverse_name='amendment_id',
                               string='Items')
    reason = fields.Html()

    @api.model
    def default_get(self, fields):
        res = super(PurchaseOrderAmendment, self).default_get(fields)
        purchase_ids = self.env.context.get('active_ids', [])
        active_model = self.env.context.get('active_model')

        if not purchase_ids or len(purchase_ids) != 1:
            return res
        assert active_model == 'purchase.order', 'Bad context propagation'

        purchase = self.env['purchase.order'].browse(purchase_ids)

        if purchase.invoiced:
            raise exceptions.Warning(
                _('An invoiced order cannot be amended.')
            )

        items = []
        for line in purchase.order_line:
            if line.state in ('cancel', 'done'):
                continue
            items.append(self._prepare_item(line))
        res['item_ids'] = items
        return res

    @api.model
    def _prepare_item(self, purchase_line):
        ordered = purchase_line.product_qty

        shipped = 0.
        canceled = 0.
        for move in purchase_line.move_ids:
            if move.state == 'done':
                shipped += move.product_qty
            elif move.state == 'cancel':
                canceled += move.product_qty

        amend = ordered - canceled - shipped
        return {
            'purchase_line_id': purchase_line.id,
            'shipped_qty': shipped,
            'canceled_qty': canceled,
            'amend_qty': amend,
        }

    @api.multi
    def _message_content(self):
        title = _('Order amendment')
        message = '<h3>%s</h3><ul>' % title
        for item in self.item_ids:
            message += (_('<li><b>%s</b>: %s Ordered, %s '
                          'Shipped, %s Canceled, %s Amended</li>') %
                        (item.purchase_line_id.name,
                         item.ordered_qty, item.shipped_qty,
                         item.canceled_qty, item.amend_qty,
                         )
                        )
        message += '</ul>'
        # if the html field is touched, it may return '<br/>' or
        # '<p></p>' so check if it contains text at all
        if self.reason and html2plaintext(self.reason).strip():
            title = _('Reason for amending')
            message += "<h3>%s</h3><p>%s</p>" % (title, self.reason)
        return message

    @api.multi
    def do_amendment(self):
        self.ensure_one()
        self.item_ids.split_lines()
        purchase = self.purchase_id
        purchase.message_post(body=self._message_content())
        return True

    @api.multi
    def wizard_view(self):
        view = self.env.ref('purchase_amendment.view_purchase_order_amendment')

        return {
            'name': _('Enter the amendment details'),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'purchase.order.amendment',
            'views': [(view.id, 'form')],
            'view_id': view.id,
            'target': 'new',
            'res_id': self.id,
            'context': self.env.context,
        }


class PurchaseOrderAmendmentItem(models.TransientModel):
    _name = 'purchase.order.amendment.item'

    amendment_id = fields.Many2one(comodel_name='purchase.order.amendment',
                                   string='Amendment',
                                   required=True,
                                   ondelete='cascade',
                                   readonly=True)
    purchase_line_id = fields.Many2one(comodel_name='purchase.order.line',
                                       string='Line',
                                       required=True,
                                       readonly=True)
    ordered_qty = fields.Float(related='purchase_line_id.product_qty',
                               readonly=True)
    shipped_qty = fields.Float(string='Delivered',
                               readonly=True,
                               digits_compute=dp.get_precision('Product UoS'))
    canceled_qty = fields.Float(string='Canceled',
                                readonly=True,
                                digits_compute=dp.get_precision('Product UoS'))
    amend_qty = fields.Float(string='Amend',
                             digits_compute=dp.get_precision('Product UoS'))
    product_uom_id = fields.Many2one(related='purchase_line_id.product_uom',
                                     readonly=True)

    @api.constrains('amend_qty')
    def _constrains_amend_qty(self):
        max_qty = self.ordered_qty - self.shipped_qty
        min_qty = self.ordered_qty - self.shipped_qty - self.canceled_qty
        rounding = self.purchase_line_id.product_uom.rounding
        compare = partial(float_compare, precision_digits=rounding)
        if (compare(min_qty, self.amend_qty) == 1 or
                compare(self.amend_qty, max_qty) == 1):
            raise exceptions.ValidationError(
                _('The amended quantity for the product "%s" must be '
                  'between the canceled quantity of %0.2f and the ordered '
                  'quantity of %0.2f.') % (self.purchase_line_id.name,
                                           min_qty, max_qty)
            )

    @api.multi
    def split_lines(self):
        """ Split the order line according to selected quantities

        The shipped quantity is the quantity that will remain in the original
        purchases order line.
        The canceled quantity will split the original line and cancel the
        duplicated line.
        The amended quantity will split the original line; the
        duplicated line will be 'confirmed' and a new picking will be created.
        """
        for item in self:
            line = item.purchase_line_id
            amend_qty = item.amend_qty
            shipped_qty = item.shipped_qty
            ordered_qty = item.ordered_qty
            rounding = line.product_id.uom_id.rounding
            # the total canceled may be different than the one displayed
            # to the user, because the one displayed is the quantity
            # canceled in the *pickings*, here it includes also the
            # quantity removed when amending
            compare = partial(float_compare, precision_digits=rounding)
            canceled_qty = ordered_qty - shipped_qty - amend_qty
            if compare(canceled_qty, 0) == -1:  # Means: canceled_qty < 0
                canceled_qty = 0

            if (not (shipped_qty or canceled_qty) and
                    compare(amend_qty, ordered_qty) == 0):
                # Means: amend_qty == ordered_qty
                # the line is not changed
                continue

            if (not canceled_qty and
                    compare(shipped_qty + amend_qty, ordered_qty) == 0):
                # Means: shipped_qty + amend_qty == ordered_qty
                # part has been shipped but there is no reason to split
                # the lines
                continue

            procurements = line.procurement_ids
            if shipped_qty:
                # only keep the done procurement on the purchase line
                proc = procurements.filtered(lambda p: p.state == 'done')
                procurements -= proc
                # update the current line with the shipped qty,
                # the rest will be either canceled either amended,
                # either both
                line.write({
                    'product_qty': shipped_qty,
                    'procurement_ids': [(6, 0, proc.ids)],
                })

            if canceled_qty:
                # only keep the canceled procurement on the purchase line
                proc = procurements.filtered(lambda p: p.state == 'cancel')
                procurements -= proc
                if shipped_qty:
                    # current line kept for the shipped quantity so
                    # create a new one
                    values = {'product_qty': canceled_qty,
                              'procurement_ids': [(6, 0, proc.ids)]}
                    canceled_line = line.copy(default=values)
                else:
                    # cancel the current line
                    proc.cancel()
                    line.write({
                        'product_qty': canceled_qty,
                        'procurement_ids': [(6, 0, proc.ids)],
                    })
                    canceled_line = line
                canceled_line.action_cancel()

            if amend_qty:
                # link the new line with the remaining procurements
                # (not done nor canceled)
                values = {'product_qty': amend_qty,
                          'procurement_ids': [(6, 0, procurements.ids)]}

                original_amend_qty = (ordered_qty -
                                      shipped_qty -
                                      item.canceled_qty)
                if compare(amend_qty, original_amend_qty) != 0:
                    # Means: amend_qty != original_amend_qty
                    # We need to change the quantity of the move
                    # A new procurement will be generated for the line
                    procurements.cancel()
                    values['procurement_ids'] = False

                amend_line = line.copy(default=values)
                amend_line.action_confirm()
                for proc in amend_line.procurement_ids:
                    if proc.state == 'confirmed':
                        # if a new procurement has been created,
                        # create the move and change it to 'running'
                        proc.run()

        purchase = self.mapped('purchase_line_id.order_id')
        # Update the pickings according to the new procurements
        # TODO: ship recreate
        return True