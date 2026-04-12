"""
SQL Query Validator for Mali Daftari
AST-based validation using sqlglot — eliminates regex fragility and correctly
qualifies the tenant filter with the primary table alias, fixing the
"ambiguous column reference" error that arises on JOIN queries.
"""

import logging
import sqlglot
import sqlglot.expressions as exp

logger = logging.getLogger(__name__)

ALLOWED_TABLES: frozenset[str] = frozenset({
    "sales",
    "products",
    "inventories",
    "expenses",
    "agent_interactions",
})


def validate_query_complete(sql: str) -> str:
    """
    Parse, validate, and secure a SQL query using AST analysis.

    The function applies five sequential checks before returning the
    secured query string:

      1. Parse — reject anything sqlglot cannot parse as valid Postgres SQL.
      2. SELECT-only — reject DDL, DML, and multi-statement inputs.
      3. No set operations — reject UNION / INTERSECT / EXCEPT at any depth.
      4. Table whitelist — reject references to tables outside ALLOWED_TABLES.
      5. Tenant injection — prepend  <alias>.business_id = $1  to WHERE,
         using the primary table's alias so JOINed queries are unambiguous.

    Raises:
        ValueError: For any query that fails a security or structural check.
            The message describes which check failed and why.

    Returns:
        Secured SQL string in Postgres dialect.  The caller must bind the
        actual business_id value as the first positional parameter ($1) when
        executing via asyncpg.
    """
    # Strip markdown fences that the LLM sometimes wraps the SQL in.
    sql = sql.replace("```sql", "").replace("```", "").strip()

    # ── 1. Parse ─────────────────────────────────────────────────────────────
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"SQL parse error: {exc}") from exc

    if len(statements) != 1:
        raise ValueError(
            f"Exactly one SQL statement is required, got {len(statements)}"
        )

    tree = statements[0]

    # ── 2. SELECT only ────────────────────────────────────────────────────────
    # parse() returns the root node of the expression tree.  A top-level UNION
    # parses to exp.Union (not exp.Select), so this check catches that case
    # automatically in addition to DDL/DML.
    if not isinstance(tree, exp.Select):
        raise ValueError(
            f"Only SELECT statements are allowed, got: {type(tree).__name__}"
        )

    # ── 3. Block set operations ───────────────────────────────────────────────
    # A top-level UNION was already rejected above.  This walk catches set ops
    # nested inside subqueries (e.g. SELECT … FROM (SELECT … UNION …) sub).
    for set_op_type in (exp.Union, exp.Intersect, exp.Except):
        if tree.find(set_op_type) is not None:
            raise ValueError(
                f"Set operations ({set_op_type.__name__}) are not permitted"
            )

    # ── 4. Table whitelist ────────────────────────────────────────────────────
    # find_all(exp.Table) walks the entire tree, so it catches tables in
    # subqueries and JOINs, not just the primary FROM clause.
    for table_node in tree.find_all(exp.Table):
        name = table_node.name.lower()
        if name not in ALLOWED_TABLES:
            raise ValueError(f"Table '{name}' is not in the allowed list")

    # ── 5. Inject tenant filter (alias-qualified) ─────────────────────────────
    from_clause = tree.args.get("from")
    if from_clause is None:
        raise ValueError("Query has no FROM clause")

    primary_table = from_clause.find(exp.Table)
    if primary_table is None:
        raise ValueError("Could not identify primary table in the FROM clause")

    # alias_or_name returns the alias when one was set (e.g. "s" for "sales s")
    # and falls back to the bare table name when no alias exists (e.g. "sales").
    # Qualifying the column with this value makes the filter unambiguous even
    # when the query JOINs multiple tables that all have a business_id column.
    qualifier = primary_table.alias_or_name

    tree = tree.where(
        f"{qualifier}.business_id = $1",
        dialect="postgres",
    )

    # ── 6. Return secured SQL ─────────────────────────────────────────────────
    return tree.sql(dialect="postgres")
