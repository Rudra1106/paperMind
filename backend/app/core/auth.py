# -*- coding: utf-8 -*-
from typing import Annotated
from fastapi import Header, HTTPException, Depends
from app.core.supabase_client import get_supabase

async def get_current_user(authorization: str = Header(default=None)) -> dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    try:
        user_response = get_supabase().auth.get_user(token)
        if not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return {"id": user_response.user.id, "email": user_response.user.email}
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(exc)}")

CurrentUser = Annotated[dict, Depends(get_current_user)]
