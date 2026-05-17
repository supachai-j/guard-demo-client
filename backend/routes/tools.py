"""MCP / HTTP tool registry endpoints.

Tools are external functions the chat agent can invoke. The admin UI
manages them as CRUD; the test endpoint pings each one and (for MCP)
stores the discovered capability set so the agent doesn't have to
re-discover on every chat turn."""

from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth as _auth
from ..database import get_db
from ..models import AppConfig, Tool
from ..schemas import ToolCreate, ToolResponse, ToolUpdate
from ..toolhive import discover_mcp_tool_capabilities_sync, store_capabilities

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("", response_model=List[ToolResponse])
async def get_tools(db: Session = Depends(get_db)):
    tools = db.query(Tool).all()
    return tools


@router.post("", response_model=ToolResponse, dependencies=[Depends(_auth.require_admin)])
async def create_tool(tool: ToolCreate, db: Session = Depends(get_db)):
    db_tool = Tool(**tool.dict())
    db.add(db_tool)
    db.commit()
    db.refresh(db_tool)
    return db_tool


@router.put("/{tool_id}", response_model=ToolResponse, dependencies=[Depends(_auth.require_admin)])
async def update_tool(tool_id: int, tool: ToolUpdate, db: Session = Depends(get_db)):
    db_tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not db_tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    for field, value in tool.dict(exclude_unset=True).items():
        setattr(db_tool, field, value)

    db.commit()
    db.refresh(db_tool)
    return db_tool


@router.delete("/{tool_id}", dependencies=[Depends(_auth.require_admin)])
async def delete_tool(tool_id: int, db: Session = Depends(get_db)):
    db_tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not db_tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    db.delete(db_tool)
    db.commit()
    return {"message": "Tool deleted"}


@router.post("/test/{tool_id}", dependencies=[Depends(_auth.require_admin)])
async def test_tool(tool_id: int, db: Session = Depends(get_db)):
    """Test a tool's connectivity and basic functionality"""
    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    # Get configuration for Lakera parameters
    config = db.query(AppConfig).first()
    lakera_api_key = config.lakera_api_key if config and config.lakera_enabled else None
    lakera_project_id = config.lakera_project_id if config else None
    lakera_blocking_mode = config.lakera_blocking_mode if config and config.lakera_enabled else True

    if tool.type in ["mcp", "http"]:
        # For MCP tools, try to discover capabilities
        try:
            discovery_result = await discover_mcp_tool_capabilities_sync(
                {"name": tool.name, "endpoint": tool.endpoint},
                lakera_api_key=lakera_api_key,
                lakera_project_id=lakera_project_id,
                lakera_blocking_mode=lakera_blocking_mode,
            )
            # Store the discovered capabilities
            await store_capabilities(tool.id, tool.name, discovery_result, db)
            return {
                "status": "success",
                "message": f"MCP tool {tool.name} discovery completed",
                "discovery": discovery_result,
            }
        except Exception as e:
            return {"status": "error", "message": f"MCP tool discovery failed: {str(e)}"}
    else:
        # For HTTP tools, test basic connectivity
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try HEAD first, then GET if HEAD fails
                try:
                    response = await client.head(tool.endpoint)
                    if response.status_code < 400:
                        return {"status": "success", "message": f"HTTP tool {tool.name} is reachable"}
                except Exception:
                    pass

                # Try GET as fallback
                response = await client.get(tool.endpoint, timeout=10.0)
                if response.status_code < 400:
                    return {"status": "success", "message": f"HTTP tool {tool.name} is reachable"}
                else:
                    return {"status": "error", "message": f"HTTP tool returned status {response.status_code}"}
        except Exception as e:
            return {"status": "error", "message": f"HTTP tool test failed: {str(e)}"}


@router.get("/{tool_id}/capabilities")
async def get_tool_capabilities(tool_id: int, db: Session = Depends(get_db)):
    """Get stored capabilities for an MCP tool"""
    from ..toolhive import get_stored_capabilities

    tool = db.query(Tool).filter(Tool.id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    if tool.type != "mcp":
        raise HTTPException(status_code=400, detail="Only MCP tools have capabilities")

    capabilities = await get_stored_capabilities(tool_id, db)
    if capabilities:
        return {"tool_id": tool_id, "tool_name": tool.name, "capabilities": capabilities}
    else:
        return {
            "tool_id": tool_id,
            "tool_name": tool.name,
            "capabilities": None,
            "message": "No capabilities discovered yet. Run the test endpoint first.",
        }
