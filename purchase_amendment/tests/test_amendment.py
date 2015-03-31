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

from openerp import exceptions
from openerp.tests import common


class TestAmendmentCombinations(common.TransactionCase):

    def setUp(self):
        super(TestAmendmentCombinations, self).setUp()
        self.amendment_model = self.env['purchase.order.amendment']
        self.purchase_model = self.env['purchase.order']
        self.purchase_line_model = self.env['purchase.order.line']
        self.partner1 = self.env.ref('base.res_partner_1')
        self.product1 = self.env.ref('product.product_product_7')
        self.product2 = self.env.ref('product.product_product_9')
        self.product3 = self.env.ref('product.product_product_11')
        self.location_stock = self.env.ref('stock.stock_location_stock')
        self.purchase_pricelist = self.env.ref('purchase.list0')
        self.purchase = self._create_purchase([(self.product1, 1000),
                                               (self.product2, 500),
                                               (self.product3, 800)])
        self.purchase.signal_workflow('purchase_confirm')

    def _create_purchase(self, line_products):
        """ Create a purchase order.

        ``line_products`` is a list of tuple [(product, qty)]
        """
        lines = []
        for product, qty in line_products:
            line_values = {
                'product_id': product.id,
                'product_qty': qty,
                'product_uom': product.uom_id.id,
                'price_unit': 50,
            }
            onchange_res = self.purchase_line_model.product_id_change(
                self.purchase_pricelist.id,
                product.id,
                qty,
                product.uom_id.id,
                self.partner1.id)
            line_values.update(onchange_res['value'])
            lines.append(
                (0, 0, line_values)
            )
        return self.purchase_model.create({
            'partner_id': self.partner1.id,
            'location_id': self.location_stock.id,
            'pricelist_id': self.purchase_pricelist.id,
            'order_line': lines,
        })

    def _search_picking_by_product(self, product, qty):
        return self.purchase.picking_ids.filtered(
            lambda p: any(move.product_id == product and
                          move.product_qty >= qty and
                          move.state in ('confirmed', 'assigned')
                          for move in p.move_lines)
        )[0]

    def ship(self, products=None):
        """ Ship products of a picking

        products is a list of tuples [(product, qty)]
        """
        operations = {}
        pickings = self.env['stock.picking'].browse()
        if products:
            for product, qty in products:
                picking = self._search_picking_by_product(product, qty)
                pickings |= picking
                operations.setdefault(picking, []).append((product, qty))
        else:
            # ship all
            pickings = self.purchase.picking_ids.filtered(
                lambda p: p.state not in ('cancel', 'done')
            )
            for picking in pickings:
                operations[picking] = []

        pickings.do_prepare_partial()

        for picking, product_qtys in operations.iteritems():
            for (product, qty) in product_qtys:
                pack_operation = picking.pack_operation_ids.filtered(
                    lambda p: p.product_id == product
                )
                pack_operation.product_qty = qty
        pickings.do_transfer()
        for picking in pickings:
            self.assertEqual(picking.state, 'done')

    def split(self, products):
        """ Split pickings

        ``products`` is a list of tuples [(product, quantity)]
        """
        operations = {}
        pickings = self.env['stock.picking'].browse()
        for product, qty in products:
            picking = self._search_picking_by_product(product, qty)
            pickings |= picking
            operations.setdefault(picking, []).append((product, qty))

        location_stock = self.env.ref('stock.stock_location_stock')
        location_customer = self.env.ref('stock.stock_location_customers')

        for picking in pickings:
            transfer_model = self.env['stock.transfer_details'].with_context(
                active_model='stock.picking',
                active_id=picking.id,
                active_ids=picking.ids
            )
            items = []
            for product_qtys in operations[picking]:
                items.append((0, 0, {
                    'quantity': qty,
                    'product_id': product.id,
                    'product_uom_id': product.uom_id.id,
                    'sourceloc_id': location_stock.id,
                    'destinationloc_id': location_customer.id,
                }))
            transfer = transfer_model.create({
                'picking_id': picking.id,
                'item_ids': items
            })
            transfer.with_context(do_only_split=True).do_detailed_transfer()

    def cancel_move(self, product, qty):
        move = self.purchase.mapped('picking_ids.move_lines').filtered(
            lambda m: (m.product_id == product and
                       m.product_qty == qty and
                       m.state in ('confirmed', 'assigned'))
        )
        move.action_cancel()

    def amend(self):
        return self.amendment_model.with_context(
            active_model='purchase.order',
            active_id=self.purchase.id,
            active_ids=self.purchase.ids,
        ).create({'purchase_id': self.purchase.id})

    def amend_product(self, amendment, product, qty):
        item = amendment.item_ids.filtered(
            lambda m: m.purchase_line_id.product_id == product
        )
        item.amend_qty = qty

    def assert_amendment_quantities(self, amendment, product,
                                    ordered_qty=0, shipped_qty=0,
                                    canceled_qty=0, amend_qty=0):
        item = amendment.item_ids.filtered(
            lambda i: i.purchase_line_id.product_id == product
        )
        self.assertEqual(len(item), 1)
        self.assertEqual(
            [item.ordered_qty, item.shipped_qty,
             item.canceled_qty, item.amend_qty],
            [ordered_qty, shipped_qty,
             canceled_qty, amend_qty],
            'The quantities do not match (ordered, shipped, canceled, amended)'
        )

    def assert_purchase_lines(self, expected_lines):
        lines = self.purchase.order_line
        not_found = []
        for product, qty, state in expected_lines:
            for line in lines:
                if ((line.product_id, line.product_qty, line.state) ==
                        (product, qty, state)):
                    lines -= line
                    break
            else:
                not_found.append((product, qty, state))
        message = ''
        for product, qty, state in not_found:
            message += ("- product: '%s', qty: '%s', state: '%s'\n" %
                        (product.display_name, qty, state))
        for line in lines:
            message += ("+ product: '%s', qty: '%s', state: '%s'\n" %
                        (line.product_id.display_name, line.product_qty,
                         line.state))
        if message:
            raise AssertionError('Purchase lines do not match:\n\n%s' %
                                 message)

    def assert_procurements(self, expected_procurements):
        procurements = self.purchase.mapped('order_line.procurement_ids')
        not_found = []
        for product, qty, state in expected_procurements:
            for proc in procurements:
                if ((proc.product_id, proc.product_qty, proc.state) ==
                        (product, qty, state)):
                    procurements -= proc
                    break
            else:
                not_found.append((product, qty, state))
        message = ''
        for product, qty, state in not_found:
            message += ("- product: '%s', qty: '%s', state: '%s'\n" %
                        (product.display_name, qty, state))
        for line in procurements:
            message += ("+ product: '%s', qty: '%s', state: '%s'\n" %
                        (line.product_id.display_name, line.product_qty,
                         line.state))
        if message:
            raise AssertionError('Procurements do not match:\n\n%s' % message)

    def assert_moves(self, expected_moves):
        moves = self.purchase.mapped('picking_ids.move_lines')
        not_found = []
        for product, qty, state in expected_moves:
            for move in moves:
                if ((move.product_id, move.product_qty, move.state) ==
                        (product, qty, state)):
                    moves -= move
                    break
            else:
                not_found.append((product, qty, state))
        message = ''
        for product, qty, state in not_found:
            message += ("- product: '%s', qty: '%s', state: '%s'\n" %
                        (product.display_name, qty, state))
        for line in moves:
            message += ("+ product: '%s', qty: '%s', state: '%s'\n" %
                        (line.product_id.display_name, line.product_qty,
                         line.state))
        if message:
            raise AssertionError('Moves do not match:\n\n%s' % message)

    def test_ship_and_cancel_part(self):
        # We have 1000 product1
        # Ship 200 products
        self.ship([(self.product1, 200),
                   (self.product2, 0),
                   (self.product3, 0),
                   ])
        # Split 500 and 300 products
        self.split([(self.product1, 300)])
        # Cancel the 300
        self.cancel_move(self.product1, 300)

        self.assert_moves([
            (self.product1, 200, 'done'),
            (self.product1, 500, 'assigned'),
            (self.product1, 300, 'cancel'),
            (self.product2, 500, 'assigned'),
            (self.product3, 800, 'assigned'),
        ])

        # Ship the rest
        self.ship()

        self.assertEqual(self.purchase.state, 'except_picking')

        # amend the purchase order
        amendment = self.amend()

        self.assert_amendment_quantities(amendment, self.product1,
                                         ordered_qty=1000,
                                         shipped_qty=700,
                                         canceled_qty=300)
        self.assert_amendment_quantities(amendment, self.product2,
                                         ordered_qty=500, shipped_qty=500)
        self.assert_amendment_quantities(amendment, self.product3,
                                         ordered_qty=800, shipped_qty=800)
        amendment.do_amendment()
        self.assert_purchase_lines([
            (self.product1, 700, 'confirmed'),
            (self.product1, 300, 'cancel'),
            (self.product2, 500, 'confirmed'),
            (self.product3, 800, 'confirmed'),
        ])
        # self.assert_procurements([
        #     (self.product1, 200, 'done'),
        #     (self.product1, 300, 'cancel'),
        #     (self.product1, 500, 'running'),
        #     (self.product2, 500, 'running'),
        #     (self.product3, 800, 'running'),
        # ])
        # self.assert_moves([
        #     (self.product1, 200, 'done'),
        #     (self.product1, 300, 'cancel'),
        #     (self.product1, 500, 'confirmed'),
        #     (self.product2, 500, 'confirmed'),
        #     (self.product3, 800, 'confirmed'),
        # ])

    def test_cancel_one_line(self):
        # We have 500 product2
        # Split product2 in another picking
        self.split([(self.product2, 500)])

        # Cancel the whole product2
        self.cancel_move(self.product2, 500)
        self.assert_moves([
            (self.product1, 1000, 'assigned'),
            (self.product2, 500, 'cancel'),
            (self.product3, 800, 'assigned'),
        ])

        # purchase is in shipping exception only if a part
        # is done and the other part is canceled
        self.ship()

        self.assertEqual(self.purchase.state, 'except_picking')

        # amend the purchase order
        amendment = self.amend()
        self.assert_amendment_quantities(amendment, self.product1,
                                         ordered_qty=1000,
                                         shipped_qty=1000,
                                         amend_qty=0)
        self.assert_amendment_quantities(amendment, self.product2,
                                         ordered_qty=500,
                                         shipped_qty=0,
                                         canceled_qty=500)
        self.assert_amendment_quantities(amendment, self.product3,
                                         ordered_qty=800,
                                         shipped_qty=800)
        amendment.do_amendment()
        # TODO
        # self.assert_purchase_lines([
        #     (self.product1, 1000, 'confirmed'),
        #     (self.product2, 500, 'cancel'),
        #     (self.product3, 800, 'confirmed'),
        # ])
        # TODO
        # self.assert_procurements([
        #     (self.product1, 1000, 'running'),
        #     (self.product2, 500, 'cancel'),
        #     (self.product3, 800, 'running'),
        # ])
        # self.assert_moves([
        #     (self.product1, 1000, 'assigned'),
        #     (self.product2, 500, 'cancel'),
        #     (self.product3, 800, 'assigned'),
        # ])

    def test_amend_ship_half(self):
        # Ship 200 product1
        self.ship([(self.product1, 200),
                   (self.product2, 0),
                   (self.product3, 0),
                   ])
        # Split 100 of product1 in another picking
        self.split([(self.product1, 100)])

        # Cancel the 100 product1
        self.cancel_move(self.product1, 100)
        self.assert_moves([
            (self.product1, 200, 'done'),
            (self.product1, 700, 'assigned'),
            (self.product1, 100, 'cancel'),
            (self.product2, 500, 'assigned'),
            (self.product3, 800, 'assigned'),
        ])

        # purchase is in shipping exception only if a part
        # is done and the other part is canceled
        self.ship()

        self.assertEqual(self.purchase.state, 'except_picking')

        # amend the purchase order
        amendment = self.amend()
        # revert the canceled product1 by half, put 750
        self.amend_product(amendment, self.product1, 50)

        self.assert_amendment_quantities(amendment, self.product1,
                                         ordered_qty=1000,
                                         shipped_qty=900,
                                         canceled_qty=100,
                                         amend_qty=50)
        self.assert_amendment_quantities(amendment, self.product2,
                                         ordered_qty=500, shipped_qty=500)
        self.assert_amendment_quantities(amendment, self.product3,
                                         ordered_qty=800, shipped_qty=800)
        amendment.do_amendment()
        self.assert_purchase_lines([
            (self.product1, 900, 'confirmed'),
            (self.product1, 50, 'cancel'),
            (self.product1, 50, 'confirmed'),
            (self.product2, 500, 'confirmed'),
            (self.product3, 800, 'confirmed'),
        ])
        # self.assert_procurements([
        #     (self.product1, 200, 'done'),
        #     (self.product1, 100, 'cancel'),
        #     (self.product1, 750, 'running'),
        #     (self.product2, 500, 'running'),
        #     (self.product3, 800, 'running'),
        # ])
        # self.assert_moves([
        #     (self.product1, 200, 'done'),
        #     (self.product1, 100, 'cancel'),
        #     (self.product1, 700, 'cancel'),
        #     (self.product1, 750, 'confirmed'),
        #     (self.product2, 500, 'confirmed'),
        #     (self.product3, 800, 'confirmed'),
        # ])

    def test_amend_revert_cancel(self):
        # Split 100 of product1 in another picking
        self.split([(self.product1, 100)])

        # Cancel the 100 product1
        self.cancel_move(self.product1, 100)
        self.assert_moves([
            (self.product1, 900, 'assigned'),
            (self.product1, 100, 'cancel'),
            (self.product2, 500, 'assigned'),
            (self.product3, 800, 'assigned'),
        ])

        # purchase is in shipping exception only if a part
        # is done and the other part is canceled
        self.ship()

        self.assertEqual(self.purchase.state, 'except_picking')

        # amend the purchase order
        amendment = self.amend()
        # revert the canceled product1 by half, put 750
        self.amend_product(amendment, self.product1, 100)

        self.assert_amendment_quantities(amendment, self.product1,
                                         ordered_qty=1000,
                                         shipped_qty=900,
                                         canceled_qty=100,
                                         amend_qty=100)
        self.assert_amendment_quantities(amendment, self.product2,
                                         ordered_qty=500, shipped_qty=500)
        self.assert_amendment_quantities(amendment, self.product3,
                                         ordered_qty=800, shipped_qty=800)
        amendment.do_amendment()
        self.assert_purchase_lines([
            (self.product1, 1000, 'confirmed'),
            (self.product2, 500, 'confirmed'),
            (self.product3, 800, 'confirmed'),
        ])
        # self.assert_procurements([
        #     (self.product1, 900, 'running'),
        #     (self.product1, 100, 'running'),
        #     (self.product2, 500, 'running'),
        #     (self.product3, 800, 'running'),
        # ])
        # self.assert_moves([
        #     (self.product1, 100, 'confirmed'),
        #     (self.product1, 100, 'cancel'),
        #     (self.product1, 900, 'confirmed'),
        #     (self.product2, 500, 'confirmed'),
        #     (self.product3, 800, 'confirmed'),
        # ])

    def test_amend_quantity(self):
        # Ship 200 product1
        self.ship([(self.product1, 200),
                   (self.product2, 0),
                   (self.product3, 0),
                   ])
        # 800 products remain
        # Split 100 of product1 in another picking and cancel them
        self.split([(self.product1, 100)])
        self.cancel_move(self.product1, 100)

        # amend the purchase order
        amendment = self.amend()
        with self.assertRaises(exceptions.ValidationError):
            # below min quantity (700, because on the 1000 ordered, 200
            # have been shipped)
            self.amend_product(amendment, self.product1, 699)
        with self.assertRaises(exceptions.ValidationError):
            # above max quantity (800, because on the 1000 ordered, 200
            # have been shipped)
            self.amend_product(amendment, self.product1, 801)
        # between bounds
        self.amend_product(amendment, self.product1, 700)
        self.amend_product(amendment, self.product1, 800)