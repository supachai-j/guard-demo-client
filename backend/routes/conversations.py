"""Conversation history endpoints — multi-turn memory inspector for the
Admin Console. Conversations + messages are written by the chat path;
these routes just surface them."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import auth as _auth
from ..database import get_db
from ..models import Conversation, Message

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", dependencies=[Depends(_auth.require_admin)])
async def list_conversations(limit: int = 50, db: Session = Depends(get_db)):
    rows = (
        db.query(Conversation)
        .order_by(Conversation.updated_at.desc())
        .limit(min(max(limit, 1), 200))
        .all()
    )
    return {
        "conversations": [
            {
                "id": r.id,
                "title": r.title,
                "session_id": r.session_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]
    }


@router.get("/{conversation_id}", dependencies=[Depends(_auth.require_admin)])
async def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.asc())
        .all()
    )
    return {
        "id": conv.id,
        "title": conv.title,
        "session_id": conv.session_id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "flagged": bool(m.flagged),
                "guardrail_status": m.guardrail_status,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ],
    }


@router.delete("/{conversation_id}", dependencies=[Depends(_auth.require_admin)])
async def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.query(Message).filter(Message.conversation_id == conversation_id).delete()
    db.delete(conv)
    db.commit()
    return {"deleted": conversation_id}
