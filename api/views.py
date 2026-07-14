from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework.decorators import api_view
import pandas as pd
from api.services import private_supabase
from excel import testingPPMP, upload_excel

def get_item(item_id):
    response = private_supabase.table("PPMP_ITEM").select("*").eq("ItemID", item_id).single().execute()
    return response.data

def get_item_detail(item_id, column_name):
    response = private_supabase.table("PPMP_ITEM").select(column_name).eq("ItemID", item_id).single().execute()
    return response.data[column_name]

def get_ppmp_items(year):
    fiscal_year = private_supabase.table("FISCAL_YEAR").select("*").eq("Year", year).single().execute()
    return private_supabase.table("PPMP_ITEM").select("*").eq("FiscalYearID", fiscal_year.data["FiscalYearID"]).execute()

def get_headers(ppmp_items):
    total_planned_item_count = 0
    total_available_item_count = 0
    total_pending_item_count = 0
    total_fulfilled_item_count = 0

    for ppmp_item in ppmp_items.data:
        total_planned_item_count += ppmp_item["PlannedQuantity"]
        total_available_item_count += ppmp_item["AvailableQuantity"]
        total_pending_item_count += ppmp_item["PendingQuantity"]
        total_fulfilled_item_count += ppmp_item["ReceivedQuantity"]

    return total_planned_item_count, total_available_item_count, total_pending_item_count, total_fulfilled_item_count



@api_view(['POST'])
def get_ppmp_preview(request):
    excel_file = request.FILES["file"]
    row_start = int(request.POST["startRow"])
    name_column = int(request.POST["itemName"])
    unit_column = int(request.POST["unit"])
    quantity_column = int(request.POST["quantity"])
    price_per_unit_column = int(request.POST["unitPrice"])
    total_abc = request.POST.get("totalABC")
    year = request.POST.get("year")
    df, grand_total_amount, exists = testingPPMP(excel_file, row_start, name_column, unit_column, quantity_column, price_per_unit_column, year)
    print(grand_total_amount)
    if float(total_abc) < grand_total_amount:
        return Response({"error": "Total ABC is less than grand total"},)
    # e = upload_excel(df)
    return Response({"data": df.head().to_dict(orient="records"), 'name': name_column, 'unit': unit_column, 'quantity': quantity_column, 'price': price_per_unit_column, 'exists': exists})


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
    df, grand_total_amount, exists = testingPPMP(excel_file, row_start, name_column, unit_column, quantity_column, price_per_unit_column, year)
    if float(total_abc) < grand_total_amount:
        return Response({"error": "Total ABC is less than grand total"},)
    e = upload_excel(df, total_ABC, year)
    return Response({"status": True, 'err': e})

@api_view(['GET'])
def export(request):
    year = request.GET["year"]
    ppmp_items = get_ppmp_items(year)
    df = pd.DataFrame(columns=[ #create columsn
        "General Description",
        "Unit of Measure",
        "Quantity",
        "Unit Price",
        "Total Amount"
    ])

    for item in ppmp_items.data:
        df.loc[len(df)] = [ #create next row
            item["ItemName"],
            item["UnitName"],
            item["PlannedQuantity"],
            item["PricePerUnit"],
            item["PlannedQuantity"] * item["PricePerUnit"]
        ]

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") #create response with file format
    response["Content-Disposition"] = 'attachment; filename="ppmp.xlsx"' #make file downloadable
    df.to_excel(response, index=False) #put file in the response

    return response


@api_view(['GET'])
def fiscal_years(request):
    response = private_supabase.table("FISCAL_YEAR").select("Year").execute()
    return Response(response.data)

@api_view(['POST'])
def dashboard_cards(request):
    year = request.POST["year"]
    fiscal_year = private_supabase.table("FISCAL_YEAR").select("*").eq("Year", year).single().execute()
    total_annual_budget = fiscal_year.data["TotalABC"]
    ppmp_items = get_ppmp_items(year)
    item_ids = list({
        item["ItemID"]
        for item in ppmp_items.data
        if item["ItemID"] is not None
    })
    purchase_requests = private_supabase.table("PURCHASE_REQUEST").select("*").in_("ItemID", item_ids).execute()
    committed_funds = 0
    requested_funds = 0
    available_lieu_pool_funds = 0
    arrived_funds = 0 # lapa
    pending_in_lieu_count = 0 #lapa
    for purchase_request in purchase_requests.data:
        purchase_request_item = private_supabase.table("PPMP_ITEM").select("*").eq("ItemID", purchase_request["ItemID"]).eq("FiscalYearID", fiscal_year.data["FiscalYearID"]).single().execute()
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

