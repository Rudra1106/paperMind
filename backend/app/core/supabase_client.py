# -*- coding: utf-8 -*-
from supabase import create_client, Client
from app.core.config import get_settings

_client: Client | None = None

def get_supabase() -> Client:
    global _client
    if _client is None:
        s = get_settings()
        # supabase_server_key returns new sb_secret_... key if set, else legacy service_role JWT
        _client = create_client(s.supabase_url, s.supabase_server_key)
    return _client

