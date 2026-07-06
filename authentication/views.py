from django.shortcuts import render

# Create your views here.
from rest_framework.response import Response
from rest_framework.decorators import api_view

from api.services import public_supabase, private_supabase


@api_view(['GET'])
def getUsers(request):
    response = private_supabase.table("USER").select("*").execute()
    print(response.data)
    return Response(response.data)