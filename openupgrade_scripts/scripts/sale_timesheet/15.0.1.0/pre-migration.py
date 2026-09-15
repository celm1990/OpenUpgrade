from openupgradelib import openupgrade


def _fast_fill_project_sale_line_employee_map_cost(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE project_sale_line_employee_map emp_map
        SET cost = emp.timesheet_cost
        FROM hr_employee emp
        WHERE emp_map.employee_id = emp.id
        """,
    )


def _re_fill_account_analytic_line_timesheet_invoice_type(env):
    openupgrade.logged_query(
        env.cr,
        """
        WITH aal_tmp AS (
            SELECT aal.id AS aal_id,
                CASE
                    WHEN product IS NOT NULL
                        AND tmpl.type = 'service' THEN 'service_revenues'
                    WHEN aal.amount >=0 THEN 'other_revenues' ELSE 'other_costs' END
                AS timesheet_invoice_type
            FROM account_analytic_line aal
            LEFT JOIN sale_order_line so_line ON aal.so_line = so_line.id
            LEFT JOIN product_product product ON so_line.product_id = product.id
            LEFT JOIN product_template tmpl ON tmpl.id = product.product_tmpl_id
            WHERE aal.project_id IS NULL
        )
        UPDATE account_analytic_line aal
        SET timesheet_invoice_type = aal_tmp.timesheet_invoice_type
        FROM aal_tmp WHERE aal_tmp.aal_id = aal.id
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        WITH aal_tmp AS (
            SELECT aal.id AS aal_id,
            CASE
            WHEN so_line IS NOT NULL AND product IS NOT NULL
                AND tmpl.type = 'service' AND tmpl.invoice_policy = 'order'
                THEN 'billable_fixed'
            WHEN so_line IS NOT NULL AND product IS NOT NULL
                AND tmpl.type = 'service' AND tmpl.invoice_policy = 'delivery'
                AND tmpl.service_type = 'timesheet' AND aal.amount > 0
                THEN 'timesheet_revenues'
            WHEN so_line IS NOT NULL AND product IS NOT NULL
                AND tmpl.type = 'service' AND tmpl.invoice_policy = 'delivery'
                AND tmpl.service_type = 'timesheet' AND aal.amount <= 0
                THEN 'billable_time'
            WHEN so_line IS NOT NULL AND product IS NOT NULL
                AND tmpl.type = 'service' AND tmpl.invoice_policy = 'delivery'
                AND tmpl.service_type != 'timesheet'
                THEN 'billable_fixed'
            WHEN so_line IS NOT NULL AND product IS NOT NULL
                AND tmpl.type = 'service' AND tmpl.invoice_policy = 'order'
                THEN 'billable_fixed'
            WHEN so_line IS NULL OR (product IS NOT NULL AND tmpl.type != 'service')
                THEN 'non_billable'
            END
            AS timesheet_invoice_type
        FROM account_analytic_line aal
        LEFT JOIN sale_order_line so_line ON aal.so_line = so_line.id
        LEFT JOIN product_product product ON so_line.product_id = product.id
        LEFT JOIN product_template tmpl ON tmpl.id = product.product_tmpl_id
        WHERE aal.project_id IS NOT NULL AND aal.timesheet_invoice_type IS NULL
        )
        UPDATE account_analytic_line aal
        SET timesheet_invoice_type = aal_tmp.timesheet_invoice_type
        FROM aal_tmp WHERE aal_tmp.aal_id = aal.id
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_analytic_line
        SET timesheet_invoice_type = 'non_billable'
        WHERE timesheet_invoice_type IN ('non_billable_timesheet', 'non_billable_project')
        """,
    )


def _fill_sale_order_line_remaining_hours(env):
    openupgrade.logged_query(
        env.cr,
        """
        WITH hour_uom AS (
            SELECT uom.id, uom.factor, uom.category_id
            FROM uom_uom uom
            JOIN ir_model_data imd ON imd.res_id = uom.id
            WHERE imd.module = 'uom' AND imd.name = 'product_uom_hour'
        )
        UPDATE sale_order_line sol
            SET remaining_hours = CASE
                WHEN tmpl.invoice_policy = 'order' AND tmpl.service_type = 'timesheet'
                    AND sol_uom.category_id = hour_uom.category_id
                THEN (sol.product_uom_qty - sol.qty_delivered)
                    / sol_uom.factor * hour_uom.factor
                ELSE 0
            END
        FROM product_product pp
        JOIN product_template tmpl ON tmpl.id = pp.product_tmpl_id
        CROSS JOIN uom_uom sol_uom
        CROSS JOIN hour_uom
        WHERE sol.product_id = pp.id
            AND sol_uom.id = sol.product_uom
        """,
    )


@openupgrade.migrate()
def migrate(env, version):
    openupgrade.add_fields(
        env,
        [
            (
                "is_cost_changed",
                "project.sale.line.employee.map",
                "project_sale_line_employee_map",
                "boolean",
                False,
                "sale_timesheet",
                False,
            ),
            (
                "cost",
                "project.sale.line.employee.map",
                "project_sale_line_employee_map",
                "float",
                False,
                "sale_timesheet",
                0.0,
            ),
            (
                "remaining_hours",
                "sale.order.line",
                "sale_order_line",
                "float",
                False,
                "sale_timesheet",
                0.0,
            ),
        ],
    )
    _fast_fill_project_sale_line_employee_map_cost(env)
    _fill_sale_order_line_remaining_hours(env)
    _re_fill_account_analytic_line_timesheet_invoice_type(env)
    # Disappeared constraint
    openupgrade.delete_sql_constraint_safely(
        env,
        "sale_timesheet",
        "project_project",
        "timesheet_product_required_if_billable_and_time",
    )
    # old name in case you have old constrain before renamed by odoo:
    openupgrade.delete_sql_constraint_safely(
        env,
        "sale_timesheet",
        "project_project",
        "timesheet_product_required_if_billable_and_timesheets",
    )
