from rest_framework import response
from rest_framework.response import Response
from rest_framework.decorators import api_view

from api.utils import private_supabase, get_user, get_token, check_admin, check_fields


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
        try:
            admin_name = private_supabase.table("USER").select("FullName").eq("Role", "Admin").single().execute()
            return Response({"fullname": admin_name.data["FullName"]}, status=200)
        except Exception as e:
            return Response({"error": "Error fetching for user"}, status=500)

@api_view(['PUT'])
def update_fullname(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    else:
        try:
            missing_fields = check_fields(["fullName"], request)
            if missing_fields:
                return Response({"error": "Required fields missing", "missingFields": missing_fields}, status=400)
        except Exception as e:
            return Response({"error": "Invalid fields"}, status=400)
        new_fullname = request.data["fullName"]
        try:
            response = private_supabase.table("USER").update({
                "FullName": new_fullname
            }).eq("UserID", user["UserID"]).execute()
        except Exception as e:
            return Response({"error": "Error updating user"}, status=500)
        if response is None:
            return Response({"error": "Error updating user"}, status=500)
        else:
            return Response({"status": "success"}, status=200)


@api_view(['POST'])
def create_user(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    required_fields = ["email", "password", "fullName", "role"]
    missing_fields = check_fields(required_fields, request)
    try:
        if missing_fields:
            return Response({"error": "Required fields missing", "missingFields": missing_fields}, status=400)
    except Exception as e:
        return Response({"error": "Invalid fields"}, status=500)
    email = request.POST["email"]
    password = request.POST["password"]
    fullname = request.POST["fullName"]
    role = request.POST["role"]
    status = "Active"
    auth_user = None
    try:
        response = private_supabase.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": False
        })
        if response is None:
            return Response({"error": "Error creating user"}, status=500)
        auth_user = response.user
        response = private_supabase.table("USER").insert({
                "UserID": auth_user.id,
                "FullName": fullname,
                "EmailAddress": email,
                "Role": role,
                "Status": status,
            }).execute()
        if response is None:
            return Response({"error": "Error creating user"}, status=500)
    except:
        if auth_user is not None:
            try:
                private_supabase.auth.admin.delete_user(auth_user.id)
            except Exception:
                return Response({"error": "Error removing auth user after failure in USER table", "auth_user": auth_user.id}, status=500)
        return Response({"error": "Error creating user"}, status=500)
    return Response({"status": "success", "userId": response.data[0]["UserID"]}, status=201)

@api_view(['PUT'])
def update_user_status(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    if check_admin(request):
        return Response({"error": "Unauthorized access"}, status=401)
    else:
        required_fields = ["userId", "status",]
        missing_fields = check_fields(required_fields, request)
        try:
            if missing_fields:
                return Response({"error": "Required fields missing", "missingFields": missing_fields}, status=400)
        except Exception as e:
            return Response({"error": "Invalid fields"}, status=400)
        user_id = request.data["userId"]
        status = request.data["status"]
        try:
            response = private_supabase.table("USER").update({"Status": status}).eq("UserID", user_id).execute()
        except Exception as e:
            return Response({"error": "Error updating user"}, status=500)
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
        missing_fields = check_fields(["userId"], request)
        try:
            if missing_fields:
                return Response({"error": "Required fields missing", "missingFields": missing_fields}, status=400)
        except Exception as e:
            return Response({"error": "Invalid fields"}, status=400)
        user_id = request.data["userId"]
        admin_response = None
        response = None
        try:
            admin_response = private_supabase.table("USER").update({"Role": "Admin"}).eq("UserID", user_id).execute()
            response = private_supabase.table("USER").update({"Role": "User"}).eq("UserID", user["UserID"]).execute()
        except Exception as e:
            if admin_response is not None and response is None:
                try:
                    private_supabase.table("USER").update({"Role": "User"}).eq("UserID", user_id).execute()
                except Exception as e:
                    return Response({"error": "Error updating user after failure in role switch"}, status=500)
            return Response({"error": "Error updating user"}, status=500)
        if response is None:
            return Response({"error": "Error updating user"}, status=500)
        else:
            return Response({"status": "success"}, status=200)