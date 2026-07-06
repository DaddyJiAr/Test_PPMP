from dotenv import load_dotenv
import os
from supabase import create_client

load_dotenv()

print("SUPABASE_URL =", os.getenv("SUPABASE_URL"))
print("ANON exists =", os.getenv("SUPABASE_ANON_KEY") is not None)
print("SERVICE exists =", os.getenv("SUPABASE_SERVICE_ROLE_KEY") is not None)

url = os.getenv("SUPABASE_URL")

public_supabase = create_client(url, os.getenv("SUPABASE_ANON_KEY"))
private_supabase = create_client(url, os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
