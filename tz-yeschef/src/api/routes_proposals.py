import uuid
from datetime import datetime, timezone

import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi.responses import HTMLResponse
from src.db.session import get_db
from src.models.tables import (
    Proposal,
    Execution,
    Workspace,
    MeetingSession,
    ProposalStatus,
    ExecutionStatus,
)

router = APIRouter(prefix="/api")

# Store background task refs to prevent GC
_background_tasks: set[asyncio.Task] = set()


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Approve a proposal and trigger execution."""
    result = await db.execute(
        select(Proposal).where(Proposal.id == uuid.UUID(proposal_id))
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != ProposalStatus.pending:
        raise HTTPException(
            status_code=400, detail=f"Proposal already {proposal.status.value}"
        )

    proposal.status = ProposalStatus.approved

    # Create execution record
    execution = Execution(
        proposal_id=proposal.id,
        status=ExecutionStatus.pending,
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    # Get workspace for entity_id
    sess_result = await db.execute(
        select(MeetingSession).where(MeetingSession.id == proposal.session_id)
    )
    session = sess_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Meeting session not found")

    ws_result = await db.execute(
        select(Workspace).where(Workspace.id == session.workspace_id)
    )
    workspace = ws_result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Extract fields before passing to background task (avoid detached ORM object)
    exec_id = str(execution.id)
    proposal_action_type = proposal.action_type
    proposal_title = proposal.title
    proposal_body = proposal.body
    proposal_recipient = proposal.recipient
    proposal_session_id = str(proposal.session_id)
    proposal_obj_id = str(proposal.id)
    entity_id = workspace.composio_entity_id
    ws_id = str(workspace.id)

    # Broadcast execution started
    try:
        from src.services.ws_manager import manager

        await manager.broadcast(
            ws_id,
            {
                "type": "execution_started",
                "data": {
                    "execution_id": exec_id,
                    "proposal_id": proposal_id,
                    "action_type": proposal_action_type,
                },
            },
        )
    except Exception:
        pass

    # Execute in background (store ref to prevent GC)
    task = asyncio.create_task(
        _run_execution(
            execution_id=exec_id,
            action_type=proposal_action_type,
            title=proposal_title,
            body=proposal_body,
            recipient=proposal_recipient,
            proposal_id=proposal_obj_id,
            entity_id=entity_id,
            workspace_id=ws_id,
            session_id=proposal_session_id,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return {
        "status": "approved",
        "execution_id": exec_id,
    }


@router.post("/proposals/{proposal_id}/dismiss")
async def dismiss_proposal(
    proposal_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Dismiss a proposal."""
    result = await db.execute(
        select(Proposal).where(Proposal.id == uuid.UUID(proposal_id))
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.status != ProposalStatus.pending:
        raise HTTPException(
            status_code=400, detail=f"Proposal already {proposal.status.value}"
        )

    proposal.status = ProposalStatus.dismissed
    await db.commit()

    # Broadcast update
    sess_result = await db.execute(
        select(MeetingSession).where(MeetingSession.id == proposal.session_id)
    )
    session = sess_result.scalar_one_or_none()

    try:
        from src.services.ws_manager import manager

        if not session:
            return {"status": "dismissed"}
        await manager.broadcast(
            str(session.workspace_id),
            {
                "type": "proposal_updated",
                "data": {
                    "id": proposal_id,
                    "status": "dismissed",
                },
            },
        )
    except Exception:
        pass

    return {"status": "dismissed"}


@router.get("/artifacts/{execution_id}/raw")
async def get_artifact_raw(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve raw artifact HTML (used as iframe src)."""
    result = await db.execute(
        select(Execution).where(Execution.id == uuid.UUID(execution_id))
    )
    execution = result.scalar_one_or_none()
    if not execution or not execution.artifact_html:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return HTMLResponse(content=execution.artifact_html)


@router.get("/artifacts/{execution_id}")
async def get_artifact(
    execution_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve artifact HTML wrapped in a YesChef branded page."""
    result = await db.execute(
        select(Execution).where(Execution.id == uuid.UUID(execution_id))
    )
    execution = result.scalar_one_or_none()
    if not execution or not execution.artifact_html:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # Get the artifact title from the execution result JSON
    title = "Artifact"
    if execution.result and isinstance(execution.result, dict):
        title = execution.result.get("title", "Artifact")

    wrapper = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — YesChef</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ height: 100%; overflow: hidden; }}
  body {{ font-family: 'Inter', -apple-system, sans-serif; display: flex; flex-direction: column; }}
  .yc-navbar {{
    display: flex; align-items: center; gap: 14px;
    padding: 12px 24px; background: #082848;
    border-bottom: 2px solid rgba(198,165,89,0.3);
    flex-shrink: 0;
  }}
  .yc-navbar-logo {{
    width: 28px; height: 28px; border-radius: 4px;
    background: #C6A559; display: flex; align-items: center; justify-content: center;
    font-family: 'Playfair Display', Georgia, serif; font-size: 18px; font-weight: 700; color: #082848;
  }}
  .yc-navbar-brand {{
    font-family: 'Playfair Display', Georgia, serif;
    font-size: 18px; font-weight: 700; color: #FAFAFA;
  }}
  .yc-navbar-sep {{
    width: 1px; height: 20px; background: rgba(198,165,89,0.3);
  }}
  .yc-navbar-title {{
    font-size: 14px; font-weight: 500; color: #C6A559;
    flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }}
  .yc-navbar-badge {{
    font-size: 11px; font-weight: 600; color: #082848; background: #C6A559;
    padding: 3px 10px; border-radius: 12px; text-transform: uppercase; letter-spacing: 0.5px;
  }}
  .yc-artifact-frame {{
    flex: 1; border: none; width: 100%; height: 100%;
  }}
