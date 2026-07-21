from datetime import datetime
import json

from django.http import HttpResponse
from postgrest import APIError
from rest_framework.response import Response
from rest_framework.decorators import api_view
import pandas as pd
from .utils import private_supabase, get_user
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

def get_available_lieu_pool_funds(ppmp_items):
    available_lieu_pool_funds = 0
    for ppmp_item in ppmp_items.data:
        available_lieu_pool_funds += ppmp_item["PlannedQuantity"] * ppmp_item["PricePerUnit"]
    return available_lieu_pool_funds

def get_year_str(fiscal_year_id):
    fiscal_year = private_supabase.table("FISCAL_YEAR").select("Year").eq("FiscalYearID", fiscal_year_id).single().execute()
    return fiscal_year.data["Year"]

def get_headers(ppmp_items):
    total_planned_item_count = 0
    total_available_item_count = 0
    total_pending_item_count = 0
    total_fulfilled_item_count = 0

    for ppmp_item in ppmp_items.data:
        total_planned_item_count += ppmp_item["PlannedQuantity"]
        total_available_item_count += ppmp_item["AvailableQuantity"]
        total_pending_item_count += ppmp_item["PendingQuantity"]
        total_fulfilled_item_count += ppmp_item["FulfilledQuantity"]

    return total_planned_item_count, total_available_item_count, total_pending_item_count, total_fulfilled_item_count

def create_procurement_log(entity_type, action_type, fiscal_year, user_fullname,
    item_name1,
    value=None,
    quantity1=None,
):
    action_type = action_type.lower()
    description = ""
    if entity_type == "PPMP":
        if action_type == "upload":
            description = f"PPMP list for Fiscal Year {fiscal_year} uploaded"
        elif action_type == "export":
            description = f"PPMP list for Fiscal Year {fiscal_year} exported"
    elif entity_type == "Purchase Request":
        if action_type == "requested":
            description = f"Purchase request of {quantity1} {item_name1} is requested"
        if action_type == "rejected":
            description = f"Purchase request of {quantity1} {item_name1} is rejected"
        if action_type == "fulfilled":
            description = f"Purchase request of {quantity1} {item_name1} has been fulfilled"
        if action_type == "cancel":
            description = f"Purchase request of {quantity1} {item_name1} is cancelled"
    elif entity_type == "In Lieu":
        if action_type == "reallocate_reduce":
            description = f"{quantity1} {item_name1} reduced through In Lieu request"
            action_type = "reallocate"
        if action_type == "reallocate_add":
            description = f"{quantity1} {item_name1} requested through In Lieu request"
            action_type = "reallocate"
        if action_type == "approved_reduce":
            description = f"{quantity1} {item_name1} reduced through In Lieu request approval"
            action_type = "approved"
        if action_type == "approved_add":
            description = f"{quantity1} {item_name1} requested through In Lieu request approval"
            action_type = "approved"
        if action_type == "rejected_reduce":
            description = f"{quantity1} {item_name1} added back in through In Lieu request rejection"
            action_type = "rejected"
        if action_type == "rejected_add":
            description = f"{quantity1} {item_name1} reduced through In Lieu request rejection"
            action_type = "rejected"
    print("Description "+ description)
    response = private_supabase.table("PROCUREMENT_LOG").insert({
        "EntityType": entity_type,
        "ActionType": action_type,
        "Price": value,
        "PerformedBy": user_fullname,
        "FiscalYear": fiscal_year,
        "Description": description,
        "ItemName": item_name1
    }).execute()
    return response is not None

def update_pr_status(status, item_id, quantity):
    response = ''
    if status == "fulfilled":
        pending_quantity = int(get_item_detail(item_id, "PendingQuantity"))
        fulfilled_quantity = int(get_item_detail(item_id, "FulfilledQuantity"))
        response = private_supabase.table("PPMP_ITEM").update({
            "PendingQuantity": pending_quantity - quantity,
            "FulfilledQuantity": fulfilled_quantity + quantity
        }).eq("ItemID", item_id).execute()
    elif status == "cancelled":
        pending_quantity = int(get_item_detail(item_id, "PendingQuantity"))
        available_quantity = int(get_item_detail(item_id, "AvailableQuantity"))
        response = private_supabase.table("PPMP_ITEM").update({
            "PendingQuantity": pending_quantity - quantity,
            "AvailableQuantity": available_quantity + quantity
        }).eq("ItemID", item_id).execute()
    return response is not None


