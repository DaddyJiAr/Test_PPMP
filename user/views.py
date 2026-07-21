from rest_framework import response
from rest_framework.response import Response
from rest_framework.decorators import api_view

from api.utils import private_supabase, get_user, get_token, check_admin


@api_view(['GET'])
def get_header_info(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found", "user": user,}, status=401)
    else:
        return Response({"UserFullName": user["FullName"], "UserEmailAddress": user["EmailAddress"], "UserRole": user["Role"]}, status=200)

@api_view(['GET'])
def get_admin_name(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    else:
        admin_name = private_supabase.table("USER").select("FullName").eq("Role", "Admin").single().execute()
        return Response({"fullname": admin_name.data["FullName"]}, status=200)

@api_view(['PUT'])
def update_fullname(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    else:
        new_fullname = request.data["fullName"]
        response = private_supabase.table("USER").update({
            "FullName": new_fullname
        }).eq("UserID", user["UserID"]).execute()
        if response is None:
            return Response({"error": "Error updating user"}, status=500)
        else:
            return Response({"status": "success"}, status=200)


@api_view(['POST'])
def create_user(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    email = request.POST["email"]
    password = request.POST["password"]
    fullname = request.POST["fullName"]
    role = request.POST["role"]
    status = "Active"
    response = private_supabase.auth.admin.create_user({
        "email": email,
        "password": password,
        "email_confirm": False
    })

    user = response.user

    response = private_supabase.table("USER").insert({
            "UserID": user.id,
            "FullName": fullname,
            "EmailAddress": email,
            "Password": password,
            "Role": role,
            "Status": status,
        }).execute()
    if response is None:
        return Response({"error": "Error creating user"}, status=500)
    else:
        return Response({"status": "success"}, status=200)

@api_view(['PUT'])
def update_user_status(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    if check_admin(request):
        return Response({"error": "Unauthorized access"}, status=401)
    else:
        user_id = request.data["userId"]
        status = request.data["status"]
        response = private_supabase.table("USER").update({"Status": status}).eq("UserID", user_id).execute()
        if response is None:
            return Response({"error": "Error updating user"}, status=500)
        else:
            return Response({"status": "success"}, status=200)

@api_view(['PUT'])
def promote_user(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    if check_admin(request):
        return Response({"error": "Unauthorized access"}, status=401)
    else:
        user_id = request.data["userId"]
        response = private_supabase.table("USER").update({"Role": "Admin"}).eq("UserID", user_id).execute()
        if response is None:
            return Response({"error": "Error updating user"}, status=500)
        response = private_supabase.table("USER").update({"Role": "User"}).eq("UserID", user["UserID"]).execute()
        if response is None:
            return Response({"error": "Error updating user"}, status=500)
        else:
            return Response({"status": "success"}, status=200)