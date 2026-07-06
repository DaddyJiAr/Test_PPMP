from rest_framework.response import Response
from rest_framework.decorators import api_view

from api.services import public_supabase


@api_view(['GET'])
def getData(request):
    response = public_supabase.table("FISCAL_YEAR").select("*").execute()
    print(response.data)
    return Response(response.data)