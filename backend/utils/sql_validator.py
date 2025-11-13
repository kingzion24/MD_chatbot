# backend/utils/sql_validator.py
import re
from typing import Optional

def validate_and_secure_sql(sql: str, business_id: str) -> Optional[str]:
    """Validate and secure SQL query"""
    # Normalize whitespace
    sql = ' '.join(sql.split())
    sql_upper = sql.upper()
    
    # Must be SELECT only
    if not sql_upper.startswith('SELECT'):
        return None
    
    # Block dangerous keywords
    dangerous = [
        'DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 
        'CREATE', 'TRUNCATE', 'EXEC', 'EXECUTE',
        'PRAGMA', 'GRANT', 'REVOKE', ';--'
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
    """Add business_id filter using simple string replacement"""
    
    safe_business_id = business_id.replace("'", "''")
    sql_upper = sql.upper()
    
    # Already has business_id filter
    if 'BUSINESS_ID' in sql_upper:
        return sql
    
    # Get table info
    from_match = re.search(r'FROM\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?', sql, re.IGNORECASE)
    if not from_match:
        return sql
    
    # Use alias if present, otherwise use table name
    table_alias = from_match.group(2) if from_match.group(2) else from_match.group(1)
    business_filter = f"{table_alias}.business_id = '{safe_business_id}'"
    
    # If query has WHERE, add to it
    if ' WHERE ' in sql_upper:
        return re.sub(
            r'\bWHERE\b',
            f'WHERE {business_filter} AND',
            sql,
            count=1,
            flags=re.IGNORECASE
        )
    
    # No WHERE - need to insert it before GROUP/ORDER/LIMIT/HAVING
    # Find the first occurrence of these keywords
    insertion_point = None
    for clause in ['GROUP BY', 'HAVING', 'ORDER BY', 'LIMIT', 'OFFSET']:
        match = re.search(rf'\b{clause}\b', sql, re.IGNORECASE)
        if match:
            if insertion_point is None or match.start() < insertion_point:
                insertion_point = match.start()
    
    if insertion_point is not None:
        # Insert WHERE before the found clause
        return sql[:insertion_point] + f'WHERE {business_filter} ' + sql[insertion_point:]
    
    # No clauses found - append at end
    return sql.rstrip(';') + f" WHERE {business_filter}"