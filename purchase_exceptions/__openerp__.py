# -*- coding: utf-8 -*-
#    Authors: Raphaël Valyi, Renato Lima, Leonardo Pistone
#    Copyright (C) 2011 Akretion LTDA.
#    Copyright (C) 2015 Camptocamp SA
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
{'name': 'Purchase Exceptions',
 'summary': 'Custom exceptions on purchase order',
 'version': '1.0',
 'category': 'Purchases',
 'author': "Akretion,Camptocamp,Odoo Community Association (OCA)",
 'website': 'http://www.akretion.com',
 'depends': ['purchase'],
 'data': ['workflow/purchase.xml',
          'view/purchase.xml',
          # 'sale_exceptions_data.xml',  # XXX a cron here
          'wizard/purchase_exception_confirm_view.xml',
          'security/ir.model.access.csv',
          # 'settings/sale.exception.csv'
          ],
 'installable': True,
 }