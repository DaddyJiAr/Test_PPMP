from rest_framework import response
from rest_framework.response import Response
from rest_framework.decorators import api_view
from supabase_auth.errors import AuthApiError

from api.utils import private_supabase, get_user, get_token, get_role_token, public_supabase, get_auth_user, \
    check_fields, create_supabase


@api_view(['GET'])
def get_users(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    try:
        response = private_supabase.table("USER").select("*").execute()
    except Exception as e:
        return Response({"error": "Error getting users"}, status=500)
    users = [
        {
            "userId": user["UserID"],
            "fullname": user["FullName"],
            "email": user["EmailAddress"],
            "role": user["Role"],
            "dateCreated": user["created_at"],
            "status": user["Status"],
        }
    for user in response.data
    ]
    print(response.data)
    return Response({"user": users})

@api_view(['POST'])
def login(request):
    req_fields = ['email', 'password']
    missing_fields = check_fields(req_fields, request)
    try:
        if missing_fields:
            return Response({"error": "Required fields missing", "missingFields": missing_fields}, status=400)
    except Exception as e:
        return Response({"error": "Invalid fields"}, status=400)
    email = request.POST['email']
    password = request.POST['password']
    try:
        response = public_supabase.auth.sign_in_with_password({'email': email, 'password': password})
        user = private_supabase.auth.get_user(response.session.access_token).user
        user = private_supabase.table("USER").select("*").eq("UserID", user.id).single().execute()
        if user.data["Status"] != "Active":
            return Response({"error": "User status not set to active."}, status=401)
        return Response({
            "status": "success",
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
        })
    except Exception as e:
        return Response({"error": "Unauthorized. Error logging in.", "message": str(e),}, status=401)


@api_view(['PUT'])
def update_password(request):
    try:
        user = get_auth_user(request)
    except:
        return Response({"error": "User not found"}, status=401)
    req = ["newPassword", "currentPassword", "accessToken", "refreshToken"]
    missing_fields = check_fields(req, request)
    if missing_fields:
        return Response({"error": "Required fields missing", "missingFields": missing_fields}, status=400)
    new_password = request.POST['newPassword']
    current_password = request.POST['currentPassword']
    access_token = request.POST['accessToken']
    refresh_token = request.POST['refreshToken']
    if new_password == current_password:
        return Response({"error": "New and Old Passwords match"}, status=400)
    try:
        client = create_supabase()
        client.auth.set_session(access_token, refresh_token)
        client.auth.update_user({
            "password": new_password
        })
        if response is not None:
            return Response({"status": "success"}, status=200)
        else:
            return Response({"error": "Error updating password"}, status=500)
    except AuthApiError:
        return Response({"error": "Invalid login credentials", "user": user}, status=401)
    return Response(user.email)

@api_view(['POST'])
def forgot_password(request):
    try:
        missing_fields = check_fields(["email"], request)
        if missing_fields:
            return Response({"error": "Required fields missing", "missingFields": missing_fields}, status=400)
    except Exception as e:
        return Response({"error": "Invalid fields"}, status=400)
    email = request.POST["email"]
    try:
        private_supabase.auth.reset_password_for_email(email, {"redirect_to": "https://cict-ppmp.vercel.app/reset-password"})
    except AuthApiError as e:
        return Response({"error": str(e)}, status=500)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
    return Response({"status": "success"}, status=200)


@api_view(['PUT'])
def reset_password(request):
    try:
        required_fields = ["accessToken", "refreshToken", "password"]
        missing_fields = check_fields(required_fields, request)
        if missing_fields:
            return Response({"error": "Required fields missing", "missingFields": missing_fields}, status=400)
    except Exception as e:
        return Response({"error": "Invalid fields"}, status=400)
    access_token = request.data["accessToken"]
    refresh_token = request.data["refreshToken"]
    password = request.data["password"]
    try:
        client = create_supabase()
        response = client.auth.set_session(access_token, refresh_token)
        user = response.user
        client.auth.update_user({"password": password})
    except AuthApiError as e:
        return Response({"error": str(e)}, status=500)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
    return Response({"status": "success"}, status=200)

