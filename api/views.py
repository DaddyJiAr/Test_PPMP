from rest_framework.response import Response
from rest_framework.decorators import api_view

from api.services import public_supabase, private_supabase
from excel import testingPPMP, upload_excel


@api_view(['GET'])
def getData(request):
    response = public_supabase.table("FISCAL_YEAR").select("*").execute()
    print(response.data)
    return Response(response.data)

@api_view(['POST'])
def testPPMP(request):
    excel_file = request.FILES["file"]
    row_start = int(request.POST["startRow"])
    name_column = int(request.POST["itemName"])
    unit_column = int(request.POST["unit"])
    quantity_column = int(request.POST["quantity"])
    price_per_unit_column = int(request.POST["unitPrice"])
    df = testingPPMP(excel_file, row_start, name_column, unit_column, quantity_column, price_per_unit_column)
    # e = upload_excel(df)
    return Response({"data": df.head().to_dict(orient="records"), 'name': name_column, 'unit': unit_column, 'quantity': quantity_column, 'price': price_per_unit_column})


@api_view(['POST'])
def upload(request):
    excel_file = request.FILES["file"]
    total_abc = request.POST.get("totalABC")
    if total_abc is None:
        return Response(
            {"error": "Missing required field: totalABC"},
            status=400
        )
    total_ABC = float(total_abc)
    row_start = int(request.POST["startRow"])
    name_column = int(request.POST["itemName"])
    unit_column = int(request.POST["unit"])
    quantity_column = int(request.POST["quantity"])
    price_per_unit_column = int(request.POST["unitPrice"])
    df = testingPPMP(excel_file, row_start, name_column, unit_column, quantity_column, price_per_unit_column)
    e = upload_excel(df, total_ABC)
    return Response({"status": True, 'err': e})

@api_view(['GET'])
def masterlist(request):
    response = private_supabase.table("PPMP_ITEM").select("*").execute()
    return Response(response.data)


@api_view(['POST'])
def purchase_request(request):
    item_id = int(request.POST["item_id"])
    # return Response({"status": int(get_item_detail(item_id, "PendingQuantity"))})
    user_id = request.POST["user_id"]
    specifications = request.POST["specifications"]
    request_quantity = int(request.POST["request_quantity"])
    status = "Pending"
    available_quantity = int(get_item_detail(item_id, "AvailableQuantity"))
    pending_quantity = int(get_item_detail(item_id, "PendingQuantity"))

    if request_quantity > available_quantity:
        return Response(
            {"error": "Not enough available quantity"},
            status=400
        )

    private_supabase.table("PURCHASE_REQUEST").insert({
        "Status": status,
        "Specifications": specifications,
        "ItemID": item_id,
        "UserID": user_id,
        "RequestQuantity": request_quantity,
    }).execute()
    private_supabase.table("PPMP_ITEM").update({
        "AvailableQuantity": (available_quantity - request_quantity),
        "PendingQuantity": pending_quantity + request_quantity,
    }).eq("ItemID", item_id).execute()
    return Response({"status": "success"})

def get_item_detail(item_id, column_name):
    response = private_supabase.table("PPMP_ITEM").select(column_name).eq("ItemID", item_id).single().execute()
    return response.data[column_name]