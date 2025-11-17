"""
Database Schema Structure for Mali Daftari
Provides structured schema information to LLM for better SQL generation
"""

import json

# Complete database schema as structured JSON
DATABASE_SCHEMA = {
    "database": "mali_daftari",
    "description": "Multi-tenant business management system for MSMEs in Tanzania",
    
    "tables": {
        "inventories": {
            "description": "Stock/inventory batches - groups of products purchased together",
            "primary_key": "id",
            "columns": {
                "id": {"type": "UUID", "nullable": False},
                "business_id": {"type": "UUID", "nullable": False, "indexed": True, 
                               "note": "CRITICAL: ALWAYS filter by this"},
                "name": {"type": "VARCHAR(100)", "nullable": False,
                        "example": "January Stock, Supplier ABC Delivery"},
                "rough_cost": {"type": "DECIMAL(12,2)", "nullable": False,
                              "description": "Estimated total cost of inventory batch"},
                "status": {"type": "ENUM", "values": ["new", "in_progress", "completed"],
                          "default": "new"},
                "created_by": {"type": "UUID", "nullable": False},
                "created_at": {"type": "TIMESTAMP WITH TIME ZONE"},
                "updated_at": {"type": "TIMESTAMP WITH TIME ZONE"}
            },
            "relationships": {
                "has_many": ["products"],
                "join_example": "JOIN products p ON p.inventory_id = inventories.id"
            },
            "common_queries": [
                "List all inventories",
                "Show active inventories (status = 'in_progress')",
                "Calculate total inventory cost: SUM(rough_cost)"
            ]
        },
        
        "products": {
            "description": "Individual products within inventory batches",
            "primary_key": "id",
            "columns": {
                "id": {"type": "UUID"},
                "business_id": {"type": "UUID", "indexed": True,
                               "note": "CRITICAL: ALWAYS filter by this"},
                "inventory_id": {"type": "UUID", "description": "Parent inventory batch"},
                "name": {"type": "VARCHAR(200)", "example": "Nike Shoes Size 42"},
                "quantity": {"type": "INTEGER", "default": 0,
                            "description": "CURRENT stock (auto-updated by system when sales happen)",
                            "important": "This decreases when products are sold"},
                "initial_quantity": {"type": "INTEGER", "default": 0,
                                   "description": "STARTING stock (user sets, NEVER changes)",
                                   "important": "Use this to calculate sold: initial_quantity - quantity"},
                "created_at": {"type": "TIMESTAMP"},
                "updated_at": {"type": "TIMESTAMP"}
            },
            "calculated_fields": {
                "sold_quantity": {
                    "formula": "initial_quantity - quantity",
                    "description": "How many units have been sold",
                    "sql": "(initial_quantity - quantity) as sold_quantity"
                },
                "stock_percentage": {
                    "formula": "(quantity / initial_quantity) * 100",
                    "description": "Percentage of stock remaining",
                    "sql": "ROUND((quantity::DECIMAL / initial_quantity) * 100, 2) as stock_percent"
                }
            },
            "relationships": {
                "belongs_to": ["inventories"],
                "has_many": ["sales"]
            },
            "common_queries": [
                "Low stock: WHERE quantity < 10 AND quantity > 0",
                "Out of stock: WHERE quantity = 0",
                "Total sold: SUM(initial_quantity - quantity)",
                "Products by inventory: JOIN inventories..."
            ]
        },
        
        "sales": {
            "description": "Individual sales transactions",
            "primary_key": "id",
            "columns": {
                "id": {"type": "UUID"},
                "business_id": {"type": "UUID", "indexed": True,
                               "note": "CRITICAL: ALWAYS filter by this"},
                "product_id": {"type": "UUID", "indexed": True},
                "quantity": {"type": "INTEGER", "description": "Units sold in this transaction"},
                "price": {"type": "DECIMAL(12,2)", "description": "Price PER UNIT (not total)"},
                "total_amount": {"type": "DECIMAL(12,2)", "computed": True,
                                "formula": "quantity * price",
                                "description": "Auto-calculated total"},
                "created_by": {"type": "UUID"},
                "created_at": {"type": "TIMESTAMP", "description": "System timestamp"},
                "sale_date": {"type": "DATE", "indexed": True,
                             "description": "Actual sale date - USE THIS for date filtering!"}
            },
            "aggregations": {
                "total_revenue": "SUM(total_amount)",
                "total_units": "SUM(quantity)",
                "average_sale": "AVG(total_amount)",
                "transaction_count": "COUNT(*)",
                "best_selling": "GROUP BY product_id, ORDER BY SUM(quantity) DESC"
            },
            "relationships": {
                "belongs_to": ["products"]
            },
            "date_filtering": {
                "today": "WHERE sale_date = CURRENT_DATE",
                "this_week": "WHERE sale_date >= DATE_TRUNC('week', CURRENT_DATE)",
                "this_month": "WHERE sale_date >= DATE_TRUNC('month', CURRENT_DATE)",
                "last_7_days": "WHERE sale_date >= CURRENT_DATE - INTERVAL '7 days'",
                "last_30_days": "WHERE sale_date >= CURRENT_DATE - INTERVAL '30 days'"
            }
        },
        
        "expenses": {
            "description": "Business expenses and costs",
            "primary_key": "id",
            "columns": {
                "id": {"type": "UUID"},
                "business_id": {"type": "UUID", "indexed": True,
                               "note": "CRITICAL: ALWAYS filter by this"},
                "name": {"type": "VARCHAR(200)", "example": "Rent, Electricity, Transport"},
                "amount": {"type": "DECIMAL(12,2)"},
                "receipt_url": {"type": "TEXT", "nullable": True},
                "created_by": {"type": "UUID"},
                "created_at": {"type": "TIMESTAMP"},
                "expense_date": {"type": "DATE", "indexed": True,
                                "description": "Actual expense date - USE THIS for filtering!"}
            },
            "aggregations": {
                "total_expenses": "SUM(amount)",
                "average_expense": "AVG(amount)",
                "expense_count": "COUNT(*)",
                "by_category": "GROUP BY name"
            },
            "common_queries": [
                "Total expenses today/month",
                "Largest expenses: ORDER BY amount DESC",
                "Expenses by category: GROUP BY name"
            ]
        }
    },
    
    "business_calculations": {
        "profit": {
            "description": "Total revenue minus total expenses",
            "formula": "SUM(sales.total_amount) - SUM(expenses.amount)",
            "sql_template": """
                SELECT 
                    (SELECT COALESCE(SUM(total_amount), 0) FROM sales 
                     WHERE business_id = '{business_id}' {date_filter}) -
                    (SELECT COALESCE(SUM(amount), 0) FROM expenses 
                     WHERE business_id = '{business_id}' {date_filter}) as profit
            """
        },
        "revenue": {
            "description": "Total sales income",
            "formula": "SUM(sales.total_amount)",
            "sql_template": "SELECT SUM(total_amount) as revenue FROM sales WHERE business_id = '{business_id}' {date_filter}"
        }
    },
    
    "query_examples": [
        {
            "natural_language": "Show me sales from today",
            "swahili": "Nionyeshe mauzo ya leo",
            "sql": "SELECT * FROM sales WHERE business_id = '{business_id}' AND sale_date = CURRENT_DATE ORDER BY created_at DESC"
        },
        {
            "natural_language": "What is my total revenue this month?",
            "swahili": "Mapato yangu jumla mwezi huu ni kiasi gani?",
            "sql": "SELECT COALESCE(SUM(total_amount), 0) as revenue FROM sales WHERE business_id = '{business_id}' AND sale_date >= DATE_TRUNC('month', CURRENT_DATE)"
        },
        {
            "natural_language": "Show me products with low stock",
            "swahili": "Nionyeshe bidhaa ambazo hifadhi ni kidogo",
            "sql": "SELECT * FROM products WHERE business_id = '{business_id}' AND quantity < 10 AND quantity > 0 ORDER BY quantity ASC"
        },
        {
            "natural_language": "What are my best selling products?",
            "swahili": "Bidhaa zangu zinazouzwa zaidi ni zipi?",
            "sql": """SELECT p.name, SUM(s.quantity) as total_sold, SUM(s.total_amount) as revenue
                      FROM products p
                      JOIN sales s ON s.product_id = p.id
                      WHERE p.business_id = '{business_id}'
                      GROUP BY p.id, p.name
                      ORDER BY total_sold DESC
                      LIMIT 10"""
        }
    ],
    
    "sql_rules": {
        "MANDATORY": [
            "ALWAYS include: WHERE business_id = '{business_id}'",
            "ONLY use SELECT statements (no INSERT/UPDATE/DELETE/DROP)",
            "Use proper JOINs when accessing related tables",
            "Add LIMIT 1000 if no LIMIT specified"
        ],
        "DATE_FILTERING": [
            "Use sale_date (NOT created_at) for sales dates",
            "Use expense_date (NOT created_at) for expense dates",
            "Today: WHERE date_column = CURRENT_DATE",
            "This month: WHERE date_column >= DATE_TRUNC('month', CURRENT_DATE)"
        ],
        "AVOID": [
            "Don't use created_at for business date filtering",
            "Don't forget business_id filter",
            "Don't use quantity as 'sold' (use initial_quantity - quantity)",
            "Don't forget COALESCE for aggregates that might be NULL"
        ]
    },
    
    "swahili_to_english_terms": {
        "mauzo": "sales",
        "bidhaa": "products",
        "hifadhi": "inventory/stock",
        "gharama": "expenses",
        "faida": "profit",
        "mapato": "revenue",
        "leo": "today",
        "jana": "yesterday",
        "wiki hii": "this week",
        "mwezi huu": "this month",
        "jumla": "total",
        "kiasi": "amount"
    }
}


def get_schema_json():
    """Return schema as formatted JSON string"""
    return json.dumps(DATABASE_SCHEMA, indent=2)


def get_schema_for_prompt():
    """Return schema formatted for system prompt"""
    return f"""
DATABASE SCHEMA (JSON FORMAT):
{json.dumps(DATABASE_SCHEMA, indent=2)}

KEY POINTS:
1. ALWAYS filter by business_id = '{{business_id}}'
2. Use sale_date/expense_date for date filtering (NOT created_at)
3. Products: quantity = current stock, initial_quantity = starting stock
4. Sold quantity = initial_quantity - quantity
5. Use COALESCE for aggregates to handle NULL
"""


# Example usage
if __name__ == "__main__":
    print(get_schema_for_prompt())