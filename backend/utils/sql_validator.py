"""
SQL Query Validator and Sanitizer for Mali Daftari
Ensures safe database queries with business_id filtering
"""

import re
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def validate_and_secure_sql(sql: str, business_id: str) -> Optional[str]:
<<<<<<< HEAD
    """Validate and secure SQL query"""
    # Normalize whitespace
    sql = ' '.join(sql.split())
=======
    """
    Validate and secure SQL query
    
    Args:
        sql: Raw SQL query from LLM
        business_id: Business identifier to filter by
        
    Returns:
        Secured SQL query or None if invalid
    """
    
    sql = sql.strip()
    
    # Remove markdown code blocks if present
    sql = sql.replace('```sql', '').replace('```', '').strip()
    
>>>>>>> c3b5854c64677957061d72491917de8be00c8e53
    sql_upper = sql.upper()
    
    # Must be SELECT only
    if not sql_upper.startswith('SELECT'):
        logger.warning(f"Rejected non-SELECT query: {sql[:50]}...")
        return None
    
    # Block dangerous keywords
    dangerous = [
        'DROP', 'DELETE', 'UPDATE', 'INSERT', 'ALTER', 
<<<<<<< HEAD
        'CREATE', 'TRUNCATE', 'EXEC', 'EXECUTE',
        'PRAGMA', 'GRANT', 'REVOKE', ';--'
=======
        'CREATE', 'TRUNCATE', 'EXEC', 'EXECUTE', '--', ';--',
        'PRAGMA', 'GRANT', 'REVOKE', 'INTO', 'INFORMATION_SCHEMA',
        'PG_', 'COPY', 'VACUUM'
>>>>>>> c3b5854c64677957061d72491917de8be00c8e53
    ]
    
    for keyword in dangerous:
        if keyword in sql_upper:
            logger.warning(f"Rejected query with dangerous keyword '{keyword}': {sql[:50]}...")
            return None
    
    # Check for multiple statements (basic check)
    if sql.count(';') > 1 or ';' in sql[:-1]:
        logger.warning(f"Rejected query with multiple statements: {sql[:50]}...")
        return None
    
    # Add business_id filter (critical security measure)
    sql = add_business_filter(sql, business_id)
    
    # Verify business_id was actually added
    if f"business_id = '{business_id}'" not in sql:
        logger.error(f"Failed to add business_id filter to query: {sql[:50]}...")
        return None
    
    # Add LIMIT if not present (prevent huge result sets)
    if 'LIMIT' not in sql_upper:
        sql = sql.rstrip(';') + ' LIMIT 1000'
    
    logger.debug(f"Validated query: {sql}")
    
    return sql


def add_business_filter(sql: str, business_id: str) -> str:
<<<<<<< HEAD
    """Add business_id filter using simple string replacement"""
=======
    """
    Add business_id filter to SQL query
    Critical security function - ensures data isolation
    
    Args:
        sql: Original SQL query
        business_id: Business identifier
        
    Returns:
        SQL with business_id filter injected
    """
>>>>>>> c3b5854c64677957061d72491917de8be00c8e53
    
    safe_business_id = business_id.replace("'", "''")
    sql_upper = sql.upper()
    
<<<<<<< HEAD
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
=======
    # Escape single quotes in business_id (prevent SQL injection)
    safe_business_id = business_id.replace("'", "''")
    
    business_filter = f"business_id = '{safe_business_id}'"
    
    # Strategy: Find the best place to inject the WHERE clause
    
    # Case 1: Query already has WHERE clause
    if ' WHERE ' in sql_upper:
        where_idx = sql_upper.find(' WHERE ') + 7
        return (
            sql[:where_idx] + 
            f"{business_filter} AND " + 
            sql[where_idx:]
        )
    
    # Case 2: Query has GROUP BY (add WHERE before it)
    elif ' GROUP BY ' in sql_upper:
        group_idx = sql_upper.find(' GROUP BY ')
        return (
            sql[:group_idx] + 
            f" WHERE {business_filter} " + 
            sql[group_idx:]
        )
    
    # Case 3: Query has HAVING (add WHERE before GROUP BY/HAVING)
    elif ' HAVING ' in sql_upper:
        having_idx = sql_upper.find(' HAVING ')
        return (
            sql[:having_idx] + 
            f" WHERE {business_filter} " + 
            sql[having_idx:]
        )
    
    # Case 4: Query has ORDER BY
    elif ' ORDER BY ' in sql_upper:
        order_idx = sql_upper.find(' ORDER BY ')
        return (
            sql[:order_idx] + 
            f" WHERE {business_filter} " + 
            sql[order_idx:]
        )
    
    # Case 5: Query has LIMIT
    elif ' LIMIT ' in sql_upper:
        limit_idx = sql_upper.find(' LIMIT ')
        return (
            sql[:limit_idx] + 
            f" WHERE {business_filter} " + 
            sql[limit_idx:]
        )
    
    # Case 6: Simple query - append WHERE clause
    else:
        return sql.rstrip(';') + f" WHERE {business_filter}"


def extract_table_names(sql: str) -> list[str]:
    """
    Extract table names from SQL query (for logging/debugging)
    
    Args:
        sql: SQL query
        
    Returns:
        List of table names found in query
    """
    sql_upper = sql.upper()
    tables = []
    
    # Extract from FROM clause
    from_match = re.search(r'FROM\s+(\w+)', sql_upper)
    if from_match:
        tables.append(from_match.group(1).lower())
    
    # Extract from JOINs
    join_matches = re.finditer(r'JOIN\s+(\w+)', sql_upper)
    for match in join_matches:
        tables.append(match.group(1).lower())
    
    return tables


def validate_allowed_tables(sql: str, allowed_tables: list[str]) -> bool:
    """
    Verify query only accesses allowed tables
    
    Args:
        sql: SQL query
        allowed_tables: List of allowed table names
        
    Returns:
        True if all tables are allowed, False otherwise
    """
    query_tables = extract_table_names(sql)
    
    for table in query_tables:
        if table not in allowed_tables:
            logger.warning(f"Query attempts to access unauthorized table: {table}")
            return False
    
    return True


# Allowed tables for Mali Daftari
ALLOWED_TABLES = [
    'inventories',
    'products',
    'sales',
    'expenses',
    'businesses'  # Read-only for business info
]


def validate_query_complete(sql: str, business_id: str) -> Optional[str]:
    """
    Complete validation pipeline
    
    Args:
        sql: Raw SQL query
        business_id: Business identifier
        
    Returns:
        Secured SQL or None if invalid
    """
    
    # Step 1: Basic validation and securing
    secured_sql = validate_and_secure_sql(sql, business_id)
    
    if not secured_sql:
        return None
    
    # Step 2: Validate table access
    if not validate_allowed_tables(secured_sql, ALLOWED_TABLES):
        logger.error(f"Query accesses unauthorized tables: {sql[:50]}...")
        return None
    
    logger.info(f"✅ Query validated successfully")
    
    return secured_sql
>>>>>>> c3b5854c64677957061d72491917de8be00c8e53
