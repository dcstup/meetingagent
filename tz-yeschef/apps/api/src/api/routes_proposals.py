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
    object-fit: contain;
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
    <img class="yc-navbar-logo" src="data:image/png;base64,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" alt="YesChef" />
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
