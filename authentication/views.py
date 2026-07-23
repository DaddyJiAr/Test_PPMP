from rest_framework import response
from rest_framework.response import Response
from rest_framework.decorators import api_view
from supabase_auth.errors import AuthApiError

from api.utils import private_supabase, get_user, get_token, get_role_token, public_supabase, get_auth_user


def get_current_user(id):
    response = private_supabase.table("USER").select("*").eq("UserID", id).execute()
    return response.data

@api_view(['GET'])
def get_users(request):
    token = get_token(request)
    user = get_user(request)
    if user is None:
        return Response({"error": "Unauthorized", "user": user, "token": token}, status=401)
    response = private_supabase.table("USER").select("*").execute()
    users = [{
        userId: user["UserID"],
        fullname: user["FullName"],
        email: user["EmailAddress"],
        role: user["Role"],
        dateCreated: user["created_at"],
        status: user["Status"],
    }
    for user in response.data
    ]
    print(response.data)
    return Response({"user": users})

@api_view(['POST'])
def login(request):
    email = request.POST['email']
    password = request.POST['password']
    try:
        response = public_supabase.auth.sign_in_with_password({'email': email, 'password': password})
        return Response({
            "status": "success",
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
        })
    except Exception:
        return Response({"status": "error", "error": "Unauthorized",}, status=401)


@api_view(['PUT'])
def update_password(request):
    try:
        user = get_auth_user(request)
    except:
        return Response({"error": "Invalid token"}, status=401)
    current_password = request.data['currentPassword']
    new_password = request.POST['newPassword']
    try:
        response = private_supabase.auth.sign_in_with_password({'email': user.email, 'password': current_password})
        if response is not None:
            response = private_supabase.auth.update_user({
                "password": new_password,
            })
            if response is not None:
                return Response({"status": "success"}, status=200)
            else:
                return Response({"error": "Error updating password"}, status=500)
    except AuthApiError:
        return Response({"error": "Invalid login credentials"}, status=401)
    return Response(user.email)

@api_view(['GET'])
def get_role(request):
    token = get_token(request)
    user = get_user(request)
    if user is None:
        return Response({"error": "Unauthorized", "user": user, "token": token}, status=401)
    return Response(user[0]["Role"])

@api_view(['GET'])
def get_user_test(request):
    token = get_token(request)
    role = get_role_token(request)
    if role is None:
        return Response({"error": "Unauthorized", "token": token}, status=401)
    if role != "Dean":
        return Response({"error": "Unauthorized", "role": role, "pakyu": "Jerson"}, status=403)
    else:
        return Response({"role": role, "token": token})

@api_view(["GET"])
def sign_up(request):
    email = request.data['email']
    password = request.data['password']
    fullname = request.data['fullname']
    role = request.data['role']
    status = "active"

    response = private_supabase.auth.admin.create_user({
        "email": email,
        "password": password,
        "email_confirm": True
    })
    user = response.user

    private_supabase.table("USER").insert({
            "UserID": user.id,
            "FullName": fullname,
            "EmailAddress": email,
            "Password": password,
            "Role": role,
            "Status": status,
    }).execute()

    return Response({"user": user, "status": "success"})