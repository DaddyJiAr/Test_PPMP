from rest_framework.response import Response
from rest_framework.decorators import api_view

from api.services import public_supabase, private_supabase, get_user
from authentication.views import get_token

@api_view(['GET'])
def get_user_fullname(request):
    token = get_token(request)
    user = get_user(token)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    else:
        return Response({"user": user[0]["FullName"]}, status=200)