@api_view(['POST'])
def masterlist_data(request):
    year = request.POST["year"]
    fiscal_year_id = private_supabase.table("FISCAL_YEAR").select("FiscalYearID").eq("Year", year).single().execute()
    if fiscal_year_id is None:
        return Response({"error": "year not found"}, status=404)
    response = private_supabase.table("PPMP_ITEM").select("*").eq("FiscalYearID", fiscal_year_id.data["FiscalYearID"]).execute()
    # return Response({"error": fiscal_year_id.data["FiscalYearID"]}, status=404)
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
def masterlist_cards(request):
    year = request.POST["year"]
    ppmp_items = get_ppmp_items(year)

    total_planned_item_count, total_available_item_count, total_pending_item_count, total_fulfilled_item_count = get_headers(ppmp_items)
    total_planned_funds = 0

    for ppmp_item in ppmp_items.data:
        total_planned_funds += ppmp_item["PlannedQuantity"] * ppmp_item["PricePerUnit"]

    return Response({"totalPlannedItemCount": total_planned_item_count,
                     "totalAvailableItemCount": total_available_item_count,
                     "totalPendingItemCount": total_pending_item_count,
                     "totalFulfilledItemCount": total_fulfilled_item_count,
                     "totalPlannedFunds": total_planned_funds,
                     })

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


@api_view(['POST'])
def procurement_cards(request):
    year = request.POST["year"]
    ppmp_items = get_ppmp_items(year)

    total_planned_item_count, total_available_item_count, total_pending_item_count, total_fulfilled_item_count = get_headers(ppmp_items)

    return Response({"totalPlannedItemCount": total_planned_item_count,
                     "totalAvailableItemCount": total_available_item_count,
                     "totalPendingItemCount": total_pending_item_count,
                     "totalFulfilledItemCount": total_fulfilled_item_count,
                     })


@api_view(['POST'])
def procurement_data(request):
    year = request.POST["year"]
    ppmp_items = get_ppmp_items(year)
    total_planned_item_count, total_available_item_count, total_pending_item_count, total_fulfilled_item_count = get_headers(ppmp_items)
    item_ids = list({
        item["ItemID"]
        for item in ppmp_items.data
        if item["ItemID"] is not None
    })
    purchase_requests = private_supabase.table("PURCHASE_REQUEST").select("*").in_("ItemID", item_ids).execute()
    pr_map = {}
    for pr in purchase_requests.data:
        pr_map.setdefault(pr["ItemID"], []).append(pr) #creates a dict where the key is itemid

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
            "prHistory": [
                {
                    "prId": pr["PurchaseRequestID"],
                    "quantity": pr["RequestQuantity"],
                    "specifications": pr["Specifications"],
                    "status": pr["Status"],
                    "dateRequested": pr["created_at"],
                    "dateFulfilled": pr.get("DateFulfilled"),
                }
                for pr in pr_map.get(item["ItemID"], []) #append pr if itemid matches
            ],
            "prHistoryCount": len(pr_map.get(item["ItemID"], [])),
        }
        for item in ppmp_items.data
    ]
    return Response({"totalPlannedItemCount": total_planned_item_count,
                     "totalAvailableItemCount": total_available_item_count,
                     "totalPendingItemCount": total_pending_item_count,
                     "totalFulfilledItemCount": total_fulfilled_item_count,
                     "ppmpMonitoringData": data
                     })

@api_view(["PUT"])
def update_purchase_request_status(request):
    pr_id = request.data["prId"]
    status = request.data["status"]
    try:
        response = private_supabase.table("PURCHASE_REQUEST").select("*").eq("PurchaseRequestID", pr_id).execute()
        if not response.data:
            return Response({"status": "PurchaseRequest does not exist"}, status=404)
        private_supabase.table("PURCHASE_REQUEST").update({"Status": status}).eq("PurchaseRequestID", pr_id).execute()
    except Exception as e:
        return Response({"error": str(e)})
    return Response({"status": "success"}, status=200)
