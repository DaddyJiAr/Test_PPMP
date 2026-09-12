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

    if missing_fields:
        return Response(
            {
                "error": "Required fields missing",
                "missingFields": missing_fields
            },
            status=400
        )

    email = request.data.get('email')
    password = request.data.get('password')

    try:
        auth_response = public_supabase.auth.sign_in_with_password({
            'email': email,
            'password': password
        })

        if not auth_response.user or not auth_response.session:
            return Response(
                {"error": "Unable to create authentication session"},
                status=401
            )

        auth_user = auth_response.user

        user_response = (
            private_supabase
            .table("USER")
            .select("*")
            .eq("UserID", auth_user.id)
            .single()
            .execute()
        )

        if not user_response.data:
            return Response(
                {"error": "User profile not found"},
                status=404
            )

        user = user_response.data

        if user["Status"] != "Active":
            return Response(
                {"error": "User status not set to active."},
                status=401
            )

        return Response({
            "status": "success",
            "access_token": auth_response.session.access_token,
            "refresh_token": auth_response.session.refresh_token,
        })

    except AuthApiError as e:
        return Response(
            {
                "error": "Unauthorized. Error logging in.",
                "message": str(e)
            },
            status=401
        )

    except Exception as e:
        return Response(
            {
                "error": "Error logging in.",
                "message": str(e)
            },
            status=500
        )

import os
import time
import httpx
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(['POST'])
def test_supabase_login(request):
    email = request.data.get("email")
    password = request.data.get("password")

    url = os.getenv("SUPABASE_URL")
    anon_key = os.getenv("SUPABASE_ANON_KEY")

    try:
        start = time.time()

        response = httpx.post(
            f"{url}/auth/v1/token?grant_type=password",
            headers={
                "apikey": anon_key,
                "Content-Type": "application/json",
            },
            json={
                "email": email,
                "password": password,
            },
            timeout=15,
        )

        elapsed = round(time.time() - start, 2)

        return Response({
            "success": True,
            "status": response.status_code,
            "elapsed": elapsed,
            "body": response.text[:1000],
        })

    except Exception as e:
        return Response({
            "success": False,
            "type": type(e).__name__,
            "error": str(e),
        })

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
    email_db = private_supabase.table("USER").select("*").eq("EmailAddress", email).maybe_single().execute()
    if email_db is None:
        return Response({"error": f"No email for: {email} is registered"}, status=404)
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

