from rest_framework import response
from rest_framework.response import Response
from rest_framework.decorators import api_view

from api.utils import private_supabase, get_user, get_token

@api_view(['GET'])
def get_header_info(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found", "user": user,}, status=401)
    else:
        return Response({"UserFullName": user["FullName"], "UserEmailAddress": user["EmailAddress"], "UserRole": user["Role"]}, status=200)

@api_view(['GET'])
def get_admin_name(request):
    token = get_token(request)
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    else:
        admin_name = private_supabase.table("USER").select("FullName").eq("Role", "Admin").single().execute()
        return Response({"fullname": admin_name.data["FullName"]}, status=200)