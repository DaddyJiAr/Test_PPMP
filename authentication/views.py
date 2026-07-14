from rest_framework.response import Response
from rest_framework.decorators import api_view

from api.services import public_supabase, private_supabase, get_user

def get_current_user(id):
    response = private_supabase.table("USER").select("*").eq("UserID", id).execute()
    return response.data

@api_view(['GET'])
def get_users(request):
    token = get_token(request)
    user = get_user(token)
    if user is None:
        return Response({"error": "Unauthorized", "user": user, "token": token}, status=401)
    response = private_supabase.table("USER").select("*").execute()
    print(response.data)
    return Response({"user": user, "token": token})

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

@api_view(['GET'])
def get_role(request):
    token = get_token(request)
    user = get_user(token)
    if user is None:
        return Response({"error": "Unauthorized", "user": user, "token": token}, status=401)
    return Response(user[0]["Role"])

def get_token(request):
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return Response({"error": "Unauthorized"}, status=401)
    token = auth.replace("Bearer ", "")
    return token

def get_role_token(token):
    user = get_user(token)
    if user is None:
        return
    else:
        return user[0]["Role"]

def check_user(request):
    token = get_token(request)
    user = get_user(token)
    if user is None:
        return False
    else:
        return True

@api_view(['GET'])
def get_user_test(request):
    token = get_token(request)
    role = get_role_token(token)
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