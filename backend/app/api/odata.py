"""Denodo-style OData v4 feed service for Excel and Power BI data consumption."""

from __future__ import annotations

import re
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.api.query import federated_executor
from app.api.views import IDENTIFIER_REGEX, resolve_view_path
from app.auth import SecurityContext, get_security_context, require_roles
from app.catalog import catalog as default_catalog
from app.connectors.models import ColumnMetadata, DataType

router = APIRouter(
    dependencies=[
        Depends(require_roles("FinancialAnalyst", "DataEngineer", "Trader", "ComplianceAdmin"))
    ]
)

EDM_TYPE_MAP = {
    DataType.STRING: "Edm.String",
    DataType.INTEGER: "Edm.Int64",
    DataType.FLOAT: "Edm.Double",
    DataType.DECIMAL: "Edm.Decimal",
    DataType.BOOLEAN: "Edm.Boolean",
    DataType.TIMESTAMP: "Edm.DateTimeOffset",
    DataType.DATE: "Edm.Date",
    DataType.JSON: "Edm.String",
    DataType.BINARY: "Edm.Binary",
    DataType.UNKNOWN: "Edm.String",
}


class EntitySetSummary(BaseModel):
    """OData entity set reference."""

    name: str
    kind: str = "EntitySet"
    url: str


class ServiceDocumentResponse(BaseModel):
    """OData v4 root service document payload."""

    odata_context: str = Field(default="/api/v1/odata/$metadata", serialization_alias="@odata.context")
    value: list[EntitySetSummary]


def translate_odata_filter(filter_str: str) -> str:
    """Translate basic OData v4 $filter syntax to SQL WHERE expression."""
    expr = filter_str.strip()
    if not expr:
        return ""

    def replace_contains(m: re.Match) -> str:
        col = m.group(1)
        val = m.group(2).strip("'")
        if not IDENTIFIER_REGEX.match(col):
            raise ValueError(f"Invalid column name: '{col}'")
        escaped = val.replace("'", "''")
        return f"{col} LIKE '%{escaped}%'"

    def replace_startswith(m: re.Match) -> str:
        col = m.group(1)
        val = m.group(2).strip("'")
        if not IDENTIFIER_REGEX.match(col):
            raise ValueError(f"Invalid column name: '{col}'")
        escaped = val.replace("'", "''")
        return f"{col} LIKE '{escaped}%'"

    def replace_endswith(m: re.Match) -> str:
        col = m.group(1)
        val = m.group(2).strip("'")
        if not IDENTIFIER_REGEX.match(col):
            raise ValueError(f"Invalid column name: '{col}'")
        escaped = val.replace("'", "''")
        return f"{col} LIKE '%{escaped}'"

    expr = re.sub(
        r"contains\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*,\s*('[^']*')\s*\)",
        replace_contains,
        expr,
        flags=re.IGNORECASE,
    )
    expr = re.sub(
        r"startswith\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*,\s*('[^']*')\s*\)",
        replace_startswith,
        expr,
        flags=re.IGNORECASE,
    )
    expr = re.sub(
        r"endswith\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*,\s*('[^']*')\s*\)",
        replace_endswith,
        expr,
        flags=re.IGNORECASE,
    )

    op_map = {
        "eq": "=",
        "ne": "!=",
        "gt": ">",
        "ge": ">=",
        "lt": "<",
        "le": "<=",
        "and": "AND",
        "or": "OR",
        "not": "NOT",
    }

    tokens = re.findall(
        r"('[^']*'|[a-zA-Z_][a-zA-Z0-9_]*|!=|>=|<=|>|<|=|\(|\)|-?\d+(?:\.\d+)?|LIKE)",
        expr,
    )
    out_tokens: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in op_map:
            out_tokens.append(op_map[low])
        else:
            out_tokens.append(tok)

    return " ".join(out_tokens)


@router.get("/$metadata")
async def get_metadata() -> Response:
    """Generate OData v4 EDM XML metadata schema definition from catalog."""
    tree = default_catalog.get_unified_tree()
    entity_types_xml: list[str] = []
    entity_sets_xml: list[str] = []

    for ds_name, ds_info in tree.items():
        schemas = ds_info.get("schemas", {})
        for schema_name, schema_info in schemas.items():
            tables = schema_info.get("tables", [])
            for tbl in tables:
                tname = tbl.get("name", "")
                entity_name = f"{schema_name}_{tname}"
                full_path = f"{ds_name}.{schema_name}.{tname}"

                cached_schema = default_catalog._table_cache.get(full_path)
                if cached_schema and cached_schema.columns:
                    cols = cached_schema.columns
                else:
                    cols = [
                        ColumnMetadata(name="id", data_type=DataType.STRING, is_primary_key=True),
                        ColumnMetadata(name="data", data_type=DataType.STRING, nullable=True),
                    ]

                pk_col = next((c.name for c in cols if c.is_primary_key), cols[0].name)

                props_xml = []
                for c in cols:
                    edm_type = EDM_TYPE_MAP.get(c.data_type, "Edm.String")
                    nullable_attr = "true" if c.nullable else "false"
                    props_xml.append(
                        f'        <Property Name="{xml_escape(c.name)}" Type="{edm_type}" Nullable="{nullable_attr}" />'
                    )

                entity_types_xml.append(
                    f'      <EntityType Name="{xml_escape(entity_name)}">\n'
                    f"        <Key>\n"
                    f'          <PropertyRef Name="{xml_escape(pk_col)}" />\n'
                    f"        </Key>\n"
                    + "\n".join(props_xml)
                    + "\n      </EntityType>"
                )

                esc_name = xml_escape(entity_name)
                entity_sets_xml.append(
                    f'        <EntitySet Name="{esc_name}" EntityType="FederatedHub.{esc_name}" />'
                )

    xml_content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<edmx:Edmx Version="4.0" xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx">\n'
        '  <edmx:DataServices>\n'
        '    <Schema Namespace="FederatedHub" xmlns="http://docs.oasis-open.org/odata/ns/edm">\n'
        + "\n".join(entity_types_xml)
        + '\n      <EntityContainer Name="Container">\n'
        + "\n".join(entity_sets_xml)
        + "\n      </EntityContainer>\n"
        "    </Schema>\n"
        "  </edmx:DataServices>\n"
        "</edmx:Edmx>"
    )

    return Response(content=xml_content, media_type="application/xml; charset=utf-8")


