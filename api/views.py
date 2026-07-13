from rest_framework import response
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
    year = (request.POST["year"])
    unit_column = int(request.POST["unit"])
    quantity_column = int(request.POST["quantity"])
    price_per_unit_column = int(request.POST["unitPrice"])
    df = testingPPMP(excel_file, row_start, name_column, unit_column, quantity_column, price_per_unit_column)
    e = upload_excel(df, total_ABC, year)
    return Response({"status": True, 'err': e})

@api_view(['GET'])
def fiscal_years(request):
    response = private_supabase.table("FISCAL_YEAR").select("Year").execute()
    return Response(response.data)

@api_view(['GET'])
def masterlist(request):
    response = private_supabase.table("PPMP_ITEM").select("*").execute()

    data = [
        {
            "itemId": item["ItemID"],
            "itemName": item["ItemName"],
            "unitMeasurement": item["UnitName"],
            "plannedQuantity": item["PlannedQuantity"],
            "availableQuantity": item["AvailableQuantity"],
            "pendingQuantity": item["PendingQuantity"],
            "fulfilledQuantity": item["ReceivedQuantity"],
            "priceCatalog": item["PricePerUnit"],
        }
        for item in response.data
    ]

    return Response(data)


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

@api_view(['POST'])
def dashboard_cards(request):
    year = request.POST["year"]
    fiscal_year = private_supabase.table("FISCAL_YEAR").select("*").eq("Year", year).single().execute()
    total_annual_budget = fiscal_year.data["TotalABC"]
    purchase_requests = private_supabase.table("PURCHASE_REQUEST").select("*").execute()
    ppmp_items = private_supabase.table("PPMP_ITEM").select("*").execute()
    committed_funds = 0
    requested_funds = 0
    available_lieu_pool_funds = 0
    arrived_funds = 0 # lapa
    pending_in_lieu_count = 0 #lapa
    for purchase_request in purchase_requests.data:
        purchase_request_item = private_supabase.table("PPMP_ITEM").select("*").eq("ItemID", purchase_request["ItemID"]).single().execute()
        committed_funds += purchase_request_item.data["PricePerUnit"] * purchase_request["RequestQuantity"] #include arrived items (kulang pa)
        requested_funds += purchase_request_item.data["PricePerUnit"] * purchase_request["RequestQuantity"] #lahat ng nasa pr (tama lang to)
    for ppmp_item in ppmp_items.data:
        available_lieu_pool_funds += ppmp_item["AvailableQuantity"] * ppmp_item["PricePerUnit"]
    open_funds = total_annual_budget - available_lieu_pool_funds
    logs = "" #lapa
    return Response({"totalAnnualBudget": total_annual_budget,
                     "committedFunds": committed_funds,
                     "availableLieuPoolFunds": available_lieu_pool_funds,
                     "openFunds": open_funds,
                     "requestedFunds": requested_funds,
                     "arrivedFunds": arrived_funds,
                     "pendingInLieuCount": pending_in_lieu_count,
                     "logs": logs
                     })