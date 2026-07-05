import asyncio
from app.core.supabase_client import get_supabase
async def run():
    supa = get_supabase()
    res = supa.table("papers").select("id").execute()
    print("Papers:", len(res.data) if res.data else 0)
    res2 = supa.table("topics").select("id").execute()
    print("Topics:", len(res2.data) if res2.data else 0)

asyncio.run(run())