@router.get("")
async def get_service_document() -> JSONResponse:
    """OData v4 service document enumerating entity collections."""
    tree = default_catalog.get_unified_tree()
    entity_sets: list[dict[str, str]] = []

    for _ds_name, ds_info in tree.items():
        schemas = ds_info.get("schemas", {})
        for schema_name, schema_info in schemas.items():
            tables = schema_info.get("tables", [])
            for tbl in tables:
                tname = tbl.get("name", "")
                entity_sets.append(
                    {
                        "name": f"{schema_name}_{tname}",
                        "kind": "EntitySet",
                        "url": f"{schema_name}/{tname}",
                    }
                )

    return JSONResponse(
        content={
            "@odata.context": "/api/v1/odata/$metadata",
            "value": entity_sets,
        }
    )


@router.get("/{schema}/{table}")
async def query_entity_set(
    schema: str,
    table: str,
    request: Request,
    catalog: str | None = None,
    select: str | None = Query(None, alias="$select", description="Columns to project"),
    filter_expr: str | None = Query(None, alias="$filter", description="OData filter clause"),
    orderby: str | None = Query(None, alias="$orderby", description="Sorting criteria"),
    top: int = Query(100, alias="$top", ge=1, le=10000, description="Max rows to return"),
    skip: int = Query(0, alias="$skip", ge=0, description="Rows to skip"),
    count: bool = Query(False, alias="$count", description="Include row count annotation"),
    context: SecurityContext = Depends(get_security_context),  # noqa: B008
) -> JSONResponse:
    """Serve OData v4 entity set queries with $filter, $select, $top, $skip, and $orderby."""
    if not IDENTIFIER_REGEX.match(schema) or not IDENTIFIER_REGEX.match(table):
        raise HTTPException(status_code=400, detail="Invalid schema or table identifier.")

    full_path = resolve_view_path(schema, table, catalog)

    # 1. Projection ($select)
    if select:
        col_list = [c.strip() for c in select.split(",") if c.strip()]
        for c in col_list:
            if not IDENTIFIER_REGEX.match(c):
                raise HTTPException(status_code=400, detail=f"Invalid $select column: '{c}'")
        select_clause = ", ".join(col_list)
    else:
        select_clause = "*"

    # 2. Filter ($filter)
    where_sql = ""
    if filter_expr:
        try:
            translated_where = translate_odata_filter(filter_expr)
            if translated_where:
                where_sql = f" WHERE {translated_where}"
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid $filter expression: {exc}") from exc

    # 3. Order By ($orderby)
    order_sql = ""
    if orderby:
        order_parts: list[str] = []
        for part in orderby.split(","):
            items = part.strip().split()
            if not items:
                continue
            col = items[0]
            if not IDENTIFIER_REGEX.match(col):
                raise HTTPException(status_code=400, detail=f"Invalid $orderby column: '{col}'")
            direction = "ASC"
            if len(items) > 1 and items[1].lower() in ("desc", "asc"):
                direction = items[1].upper()
            order_parts.append(f"{col} {direction}")
        if order_parts:
            order_sql = f" ORDER BY {', '.join(order_parts)}"

    # 4. Limit and Offset ($top, $skip)
    offset_sql = f" OFFSET {skip}" if skip > 0 else ""
    sql = f"SELECT {select_clause} FROM {full_path}{where_sql}{order_sql} LIMIT {top}{offset_sql}"  # noqa: S608

    try:
        arrow_table, _metrics = await federated_executor.execute(
            sql, security_context=context, protocol="OData"
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"OData query execution failed: {exc}") from exc

    cols = arrow_table.column_names
    pydict = arrow_table.to_pydict()
    row_count = arrow_table.num_rows

    records: list[dict[str, Any]] = [
        {col: pydict[col][i] for col in cols}
        for i in range(row_count)
    ]

    response_payload: dict[str, Any] = {
        "@odata.context": f"/api/v1/odata/$metadata#{schema}_{table}",
        "value": records,
    }
    if count:
        response_payload["@odata.count"] = row_count

    return JSONResponse(content=response_payload)
