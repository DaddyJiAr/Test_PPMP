from dotenv import load_dotenv
import os
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")

public_supabase = create_client(url, os.getenv("SUPABASE_ANON_KEY"))
private_supabase = create_client(url, os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

def get_user(token):
    try:
        user = private_supabase.auth.get_user(token).user
        response = private_supabase.table("USER").select("*").eq("UserID", user.id).execute()
        return response.data
    except Exception:
        return None
