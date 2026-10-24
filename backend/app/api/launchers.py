"""One-click launchers for Power BI (.pbids) and Microsoft Excel (.odc) data connections."""

from __future__ import annotations

import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

router = APIRouter()


@router.get("/pbids")
async def generate_pbids(
    request: Request,
    host: str | None = Query(None, description="Hostname of PGWire gateway"),
    port: int = Query(5433, ge=1, le=65535, description="Port of PGWire gateway"),
    database: str = Query("federated", description="Database catalog name"),
    mode: str = Query("DirectQuery", description="Power BI query mode (DirectQuery or Import)"),
) -> Response:
    """Generate a .pbids (Power BI Data Source) file for 1-click DirectQuery modeling."""
    server_host = host or request.url.hostname or "127.0.0.1"

    pbids_content = {
        "version": "0.1",
        "connections": [
            {
                "details": {
                    "protocol": "postgresql",
                    "address": {
                        "server": f"{server_host}:{port}",
                        "database": database,
                    },
                    "authentication": None,
                    "query": None,
                },
                "options": {},
                "mode": mode,
            }
        ],
    }

    json_bytes = json.dumps(pbids_content, indent=2).encode("utf-8")
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="federated_data_hub.pbids"'},
    )


@router.get("/odc")
async def generate_odc(
    request: Request,
    schema: str | None = Query(None, description="Optional schema name"),
    table: str | None = Query(None, description="Optional table name"),
) -> Response:
    """Generate an .odc (Office Data Connection) file for 1-click Excel OData feed import."""
    base_url = str(request.base_url).rstrip("/")
    if schema and table:
        feed_url = f"{base_url}/api/v1/odata/{schema}/{table}"
        command_text = f"{schema}_{table}"
    else:
        feed_url = f"{base_url}/api/v1/odata"
        command_text = "FederatedHub"

    odc_content = f"""<html xmlns:o="urn:schemas-microsoft-com:office:office"
xmlns:x="urn:schemas-microsoft-com:office:excel"
xmlns:odc="urn:schemas-microsoft-com:office:odc">
<head>
<meta http-equiv="Content-Type" content="text/x-ms-odc; charset=utf-8"/>
<meta name="ProgId" content="ODC.DataFeed"/>
<meta name="SourceType" content="OLEDB"/>
<title>Federated Data Hub</title>
<xml id="docprops"><o:DocumentProperties
  xmlns:o="urn:schemas-microsoft-com:office:office">
  <o:Name>Federated Data Hub</o:Name>
</xml>
<xml id="msodc"><odc:OfficeDataConnection
  xmlns:odc="urn:schemas-microsoft-com:office:odc">
  <odc:Connection odc:Type="OLEDB">
    <odc:ConnectionString>Provider=Microsoft.Data.Mashup.Provider;Data Source={feed_url}</odc:ConnectionString>
    <odc:CommandType>Table</odc:CommandType>
    <odc:CommandText>{command_text}</odc:CommandText>
  </odc:Connection>
</odc:OfficeDataConnection>
</xml>
</head>
<body>
</body>
</html>
"""

    return Response(
        content=odc_content.encode("utf-8"),
        media_type="text/x-ms-odc",
        headers={"Content-Disposition": 'attachment; filename="federated_data_hub.odc"'},
    )
