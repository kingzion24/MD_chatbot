# backend/utils/sql_validator.py
import re
from typing import Optional

def validate_and_secure_sql(sql: str, business_id: str) -> Optional[str]:
    """Validate and secure SQL query"""
    
    sql = sql.strip()
    sql_upper = sql.upper()
    
    # Must be SELECT only
    if not sql_upper.startswith('SELECT'):
        return None
    
    # Block dangerous keywords
    dangerous = [
        'DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 
        'CREATE', 'TRUNCATE', 'EXEC', 'EXECUTE', '--', ';--',
        'PRAGMA', 'GRANT', 'REVOKE'
    ]
    
    for keyword in dangerous:
        if keyword in sql_upper:
            return None
    
    # Add business_id filter
    sql = add_business_filter(sql, business_id)
    
    # Add LIMIT if not present
    if 'LIMIT' not in sql_upper:
        sql = sql.rstrip(';') + ' LIMIT 100'
    
    return sql

def add_business_filter(sql: str, business_id: str) -> str:
    """Add business_id filter to SQL query"""
    
    sql_upper = sql.upper()
    
    # Escape single quotes in business_id
    safe_business_id = business_id.replace("'", "''")
    
    # Different patterns for WHERE clause injection
    if ' WHERE ' in sql_upper:
        # Find WHERE and insert after it
        where_idx = sql_upper.find(' WHERE ') + 7
        return (
            sql[:where_idx] + 
            f"business_id = '{safe_business_id}' AND " + 
            sql[where_idx:]
        )
    elif ' GROUP BY ' in sql_upper:
        group_idx = sql_upper.find(' GROUP BY ')
        return (
            sql[:group_idx] + 
            f" WHERE business_id = '{safe_business_id}' " + 
            sql[group_idx:]
        )
    elif ' ORDER BY ' in sql_upper:
        order_idx = sql_upper.find(' ORDER BY ')
        return (
            sql[:order_idx] + 
            f" WHERE business_id = '{safe_business_id}' " + 
            sql[order_idx:]
        )
    elif ' LIMIT ' in sql_upper:
        limit_idx = sql_upper.find(' LIMIT ')
        return (
            sql[:limit_idx] + 
            f" WHERE business_id = '{safe_business_id}' " + 
            sql[limit_idx:]
        )
    else:
        # Simple append
        return sql.rstrip(';') + f" WHERE business_id = '{safe_business_id}'"