</style>
</head>
<body>
  <nav class="yc-navbar">
    <div class="yc-navbar-logo">Y</div>
    <span class="yc-navbar-brand">YesChef</span>
    <div class="yc-navbar-sep"></div>
    <span class="yc-navbar-title">{title}</span>
    <span class="yc-navbar-badge">Artifact</span>
  </nav>
  <iframe class="yc-artifact-frame" src="/api/artifacts/{execution_id}/raw" sandbox="allow-scripts"></iframe>
</body>
</html>"""
    return HTMLResponse(content=wrapper)


async def _run_execution(
    execution_id: str,
    action_type: str,
    title: str,
    body: str,
    recipient: str | None,
    proposal_id: str,
    entity_id: str | None,
    workspace_id: str,
    session_id: str | None = None,
):
    """Run the actual execution in background using plain field values (not ORM objects)."""
    from src.db.engine import async_session
    from src.services.executor import execute_gmail_draft, execute_generic_draft, execute_artifact

    async with async_session() as db:
        result = await db.execute(
            select(Execution).where(Execution.id == uuid.UUID(execution_id))
        )
        execution = result.scalar_one_or_none()
        if not execution:
            return

        execution.status = ExecutionStatus.running
        await db.commit()

        try:
            if action_type == "gmail_draft" and entity_id:
                exec_result = await execute_gmail_draft(
                    entity_id=entity_id,
                    recipient=recipient or "",
                    subject=title,
                    body=body,
                    session_id=session_id,
                )
            elif action_type == "html_artifact":
                exec_result = await execute_artifact(
                    title=title,
                    body=body,
                    session_id=session_id,
                )
                if exec_result.get("artifact_html"):
                    execution.artifact_html = exec_result["artifact_html"]
            else:
                exec_result = await execute_generic_draft(
                    title=title,
                    body=body,
                    session_id=session_id,
                )

            execution.status = (
                ExecutionStatus.success
                if exec_result.get("status") == "success"
                else ExecutionStatus.failed
            )
            # Don't store artifact_html in the JSONB result (it can be large)
            result_data = {k: v for k, v in exec_result.items() if k != "artifact_html"}
            if exec_result.get("artifact_html"):
                result_data["artifact_url"] = f"/api/artifacts/{execution_id}"
            execution.result = result_data
            execution.error = exec_result.get("error")
            execution.completed_at = datetime.now(timezone.utc)
        except Exception as e:
            execution.status = ExecutionStatus.failed
            execution.error = str(e)
            execution.completed_at = datetime.now(timezone.utc)

        await db.commit()

        # Broadcast execution result
        try:
            from src.services.ws_manager import manager

            await manager.broadcast(
                workspace_id,
                {
                    "type": "execution_completed",
                    "data": {
                        "execution_id": execution_id,
                        "proposal_id": proposal_id,
                        "status": execution.status.value,
                        "result": execution.result,
                        "error": execution.error,
                    },
                },
            )
        except Exception:
            pass