@api_view(['POST'])
def get_ppmp_preview(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    excel_file = request.FILES["file"]
    row_start = int(request.POST["startRow"])
    name_column = int(request.POST["itemName"])
    unit_column = int(request.POST["unit"])
    quantity_column = int(request.POST["quantity"])
    price_per_unit_column = int(request.POST["unitPrice"])
    total_abc = request.POST.get("totalABC")
    year = request.POST.get("year")
    try:
        df, grand_total_amount, exists = testingPPMP(
            excel_file,
            row_start,
            name_column,
            unit_column,
            quantity_column,
            price_per_unit_column,
            year,
        )
    except ValueError as e:
        return Response(
            {"errors": e.args[0]},
            status=400,
        )
    print(grand_total_amount)
    if float(total_abc) < grand_total_amount:
        return Response(
            {
                "errors": {
                    "message": "Total ABC is less than grand total"
                }
            },
            status=400,
        )
    # e = upload_excel(df)
    return Response({"data": df.head().to_dict(orient="records"), 'name': name_column, 'unit': unit_column, 'quantity': quantity_column, 'price': price_per_unit_column, 'exists': exists})


@api_view(['POST'])
def upload(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
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
    create_procurement_log("PPMP", "upload", year, user["FullName"])
    return Response({"status": True, 'err': e})

@api_view(['POST'])
def export(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    year = request.POST["year"]
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
    create_procurement_log("PPMP", "export", year, user["FullName"], "")
    return response


@api_view(['GET'])
def fiscal_years(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "Invalid token"}, status=401)
    response = private_supabase.table("FISCAL_YEAR").select("Year").execute()
    return Response(response.data)

@api_view(['POST'])
def dashboard_cards(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "Invalid token"}, status=401)
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
    available_lieu_pool_funds = get_available_lieu_pool_funds(ppmp_items)
    open_funds = total_annual_budget - available_lieu_pool_funds
    logs = private_supabase.table("PROCUREMENT_LOG").select("*").execute()
    logs = [
        {
            "actionType": log["ActionType"].capitalize(),
            "description": log["Description"],
            "date": log["created_at"],
            "value": log["Price"],
            "userFullName": log["PerformedBy"],
            "fiscalYear": log["FiscalYear"],
        }
        for log in logs.data
    ]
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
    user = get_user(request)
    if user is None:
        return Response({"error": "Invalid token"}, status=401)
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
            "fulfilledQuantity": item["FulfilledQuantity"],
            "priceCatalog": item["PricePerUnit"],
        }
        for item in response.data
    ]

    return Response(data)

@api_view(['POST'])
def masterlist_cards(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "Invalid token"}, status=401)
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
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    item_id = int(request.POST["item_id"])
    user_id = request.POST["user_id"]
    specifications = request.POST["specifications"]
    request_quantity = int(request.POST["request_quantity"])
    status = "Pending"
    available_quantity = int(get_item_detail(item_id, "AvailableQuantity"))
    pending_quantity = int(get_item_detail(item_id, "PendingQuantity"))
    price_per_unit = int(get_item_detail(item_id, "PricePerUnit"))
    item_name = get_item_detail(item_id, "ItemName")
    fiscal_year_id = int(get_item_detail(item_id, "FiscalYearID"))
    value = price_per_unit * request_quantity
    year = get_year_str(fiscal_year_id)
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
    response = create_procurement_log("Purchase Request", "requested", year, user["FullName"], value=value, quantity1=request_quantity, item_name1=item_name)
    if response == True:
        return Response({"status": "success"})
    else:
        return Response({"status": "fail"})


