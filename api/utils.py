from rest_framework.response import Response
from dotenv import load_dotenv
import os
from supabase import create_client

load_dotenv()
url = os.getenv("SUPABASE_URL")

public_supabase = create_client(url, os.getenv("SUPABASE_ANON_KEY"))
private_supabase = create_client(url, os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

def get_user(request):
    try:
        token = get_token(request)
        user = private_supabase.auth.get_user(token).user
        if user is None:
            return None
        response = private_supabase.table("USER").select("*").eq("UserID", user.id).single().execute()
        return response.data
    except Exception:
        return None

def get_auth_user(request):
    try:
        token = get_token(request)
        user = private_supabase.auth.get_user(token).user
        return user
    except Exception:
        return None

def get_token(request):
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    token = auth.replace("Bearer ", "")
    return token

def get_role_token(token):
    user = get_user(token)
    if user is None:
        return None
    else:
        return user[0]["Role"]

def check_user(request):
    token = get_token(request)
    user = get_user(token)
    if user is None:
        return False
    else:
        return True

def check_admin(request):
    token = get_token(request)
    user = get_user(token)
    if user is None:
        return False
    else:
        return user["Role"] == "Admin"

def check_fields(required_fields, request):
    missing_fields = [
        field for field in required_fields
        if not request.data.get(field)
    ]
    if missing_fields:
        return missing_fields
    else:
        return None