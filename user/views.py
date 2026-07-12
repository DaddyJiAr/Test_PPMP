from rest_framework.response import Response
from rest_framework.decorators import api_view

from api.services import public_supabase, private_supabase, get_user
from authentication.views import get_token

@api_view(['GET'])
def get_header_info(request):
    token = get_token(request)
    user = get_user(token)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    else:
        return Response({"UserFullName": user[0]["FullName"], "UserEmailAddress": user[0]["EmailAddress"], "UserRole": user[0]["Role"]}, status=200)
