from rest_framework import response
from rest_framework.response import Response
from rest_framework.decorators import api_view
from supabase_auth.errors import AuthApiError

from api.utils import private_supabase, get_user, get_token, get_role_token, public_supabase, get_auth_user, \
    check_fields

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
        return Response({
            "status": "success",
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
        })
    except Exception as e:
        return Response({"error": "Unauthorized. Error logging in."}, status=401)


@api_view(['PUT'])
def update_password(request):
    try:
        user = get_auth_user(request)
    except:
        return Response({"error": "User not found"}, status=401)
    req = ["current_password", "new_password"]
    current_password = request.data['currentPassword']
    missing_fields = check_fields(req, request)
    if missing_fields:
        return Response({"error": "Required fields missing", "missingFields": missing_fields}, status=400)
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
