from fastapi import Depends, HTTPException, Header
from sqlmodel import Session, select
from models.postgres_models import Employee, Session as DBSession
from database.db import get_session
from datetime import datetime

def get_current_user(token: str = Header(...), session: Session = Depends(get_session)) -> Employee:
    db_session = session.exec(select(DBSession).where(DBSession.token == token)).first()
    if not db_session or db_session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = session.get(Employee, db_session.employee_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

def require_admin(user: Employee = Depends(get_current_user)) -> Employee:
    if user.role != "Admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