@api_view(['PUT'])
def update_purchase_request_status(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    pr_id = request.data["prId"]
    status = request.data["status"]
    status = status.lower()
    try:
        purchase_request = private_supabase.table("PURCHASE_REQUEST").select("*").eq("PurchaseRequestID", pr_id).single().execute()
        purchase_request = purchase_request.data
        item_id = int(purchase_request["ItemID"])
        ppmp_item = get_item(purchase_request["ItemID"])
        fiscal_year_id = int(get_item_detail(ppmp_item["ItemID"], "FiscalYearID"))
        year = get_year_str(fiscal_year_id)
        item_name = get_item_detail(ppmp_item["ItemID"], "ItemName")
        price_per_unit = int(get_item_detail(ppmp_item["ItemID"], "PricePerUnit"))
        request_quantity = purchase_request["RequestQuantity"]
        value = purchase_request["RequestQuantity"] * price_per_unit
        if not purchase_request:
            return Response({"status": "PurchaseRequest does not exist"}, status=404)
        private_supabase.table("PURCHASE_REQUEST").update({"Status": status.capitalize()}).eq("PurchaseRequestID", pr_id).execute()
        update_pr_status(status, item_id, request_quantity)
        response = create_procurement_log("Purchase Request", status.lower(), year, user["FullName"],
                                          value=value, quantity1=request_quantity, item_name1=item_name)

    except Exception as e:
        return Response({"error": str(e)})
    if response is not None:
        return Response({"status": "success"}, status=200)
    else:
        return Response({"status": "fail"}, status=400)

@api_view(['POST'])
def procurement_cards(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "Invalid token"}, status=401)
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
    user = get_user(request)
    if user is None:
        return Response({"error": "Invalid token"}, status=401)
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
    user_ids = list({
        pr["UserID"]
        for pr in purchase_requests.data
        if pr["UserID"] is not None
    })
    users = private_supabase.table("USER").select("UserID, FullName").in_("UserID", user_ids).execute()
    user_lookup = {
        user["UserID"]: user["FullName"]
        for user in users.data
    }

    data = [
        {
            "itemId": item["ItemID"],
            "itemName": item["ItemName"],
            "unitMeasurement": item["UnitName"],
            "plannedQuantity": item["PlannedQuantity"],
            "availableQuantity": item["AvailableQuantity"],
            "pendingQuantity": item["PendingQuantity"],
            "fulfilledQuantity": item["FulfilledQuantity"],
            "priceCatalog": item["PricePerUnit"],
            "prHistory": [
                {
                    "prId": pr["PurchaseRequestID"],
                    "quantity": pr["RequestQuantity"],
                    "specifications": pr["Specifications"],
                    "status": pr["Status"],
                    "requestedBy": user_lookup.get(pr["UserID"]),
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

@api_view(['POST'])
def get_in_lieu_data(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    user_fullname = user["FullName"]
    year = request.POST["year"]
    fiscal_year = private_supabase.table("FISCAL_YEAR").select("*").eq("Year", year).single().execute()
    total_abc = fiscal_year.data["TotalABC"]
    ppmp_items = get_ppmp_items(year)
    open_funds = total_abc - get_available_lieu_pool_funds(ppmp_items)
    ppmp_reallocation_data = [{
        "itemId": ppmp_item["ItemID"],
        "itemName": ppmp_item["ItemName"],
        "unitMeasurement": ppmp_item["UnitName"],
        "plannedQuantity": ppmp_item["PlannedQuantity"],
        "availableQuantity": ppmp_item["AvailableQuantity"],
        "pendingQuantity": ppmp_item["PendingQuantity"],
        "fulfilledQuantity": ppmp_item["FulfilledQuantity"],
        "priceCatalog": ppmp_item["PricePerUnit"],
    }for ppmp_item in ppmp_items.data]
    return Response({
        "userFullName": user_fullname,
        "openFunds": open_funds,
        "ppmpReallocationData": ppmp_reallocation_data
    }, status=200)


@api_view(["POST"])
def create_in_lieu_request(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)

    payload = json.loads(request.POST.get("payload"))
    in_lieu_items = payload["itemsToReduce"]
    in_lieu_addition = payload["itemsToProcure"]
    open_funds_utilized = payload["openFundsUtilized"]
    budget_impact = payload["requiredBudget"]
    status = "Pending"
    user_id = user["UserID"]
    fiscal_year_id = 0
    if len(in_lieu_items) > 0:
        ppmp_item_id = in_lieu_items[0]["itemId"]
        ppmp_item = private_supabase.table("PPMP_ITEM").select("FiscalYearID").eq("ItemID", ppmp_item_id).single().execute()
        fiscal_year_id = ppmp_item.data["FiscalYearID"]
    else:
        current_year = datetime.now().year
        fiscal_year = private_supabase.table("FISCAL_YEAR").select("FiscalYearID").eq("Year", current_year).single().execute()
        if not fiscal_year.data:
            return Response({"error": "Fiscal year missing"}, status=401)
        fiscal_year_id = fiscal_year.data["FiscalYearID"]
    response = private_supabase.table("IN_LIEU").insert({
        "BudgetImpact": budget_impact,
        "Status": status,
        "UserID": user_id,
        "OpenFundsUtilized": open_funds_utilized,
        "FiscalYearID": fiscal_year_id,
    }).execute()
    if not response.data:
        return Response({"error": "Error inserting In Lieu"}, status=401)
    in_lieu_id = response.data[0]["InLieuID"]

    if len(in_lieu_items) > 0:
        insert_in_lieu_items = [{ # parang finormat ko lang para madali i-insert
            "QuantityReduced": in_lieu_item["reduceQuantity"],
            "ItemID": in_lieu_item["itemId"],
            "InLieuID": in_lieu_id,
        }for in_lieu_item in in_lieu_items]

    new_items_list = [item for item in in_lieu_addition if item["added"]]
    new_items = []
    if len(new_items_list) > 0:
        new_items = [{
            "ItemName": item["name"],
            "UnitName": item["measurementUnit"],
            "PricePerUnit": item["unitPrice"],
            "PlannedQuantity": item["quantity"],
            "AvailableQuantity": 0,
            "PendingQuantity": 0,
            "FulfilledQuantity": 0,
            "FiscalYearID": fiscal_year_id,
        }for item in new_items_list]
        # response = private_supabase.table("PPMP_ITEM").insert(new_items).execute()
        # if not response.data:
        #     return Response({"error": "Error inserting PPMP item "}, status=401)
        # inserted_items = response.data
        # print(inserted_items)
        # pairs the original_item to new_items_list and inserted_item to inserted_items
        # parang for each pero dalawa
        #gagana lang daw pag same dictionary
        # for original_item, inserted_item in zip(new_items_list, inserted_items):
        #     original_item["itemId"] = inserted_item["ItemID"]
        # print("new_items_list:", new_items_list)
        # print("in_lieu_addition:", in_lieu_addition)
        # di pala muna dapat ma insert

    insert_in_lieu_addition = [{
        "ItemName": item["name"],
        "UnitName": item["measurementUnit"],
        "UnitPrice": item["unitPrice"],
        "Quantity": item["quantity"],
        "InLieuID": in_lieu_id,
        "ItemID": item["itemId"] if not item["added"] else None,
    }for item in in_lieu_addition]
    if len(insert_in_lieu_addition) > 0:
        response = private_supabase.table("IN_LIEU_ADDITION").insert(insert_in_lieu_addition).execute()
        print(insert_in_lieu_addition)
        if not response.data:
            return Response({"error": "Error inserting In Lieu Items"}, status=401)
    if len(in_lieu_items) > 0:
        response = private_supabase.table("IN_LIEU_ITEM").insert(insert_in_lieu_items).execute()
        if not response.data:
            return Response({"error": "Error inserting In Lieu Items"}, status=401)
    year = get_year_str(fiscal_year_id)
    for reduced in in_lieu_items: # in_lieu_items para may name
        create_procurement_log(
            "In Lieu",
            "reallocate_reduce",
            year,
            user["FullName"],
            item_name1=reduced["itemName"],
            quantity1=reduced["reduceQuantity"],
            value=budget_impact
        )
    for added in insert_in_lieu_addition:
        create_procurement_log(
            "In Lieu",
            "reallocate_add",
            year,
            user["FullName"],
            item_name1=added["ItemName"],
            quantity1=added["Quantity"],
            value=budget_impact
        )
    return Response({"stats": "success", "item_id": in_lieu_id, "new": new_items,
                     "ppmp in lieu items": insert_in_lieu_items if len(in_lieu_items) > 0 else []})


@api_view(['POST'])
def get_in_lieu_approvals(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "Invalid token"}, status=401)
    year = request.POST["year"]
    fiscal_year_id = private_supabase.table("FISCAL_YEAR").select("FiscalYearID").eq("Year", year).single().execute()
    fiscal_year_id = fiscal_year_id.data["FiscalYearID"]
    role = user["Role"]
    in_lieus = private_supabase.table("IN_LIEU").select("*").eq("FiscalYearID", fiscal_year_id).execute()
    in_lieu_ids = list({
        in_lieu["InLieuID"]
        for in_lieu in in_lieus.data
        if in_lieu["InLieuID"] is not None
    })
    in_lieu_additions = private_supabase.table("IN_LIEU_ADDITION").select("*").in_("InLieuID", in_lieu_ids).execute()
    in_lieu_items = private_supabase.table("IN_LIEU_ITEM").select("*").in_("InLieuID", in_lieu_ids).execute()
    additions_map = {}
    for addition in in_lieu_additions.data:
        additions_map.setdefault(addition["InLieuID"], []).append(addition) # creates a dict where the key is inlieuid
    in_lieu_items_map = {}
    for in_lieu_item in in_lieu_items.data:
        in_lieu_items_map.setdefault(in_lieu_item["InLieuID"], []).append(in_lieu_item)
    in_lieu_item_ids = list({  # get all ids from in_lieu_items
        in_lieu["ItemID"]
        for in_lieu in in_lieu_items.data
        if in_lieu["ItemID"] is not None
    })
    in_lieu_items_ppmp = private_supabase.table("PPMP_ITEM").select("*").in_("ItemID", in_lieu_item_ids).execute()
    in_lieu_items_ppmp_map = {}
    for in_lieu_item in in_lieu_items_ppmp.data:
        in_lieu_items_ppmp_map.setdefault(in_lieu_item["ItemID"], []).append(in_lieu_item)
    ppmp_lookup = {
        item["ItemID"]: item
        for item in in_lieu_items_ppmp.data
    }
    user_ids = list({ # get all users with inlieu requests
        in_lieu["UserID"]
        for in_lieu in in_lieus.data
        if in_lieu["UserID"] is not None
    })
    users = private_supabase.table("USER").select("UserID, FullName").in_("UserID", user_ids).execute()
    user_lookup = { # creates a dict where the key is UserID
        user["UserID"]: user["FullName"]
        for user in users.data
    }
    in_lieu_approval_data = [
            {
                "inLieuId": in_lieu["InLieuID"],
                "requestDate": in_lieu["created_at"],
                "requestedBy": user_lookup.get(in_lieu["UserID"]),
                "openFundsUtilized": in_lieu["OpenFundsUtilized"],
                "inLieuAdditionItems": [
                    {
                        "itemId": in_lieu_addition["ItemID"],
                        "quantity": in_lieu_addition["Quantity"],
                        "itemName": in_lieu_addition["ItemName"],
                        "unitMeasurement": in_lieu_addition["UnitName"],
                        "priceCatalog": in_lieu_addition["UnitPrice"],
                    }
                    for in_lieu_addition in additions_map.get(in_lieu["InLieuID"], [])
                ],
                "inLieuReducedItems": [
                    {
                        "itemId": in_lieu_item["ItemID"],
                        "quantity": in_lieu_item["QuantityReduced"],  # IN_LIEU_ITEM
                        "itemName": ppmp_lookup[in_lieu_item["ItemID"]]["ItemName"],
                        "unitMeasurement": ppmp_lookup[in_lieu_item["ItemID"]]["UnitName"],
                        "priceCatalog": ppmp_lookup[in_lieu_item["ItemID"]]["PricePerUnit"],
                        "plannedQuantity": ppmp_lookup[in_lieu_item["ItemID"]]["PlannedQuantity"],
                        "availableQuantityAfter": ppmp_lookup[in_lieu_item["ItemID"]]["AvailableQuantity"] - in_lieu_item["QuantityReduced"],
                    }
                    for in_lieu_item in in_lieu_items_map.get(in_lieu["InLieuID"], [])
                ],
                "budgetImpact": in_lieu["BudgetImpact"],
                "status": in_lieu["Status"],
            }
        for in_lieu in in_lieus.data
        ]
    return Response({"userRole": role, "inLieuApprovalData": in_lieu_approval_data}, status=200)

@api_view(['PUT'])
def update_in_lieu_status(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)

    in_lieu_id = request.POST.get("inLieuId")
    status = request.POST.get("status")

    if status == "Rejected":
        try:
            in_lieu = private_supabase.table("IN_LIEU").select("*").eq("InLieuID", in_lieu_id).single().execute()
            response = private_supabase.table("IN_LIEU").update({"Status": status}).eq("InLieuID", in_lieu_id).execute()
            if response is None:
                return Response({"error": "Error updating in lieu request", "InLieuID": in_lieu_id}, status=500)
            return Response({"status": "success"}, status=200)
        except APIError:
            return Response({"error": "InLieu not found", "InLieuID": in_lieu_id}, status=404)
    else:
        try:
            in_lieu = private_supabase.table("IN_LIEU").select("*").eq("InLieuID", in_lieu_id).single().execute()
            in_lieu_items = private_supabase.table("IN_LIEU_ITEM").select("*").eq("InLieuID", in_lieu_id).execute()
            in_lieu_additions = private_supabase.table("IN_LIEU_ADDITION").select("*").eq("InLieuID", in_lieu_id).execute()
        except APIError:
            return Response({"error": "InLieu not found", "InLieuID": in_lieu_id}, status=404)
        in_lieu = in_lieu.data
        in_lieu_items = in_lieu_items.data
        in_lieu_additions = in_lieu_additions.data
        in_lieu_item_ids = [in_lieu_item["ItemID"] for in_lieu_item in in_lieu_items]
        in_lieu_additions_without_id = [in_lieu_addition for in_lieu_addition in in_lieu_additions if not in_lieu_addition["ItemID"]]
        in_lieu_additions_with_id = [in_lieu_addition for in_lieu_addition in in_lieu_additions if in_lieu_addition["ItemID"]]
        for in_lieu_addition in in_lieu_additions:
            if in_lieu_addition["ItemID"]:
                in_lieu_additions_with_id.setdefault(
                    in_lieu_addition["ItemID"], []
                ).append(in_lieu_addition)

        if len(in_lieu_items) > 0:
            ppmp_item_id = in_lieu_items[0]["itemId"]
            ppmp_item = private_supabase.table("PPMP_ITEM").select("FiscalYearID").eq("ItemID", ppmp_item_id).single().execute()
            fiscal_year_id = ppmp_item.data["FiscalYearID"]
        else:
            current_year = datetime.now().year
            fiscal_year = private_supabase.table("FISCAL_YEAR").select("FiscalYearID").eq("Year",
                                                                                          current_year).single().execute()
            if not fiscal_year.data:
                return Response({"error": "Fiscal year missing"}, status=401)
            fiscal_year_id = fiscal_year.data["FiscalYearID"]

        for in_lieu_addition in in_lieu_additions_without_id:
            response = private_supabase.table("PPMP_ITEM").insert({
                "ItemName": in_lieu_addition["ItemName"],
                "UnitName": in_lieu_addition["UnitName"],
                "PlannedQuantity": int(in_lieu_addition["Quantity"]),
                "AvailableQuantity": int(in_lieu_addition["Quantity"]),
                "PricePerUnit": float(in_lieu_addition["UnitPrice"]),
                "PendingQuantity": 0,
                "FulfilledQuantity": 0,
                "FiscalYearID": fiscal_year_id,
            }).execute()
            in_lieu_addition["ItemID"] = response.data[0]["ItemID"]

        for in_lieu_item_id in in_lieu_item_ids:
            quantity_to_reduce = private_supabase.table("IN_LIEU_ITEM").select("QuantityReduced").eq("InLieuID", in_lieu_item_id).single().execute()
            quantity_to_reduce = quantity_to_reduce.data["QuantityReduced"]
            planned_quantity = get_item_detail(in_lieu_item_id, "PlannedQuantity")
            available_quantity = get_item_detail(in_lieu_item_id, "AvailableQuantityAfter")
            if planned_quantity - quantity_to_reduce < 0 or available_quantity - quantity_to_reduce < 0:
                return Response({"error": "Quantity to reduce is greater than planned quantity or available quantity"})
            private_supabase.table("PPMP_ITEM").update({
                "PlannedQuantity": planned_quantity - quantity_to_reduce,
                "AvailableQuantity": available_quantity - quantity_to_reduce,
            })

        response = private_supabase.table("IN_LIEU").update({"Status": status}).eq("InLieuID", in_lieu_id).execute()
        if response is None:
            return Response({"error": "Error updating in lieu request", "InLieuID": in_lieu_id}, status=500)
        return Response({"status": "success"}, status=200)


@api_view(['POST'])
def get_signatories(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    document_type = request.POST["documentType"]
    if document_type is None:
        return Response({"error": "Document type not found"}, status=401)
    response = private_supabase.table("DOCUMENT_SIGNATORY").select("*").eq("DocumentType", document_type.upper()).execute()
    if response is None:
        return Response({"error": "Document type not found"}, status=401)
    signatories = [{
        "signatoryId": signatory["SignatoryID"],
        "fullName": signatory["FullName"],
        "position": signatory["PositionTitle"],
    }for signatory in response.data]
    return Response({"signatories": signatories}, status=200)
