import json

import joblib
from ortools.sat.python import cp_model
from postgrest import APIError
from rest_framework.response import Response
from rest_framework.decorators import api_view
from datetime import datetime

from ml import reverse_knapsack, test
from user.views import get_admin
from .utils import private_supabase, get_user, check_fields, get_ppmp_items
from excel import testingPPMP, upload_excel, export_formatted_excel
from smart_suggest.ml_suggestion import MLSuggest

def get_item_categories():
    response = private_supabase.rpc("get_item_categories").execute()
    return response.data

def get_ppmp_categories():
    response = private_supabase.rpc("get_ppmp_categories").execute()
    return response.data

def get_item(item_id):
    response = private_supabase.table("PPMP_ITEM").select("*").eq("ItemID", item_id).single().execute()
    return response.data

def get_item_detail(item_id, column_name):
    response = private_supabase.table("PPMP_ITEM").select(column_name).eq("ItemID", item_id).single().execute()
    return response.data[column_name]

def get_available_lieu_pool_funds(ppmp_items):
    available_lieu_pool_funds = 0
    for ppmp_item in ppmp_items.data:
        available_lieu_pool_funds += ppmp_item["AvailableQuantity"] * ppmp_item["PricePerUnit"]
    return available_lieu_pool_funds

def get_open_funds(ppmp_items):
    open_funds = 0
    for ppmp_item in ppmp_items.data:
        open_funds += ppmp_item["PlannedQuantity"] * ppmp_item["PricePerUnit"]
    return open_funds

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
            description = f"{quantity1} {item_name1} added through In Lieu request approval"
            action_type = "approved"
        if action_type == "rejected_reduce":
            description = f"Reduction of {quantity1} {item_name1} is rejected through In Lieu request rejection"
            action_type = "rejected"
        if action_type == "rejected_add":
            description = f"Addition of {quantity1} {item_name1} is rejected through In Lieu request rejection"
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

def insert_filtered_aggregate_data(data):
    response = private_supabase.table("AGGREGATE_PPMP_ITEM").insert([
        {"ItemID": r["ItemID"],
         "created_at": r["created_at"],
         "ItemName": r["ItemName"],
         "UnitName": r["UnitName"],
         "PricePerUnit": r["PricePerUnit"],
         "PlannedQuantity": r["PlannedQuantity"],
         "AvailableQuantity": r["AvailableQuantity"],
         "PendingQuantity": r["PendingQuantity"],
         "FulfilledQuantity": r["FulfilledQuantity"],
         "FiscalYearID": r["FiscalYearID"],
         "ItemCategory": r["ItemCategory"],
         "PpmpCategory": r["PpmpCategory"],
         "Occurrence": r["Occurrence"],
         "QuantityReduced": r["QuantityReduced"],
         "PriceScore": r["PriceScore"],
         "FrequentScore": r["FrequentScore"],
         "StaleScore": r["StaleScore"],
         "YearlyStaleScore": r["YearlyStaleScore"],
         "FinalScore": r["FinalScore"],
         "PriceDifference": r["PriceDifference"],
         "InLieuDate": r["InLieuDate"]} for _, r in data
        ]).execute()
    return response is not None

def score_aggregate_data(df, total_price):
    def parse_inlieu_date(date):
        return dateparser.parse(date) if type(date) is str else ""

    now_date = datetime.now()
    min_date = parse_inlieu_date(df["InLieuDate"].min())
    max_date = parse_inlieu_date(df["InLieuDate"].max())

    weights = {
        "frequency": .4,
        "price": .3,
        "staleness": .2,
        "yearly_staleness": .1
    }

    df["PriceDifference"] = (df["PricePerUnit"] * df["AvailableQuantity"] - total_price) / total_price
    df["PriceScore"] = (df["PriceDifference"] - df["PriceDifference"].min()) / (df["PriceDifference"].max() - df["PriceDifference"].min())
    df["FrequentScore"] = (df["Occurrence"].min() * df["QuantityReduced"].min()) / (df["Occurrence"].max() * df["QuantityReduced"].max())
    df["StaleScore"] = min((now_date.year - min_date.year) / max_date.year, 1)

    for _, row in df.iterrows():
        row_date = parse_inlieu_date(row["InLieuDate"])
        row_year = row_date if row_date == "" else row_date.year

        row["YearlyStaleScore"] = min(((now_date.timestamp() - min_date.timestamp() / max_date.timestamp())) if row_year == now_date.year else 0, 1)

    df["FinalScore"] = df["PriceScore"] * weights['price'] + df["FrequentScore"] * weights["frequency"] + df["StaleScore"] * weights['staleness'] + df["YearlyStaleScore"] * weights['yearly_staleness']
    df["Efficiency"] = df["FinalScore"] / df["PricePerUnit"].median()

    new_df = df.sort_values("Efficiency", ascending=False, inplace=False)

    return new_df

def select_minimum_items(df, total_price):
    df = df.copy()
    df["StockValue"] = df["PricePerUnit"] * df["AvailableQuantity"]
    df["CumStockValue"] = df["StockValue"].cumsum()

    if df["StockValue"].sum() < total_price:
        return None

    cutoff_idx = df[df["CumStockValue"] >= total_price].index[0]
    return df.loc[:cutoff_idx]

def ml_learn_from_decision(supabase, fiscal_year, items):
    try:
        budget = sum(
            float(item.get("reduceQuantity", 0) or 0) * float(item.get("priceCatalog", 0) or 0)
            for item in items
        )
        if budget > 0:
            ml = MLSuggest(supabase, fiscal_year)
            ml.learn_from_decision(items, budget)
            ml.clear_last_recommendation()
    except Exception as e:
        print(f"ML feedback failed: {e}")
        
def ml_learn_from_rejection(supabase, fiscal_year, budget=None, items=None):
    try:
        if budget is None and items is not None:
            budget = sum(
                float(item.get("reduceQuantity", 0) or 0) * float(item.get("priceCatalog", 0) or 0)
                for item in items
            )
        elif items is None:
            print("No budget to learn from")
            return 
        
        if budget > 0:
            ml = MLSuggest(supabase, fiscal_year)
            previous = ml.load_last_recommendation()
            
            if previous and previous.get("items"):
                ml.learn_from_rejection(items, budget)
                
            return ml
    except Exception as e:
        print(f"ML feedback failed: {e}")

@api_view(['POST'])
def get_inlieu_suggestions(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)

    budget = float(request.POST["Sum"])
    fiscal_year = request.POST["FiscalYear"]

    ml = ml_learn_from_rejection(private_supabase, fiscal_year, budget)
    
    if ml is None:
        ml = MLSuggest(private_supabase, fiscal_year)
        
    try:
        res = ml.recommend(budget)
    except Exception as e:
        return Response({
            "error": str(e),
        }, status=400)

    ml.save_last_recommendation(res, budget)

    result = [{
        "itemId": getattr(res, "ItemID"),
        "itemName": getattr(res, "ItemName"),
        "unitMeasurement": getattr(res, "UnitName"),
        "reduceQuantity": getattr(res, "Quantity"),
        "priceCatalog": getattr(res, "PricePerUnit"),
    } for res in res.itertuples()]
    
    return Response(data={"data": result}, status=200)

@api_view(['POST'])
def get_ppmp_preview(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    required_fields = ["isDualMode", "file", "totalABC", "startRow", "itemName", "year", "unit", "quantity", "unitPrice"]
    missing_fields = check_fields(required_fields, request)
    try:
        if missing_fields:
            return Response({"error": "Missing fields", "missingFields": missing_fields}, status=400)
    except Exception as e:
        return Response({"error": "Invalid fields"}, status=400)
    isDualMode = request.POST.get("isDualMode") == "true"
    excel_file = request.FILES["file"]
    total_abc = request.POST.get("totalABC")
    row_start = int(request.POST["startRow"])
    name_column = int(request.POST["itemName"])
    year = (request.POST["year"])
    unit_column = int(request.POST["unit"])
    quantity_column = int(request.POST["quantity"])
    price_per_unit_column = int(request.POST["unitPrice"])
    excel_file2 = None
    if isDualMode is True:
        excel_file2 = request.FILES["file2"]
        if excel_file2 is None:
            return Response(
                {"error": "Second PPMP file is required in dual mode"},
                status=400
            )

    df = [None, None]
    grand_total_amount = 0
    exists = False
    try:
        if isDualMode:
            df[0], grand_total_amount1, exists1 = testingPPMP(excel_file, row_start, name_column, unit_column,
                                                              quantity_column, price_per_unit_column, year,
                                                              "Office Supply")
            df[1], grand_total_amount2, exists2 = testingPPMP(excel_file2, row_start, name_column, unit_column,
                                                              quantity_column, price_per_unit_column, year,
                                                              "Laboratory Supply/Equipment")
            grand_total_amount = grand_total_amount1 + grand_total_amount2
            exists = exists1
        else:
            df[0], grand_total_amount, exists = testingPPMP(excel_file, row_start, name_column, unit_column,
                                                         quantity_column, price_per_unit_column, year, "Office Supply")
    except ValueError as e:
        return Response({"error": e.args[0]}, status=400, )
    if float(total_abc) < grand_total_amount:
        return Response({"error": "Total ABC is less than grand total"}, status=400, )
    # e = upload_excel(df[0], grand_total_amount, year, "Office Supply")
    # if isDualMode:
    #     e = upload_excel(df[1], grand_total_amount, year, "Laboratory Supply/Equipment")
    if isDualMode:
        return Response({
            "data": df[0].to_dict(orient="records"),
            "data2": df[1].to_dict(orient="records"),
            "exists": exists
        })
    else:
        return Response({
            "data": df[0].to_dict(orient="records")
        })

@api_view(['POST'])
def upload(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    required_fields = ["isDualMode", "file", "totalABC", "startRow", "itemName", "year", "unit", "quantity", "unitPrice"]
    missing_fields = check_fields(required_fields, request)
    try:
        if missing_fields:
            return Response({"error": "Missing fields", "missingFields": missing_fields}, status=400)
    except Exception as e:
        return Response({"error": "Invalid fields"}, status=400)
    isDualMode = request.POST.get("isDualMode") == "true"
    excel_file = request.FILES["file"]
    total_abc = request.POST.get("totalABC")
    row_start = int(request.POST["startRow"])
    name_column = int(request.POST["itemName"])
    year = (request.POST["year"])
    unit_column = int(request.POST["unit"])
    quantity_column = int(request.POST["quantity"])
    price_per_unit_column = int(request.POST["unitPrice"])
    excel_file2 = None
    if isDualMode:
        excel_file2 = request.FILES["file2"]
        if excel_file2 is None:
            return Response(
                {"error": "Second PPMP file is required in dual mode"},
                status=400
            )
    df = [None, None]
    grand_total_amount = 0
    exists = False
    try:
        if isDualMode:
            df[0], grand_total_amount1, exists1 = testingPPMP(excel_file, row_start, name_column, unit_column, quantity_column, price_per_unit_column, year, "Office Supply")
            df[1], grand_total_amount2, exists2 = testingPPMP(excel_file2, row_start, name_column, unit_column, quantity_column, price_per_unit_column, year, "Laboratory Supply/Equipment")
            grand_total_amount = grand_total_amount1 + grand_total_amount2
            exists = exists1
        else:
            df[0], grand_total_amount, exists = testingPPMP(excel_file, row_start, name_column, unit_column, quantity_column, price_per_unit_column, year, "Office Supply")
    except ValueError as e:
        return Response({"error": e.args[0]}, status=400, )
    if float(total_abc) < grand_total_amount:
        return Response({"error": "Total ABC is less than grand total"}, status=400, )
    e = upload_excel(df[0], total_abc, year, "Office Supply")
    if isDualMode:
        e = upload_excel(df[1], total_abc, year, "Laboratory Supply/Equipment")
    create_procurement_log("PPMP", "upload", year, user["FullName"], "")
    return Response({"status": "success", 'err': e})

@api_view(['POST'])
def export(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    year = request.POST["year"]

    create_procurement_log("PPMP", "export", year, user["FullName"], "")
    return export_formatted_excel(year, get_admin())

@api_view(['GET'])
def fiscal_years(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "Invalid token"}, status=401)
    try:
        response = private_supabase.table("FISCAL_YEAR").select("Year").execute()
    except Exception as e:
        return Response({"error": {e}}, status=400)
    if not response.data:
        return Response({"error": "No years found"}, status=404)
    return Response(response.data)

@api_view(['POST'])
def dashboard_cards(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "Invalid token"}, status=401)
    missing_fields = check_fields(["year"], request)
    try:
        if missing_fields:
            return Response({"error": "Missing fields", "missingFields": missing_fields}, status=400)
    except Exception as e:
        return Response({"error": "Invalid fields"}, status=400)
    year = request.POST["year"]
    fiscal_year = private_supabase.table("FISCAL_YEAR").select("TotalABC", "FiscalYearID").eq("Year", year).single().execute()
    total_annual_budget = fiscal_year.data["TotalABC"]
    ppmp_items = private_supabase.table("PPMP_ITEM").select("ItemID, PlannedQuantity, PendingQuantity, FulfilledQuantity, AvailableQuantity, PricePerUnit").eq('FiscalYearID', fiscal_year.data["FiscalYearID"]).execute()
    item_ids = list({
        item["ItemID"]
        for item in ppmp_items.data
        if item["ItemID"] is not None
    })
    purchase_requests = private_supabase.table("PURCHASE_REQUEST").select("ItemID, RequestQuantity, Status").in_("ItemID", item_ids).execute()
    in_lieus = private_supabase.table("IN_LIEU").select("Status").eq('FiscalYearID', fiscal_year.data["FiscalYearID"]).execute()
    # retry
    # for attempt in range(3):
    #     purchase_requests = (
    #         private_supabase
    #         .table("PURCHASE_REQUEST")
    #         .select("ItemID, RequestQuantity, Status")
    #         .in_("ItemID", item_ids)
    #         .execute()
    #     )
    #
    #     if purchase_requests.data:
    #         break
    #
    #     time.sleep(0.2)
    requested_funds = 0
    arrived_funds = 0
    pending_pr = 0
    pending_in_lieu_count = 0
    ppmp_item_map = {
        item["ItemID"]: item
        for item in ppmp_items.data
    }
    for purchase_request in purchase_requests.data:
        purchase_request_item = ppmp_item_map.get(purchase_request["ItemID"])
        if not purchase_request_item:
            continue
        if purchase_request["Status"] == "Pending":
            requested_funds += purchase_request_item["PricePerUnit"] * purchase_request["RequestQuantity"]
    for in_lieu in in_lieus.data:
        if in_lieu["Status"] == "Pending":
            pending_in_lieu_count += 1

    for ppmp_item in ppmp_items.data:
        pending_pr += ppmp_item["PricePerUnit"] * ppmp_item["PendingQuantity"]
        arrived_funds += ppmp_item["PricePerUnit"] * ppmp_item["FulfilledQuantity"]

    committed_funds = pending_pr + arrived_funds

    available_lieu_pool_funds = get_available_lieu_pool_funds(ppmp_items)
    open_funds = total_annual_budget - get_open_funds(ppmp_items)
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
    missing_fields = check_fields(["year"], request)
    try:
        if missing_fields:
            return Response({"error": "Missing fields", "missingFields": missing_fields}, status=400)
    except Exception as e:
        return Response({"error": "Invalid fields"}, status=400)
    year = request.POST["year"]
    fiscal_year_id = private_supabase.table("FISCAL_YEAR").select("FiscalYearID").eq("Year", year).single().execute()
    if fiscal_year_id is None:
        return Response({"error": "year not found"}, status=404)
    try:
        response = private_supabase.table("PPMP_ITEM").select("*").eq("FiscalYearID", fiscal_year_id.data["FiscalYearID"]).execute()
    except Exception as e:
        return Response({"error": f"Error fetching ppmp items: {str(e)}"}, status=400)
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
            "itemCategory": item["ItemCategory"],
            "ppmpCategory": item["PpmpCategory"],
        }
        for item in response.data
    ]
    item_categories = get_item_categories()
    ppmp_categories = get_ppmp_categories()
    return Response({"ppmpData": data, "itemCategories": item_categories, "ppmpCategories": ppmp_categories})

@api_view(['POST'])
def masterlist_cards(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "Invalid token"}, status=401)
    missing_fields = check_fields(["year"], request)
    try:
        if missing_fields:
            return Response({"error": "Missing fields", "missingFields": missing_fields}, status=400)
    except Exception as e:
        return Response({"error": "Invalid fields"}, status=400)
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
    required_fields = ["item_id", "user_id", "specifications", "request_quantity"]
    missing_fields = check_fields(required_fields, request)
    try:
        if missing_fields:
            return Response({"error": "Missing fields", "missingFields": missing_fields}, status=400)
    except Exception as e:
        return Response({"error": "Invalid fields"}, status=400)
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
        return Response({"error": "Error creating purchase request"}, status=400)


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
        return Response({"status": "Error updating purchase request"}, status=400)

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
        "itemCategory": ppmp_item["ItemCategory"],
        "ppmpCategory": ppmp_item["PpmpCategory"],
    }for ppmp_item in ppmp_items.data]
    item_categories = get_item_categories()
    ppmp_categories = get_ppmp_categories()
    return Response({
        "userFullName": user_fullname,
        "openFunds": open_funds,
        "ppmpReallocationData": ppmp_reallocation_data,
        "itemCategories": item_categories,
        "ppmpCategories": ppmp_categories
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
            "ItemCategory": item["itemCategory"],
            "PpmpCategory": item["ppmpCategory"],
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
        "ItemCategory": item["itemCategory"],
        "PpmpCategory": item["ppmpCategory"],
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

    ml_learn_from_decision(private_supabase, year, in_lieu_items)

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
                        "itemCategory": in_lieu_addition["ItemCategory"],
                        "ppmpCategory": in_lieu_addition["PpmpCategory"]
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
                        "itemCategory": ppmp_lookup[in_lieu_item["ItemID"]]["ItemCategory"],
                        "ppmpCategory": ppmp_lookup[in_lieu_item["ItemID"]]["PpmpCategory"],
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
    budget_impact = 0
    if status == "Rejected":
        return reject_in_lieu(user, in_lieu_id)
    else:
        return approve_in_lieu(user, in_lieu_id)

def reject_in_lieu(user, in_lieu_id):
    budget_impact = 0
    status = "Rejected"
    try:
        in_lieu = private_supabase.table("IN_LIEU").select("*").eq("InLieuID", in_lieu_id).single().execute()
        budget_impact = in_lieu.data["BudgetImpact"]
        in_lieu_items = private_supabase.table("IN_LIEU_ITEM").select("*").eq("InLieuID", in_lieu_id).execute()
        in_lieu_additions = private_supabase.table("IN_LIEU_ADDITION").select("*").eq("InLieuID", in_lieu_id).execute()
        if len(in_lieu_items.data) > 0:
            ppmp_item_id = in_lieu_items.data[0]["ItemID"]
            ppmp_item = private_supabase.table("PPMP_ITEM").select("FiscalYearID").eq("ItemID", ppmp_item_id).single().execute()
            fiscal_year_id = ppmp_item.data["FiscalYearID"]
            fiscal_year = private_supabase.table("FISCAL_YEAR").select("*").eq("FiscalYearID", fiscal_year_id).single().execute()
        else:
            current_year = datetime.now().year
            fiscal_year = private_supabase.table("FISCAL_YEAR").select("*").eq("Year", current_year).single().execute()
            if not fiscal_year.data:
                return Response({"error": "Fiscal year missing"}, status=401)
        response = private_supabase.table("IN_LIEU").update({"Status": status}).eq("InLieuID", in_lieu_id).execute()
        year = fiscal_year.data["Year"]
        status = status.lower()
        for added in in_lieu_additions.data:
            create_procurement_log(
                "In Lieu",
                status + "_add",
                year,
                user["FullName"],
                item_name1=added["ItemName"],
                quantity1=added["Quantity"],
                value=budget_impact
            )

        reduction_map = {item["ItemID"]: item["QuantityReduced"] for item in in_lieu_items.data}
        in_lieu_item_ids = list(reduction_map.keys())

        response = private_supabase.table("PPMP_ITEM").select("ItemID, ItemName").in_("ItemID", in_lieu_item_ids).execute()
        to_reduce_ppmp_items = response.data

        for item in to_reduce_ppmp_items:
            item_id = item["ItemID"]
            item_name = item["ItemName"]
            quantity_reduced = reduction_map.get(item_id)

            create_procurement_log(
                "In Lieu",
                status + "_reduce",
                year,
                user["FullName"],
                item_name1=item_name,
                quantity1=quantity_reduced,
                value=budget_impact
            )
        response = private_supabase.table("IN_LIEU").update({"Status": status}).eq("InLieuID", in_lieu_id).execute()
        if response is None:
            return Response({"error": "Error updating in lieu request", "InLieuID": in_lieu_id}, status=500)
            
        ml_learn_from_rejection(private_supabase, fiscal_year, items=in_lieu_items.data)
        
        return Response({"status": "success"}, status=200)
    except APIError:
        return Response({"error": "InLieu not found", "InLieuID": in_lieu_id}, status=404)

def approve_in_lieu(user, in_lieu_id):
    budget_impact = 0
    status = "Approved"
    try:
        in_lieu = private_supabase.table("IN_LIEU").select("*").eq("InLieuID", in_lieu_id).single().execute()
        in_lieu_items = private_supabase.table("IN_LIEU_ITEM").select("*").eq("InLieuID", in_lieu_id).execute()
        in_lieu_additions = private_supabase.table("IN_LIEU_ADDITION").select("*").eq("InLieuID", in_lieu_id).execute()
    except APIError:
        return Response({"error": "InLieu not found", "InLieuID": in_lieu_id}, status=404)
    in_lieu = in_lieu.data
    budget_impact = in_lieu["BudgetImpact"]
    in_lieu_items = in_lieu_items.data
    in_lieu_additions = in_lieu_additions.data
    in_lieu_additions_without_id = [in_lieu_addition for in_lieu_addition in in_lieu_additions if
                                    not in_lieu_addition["ItemID"]]
    in_lieu_additions_with_id = [in_lieu_addition for in_lieu_addition in in_lieu_additions if
                                 in_lieu_addition["ItemID"]]
    fiscal_year = None
    fiscal_year_id = 0
    if len(in_lieu_items) > 0:
        ppmp_item_id = in_lieu_items[0]["ItemID"]
        ppmp_item = private_supabase.table("PPMP_ITEM").select("FiscalYearID").eq("ItemID", ppmp_item_id).single().execute()
        fiscal_year_id = ppmp_item.data["FiscalYearID"]
        fiscal_year = private_supabase.table("FISCAL_YEAR").select("*").eq("FiscalYearID", fiscal_year_id).single().execute()
    else:
        current_year = datetime.now().year
        fiscal_year = private_supabase.table("FISCAL_YEAR").select("*").eq("Year", current_year).single().execute()
        if not fiscal_year.data:
            return Response({"error": "Fiscal year missing"}, status=401)
        fiscal_year_id = fiscal_year.data["FiscalYearID"]

    in_lieu_item_map = {}
    for in_lieu_item in in_lieu_items:
        quantity_to_reduce = in_lieu_item["QuantityReduced"]
        planned_quantity = get_item_detail(in_lieu_item["ItemID"], "PlannedQuantity")
        available_quantity = get_item_detail(in_lieu_item["ItemID"], "AvailableQuantity")
        if planned_quantity - quantity_to_reduce < 0 or available_quantity - quantity_to_reduce < 0:
            return Response({"error": "Quantity to reduce is greater than planned quantity or available quantity"}, status=400)
        in_lieu_item_map[in_lieu_item["ItemID"]] = {
            "QuantityReduced": quantity_to_reduce,
            "PlannedQuantity": planned_quantity,
            "AvailableQuantity": available_quantity
        }
    for in_lieu_item_id, in_lieu_item_data in in_lieu_item_map.items():
        private_supabase.table("PPMP_ITEM").update({
            "PlannedQuantity": in_lieu_item_data["PlannedQuantity"] - in_lieu_item_data["QuantityReduced"],
            "AvailableQuantity": in_lieu_item_data["AvailableQuantity"] - in_lieu_item_data["QuantityReduced"],
        }).eq("ItemID", in_lieu_item_id).execute()

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
            "ItemCategory": in_lieu_addition["ItemCategory"],
            "PpmpCategory": in_lieu_addition["PpmpCategory"],
        }).execute()
        in_lieu_addition["ItemID"] = response.data[0]["ItemID"]

    for in_lieu_addition_id in in_lieu_additions_with_id:
        quantity_to_add = private_supabase.table("IN_LIEU_ADDITION").select("Quantity").eq("InLieuAdditionID", in_lieu_addition_id["InLieuAdditionID"]).maybe_single().execute()
        if quantity_to_add is None:
            return Response({"error": "Quantity not found"}, status=404)
        quantity_to_add = quantity_to_add.data["Quantity"]
        planned_quantity = get_item_detail(in_lieu_addition_id["ItemID"], "PlannedQuantity")
        available_quantity = get_item_detail(in_lieu_addition_id["ItemID"], "AvailableQuantity")
        private_supabase.table("PPMP_ITEM").update({
            "PlannedQuantity": planned_quantity + quantity_to_add,
            "AvailableQuantity": available_quantity + quantity_to_add,
        }).eq("ItemID", in_lieu_addition_id["ItemID"]).execute()

    year = fiscal_year.data["Year"]
    status = status.lower()
    for added in in_lieu_additions:
        create_procurement_log(
            "In Lieu",
            status + "_add",
            year,
            user["FullName"],
            item_name1=added["ItemName"],
            quantity1=added["Quantity"],
            value=budget_impact
        )


    in_lieu_item_ids = list(in_lieu_item_map.keys())
    response = private_supabase.table("PPMP_ITEM").select("ItemID, ItemName").in_("ItemID", in_lieu_item_ids).execute()
    in_lieu_items = response.data

    for item in in_lieu_items:
        item_id = item["ItemID"]
        item_name = item["ItemName"]
        quantity_reduced = in_lieu_item_map.get(item_id)  # Get matching quantity

        create_procurement_log(
            "In Lieu",
            status + "_reduce",
            year,
            user["FullName"],
            item_name1=item_name,
            quantity1=quantity_reduced,
            value=budget_impact
        )

    response = private_supabase.table("IN_LIEU").update({"Status": status}).eq("InLieuID", in_lieu_id).execute()
    if response is None:
        return Response({"error": "Error updating in lieu request", "InLieuID": in_lieu_id}, status=500)
    
    ml_learn_from_decision(private_supabase, year, in_lieu_items)
    
    return Response({"status": status}, status=200)

@api_view(['GET'])
def get_signatories(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    response = private_supabase.table("DOCUMENT_SIGNATORY").select("*").execute()
    if response is None:
        return Response({"error": "Error fetching signatories"}, status=401)
    pr_signatories = [{
        "signatoryId": signatory["SignatoryID"],
        "fullName": signatory["FullName"],
        "position": signatory["PositionTitle"],
    }for signatory in response.data
    if signatory["DocumentType"] == "PURCHASE REQUEST"]
    approved_signatories = [{
        "signatoryId": signatory["SignatoryID"],
        "fullName": signatory["FullName"],
        "position": signatory["PositionTitle"],
    } for signatory in response.data
        if signatory["DocumentType"] == "APPROVED PPMP"]
    revised_signatories = [{
        "signatoryId": signatory["SignatoryID"],
        "fullName": signatory["FullName"],
        "position": signatory["PositionTitle"],
    } for signatory in response.data
        if signatory["DocumentType"] == "REVISED PPMP"]
    return Response({"signatories": {
        "prSignatories": pr_signatories,
        "approvedSignatories": approved_signatories,
        "revisedSignatories": revised_signatories
    }}, status=200)

@api_view(['POST'])
def update_signatories(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    missing_fields = check_fields(["signatories", "documentType"], request)
    try:
        if missing_fields:
            return Response({"error": "Missing fields", "missingFields": missing_fields}, status=400)
    except Exception as e:
        return Response({"error": "Invalid fields"}, status=400)
    payload = json.loads(request.data["signatories"])
    signatories = payload["signatories"]
    document_type = request.data["documentType"]
    signatory_id = -1
    try:
        delete = private_supabase.table("DOCUMENT_SIGNATORY").delete().eq("DocumentType", document_type).execute()
        if delete is None:
            return Response({"error": "Error deleting signatories"}, status=500)
        for signatory in signatories:
            signatory_id = signatory["signatoryId"]
            private_supabase.table("DOCUMENT_SIGNATORY").insert({
                "FullName": signatory["fullName"],
                "PositionTitle": signatory["positionTitle"],
                "DocumentType": document_type,
            }).execute()
        pass
    except Exception as e:
        return Response({"error": "Error updating signatories", "signatoryId": signatory_id, "err": f"{e}"}, status=500)
    return Response({"status": "success"}, status=200)


@api_view(['POST'])
def test_ml(request):
    # user = get_user(request)
    # if user is None:
    #     return Response({"error": "User not found"}, status=401)
    missing_fields = check_fields(["year", "targetBudget"], request)
    try:
        if missing_fields:
            return Response({"error": "Missing fields", "missingFields": missing_fields}, status=400)
    except Exception as e:
        return Response({"error": "Invalid fields"}, status=400)
    year = request.POST["year"]
    fiscal_year = private_supabase.table("FISCAL_YEAR").select("FiscalYearID").eq("Year", year).maybe_single().execute()
    if fiscal_year is None:
        return Response({"errpr": "Fiscal year not found"}, status=404)
    fiscal_year_id = fiscal_year.data["FiscalYearID"]
    target_budget = float(request.POST["targetBudget"])
    ppmp_items = private_supabase.table("PPMP_ITEM").select("*").eq("FiscalYearID", fiscal_year_id).execute()
    ppmp_items = ppmp_items.data
    ppmp_item_ids = [ppmp_item["ItemID"] for ppmp_item in ppmp_items]
    item_categories = [ppmp_item["ItemCategory"] for ppmp_item in ppmp_items if
                       ppmp_item["ItemCategory"] not in (None, "", "NULL")]
    in_lieus = private_supabase.table("IN_LIEU").select("InLieuID").eq("Status", "approved").eq("FiscalYearID", fiscal_year_id).execute()
    in_lieus = in_lieus.data
    in_lieu_ids = [in_lieu["InLieuID"] for in_lieu in in_lieus]
    in_lieu_items = private_supabase.table("IN_LIEU_ITEM").select("*").in_("InLieuID", in_lieu_ids).execute()
    in_lieu_items = in_lieu_items.data
    in_lieu_item_map = {}
    for in_lieu_item in in_lieu_items:
        in_lieu_item_map[in_lieu_item["ItemID"]] = True
    in_lieu_item_quantity = {}
    for in_lieu_item in in_lieu_items:
        in_lieu_item_quantity[in_lieu_item["ItemID"]] = in_lieu_item["QuantityReduced"]
    category_data = {}
    for item_category in item_categories:
        planned_quantity = 0
        available_quantity = 0
        in_lieu_total_quantity = 0
        target_was_cut = False
        for ppmp_item in ppmp_items:
            try:
                if ppmp_item["ItemCategory"] == item_category:
                    planned_quantity += ppmp_item["PlannedQuantity"]
                    available_quantity += ppmp_item["AvailableQuantity"]
                    in_lieu_total_quantity += in_lieu_item_quantity[ppmp_item["ItemID"]]
            except KeyError:
                pass
        category_data[item_category] = {
            "ItemCategory": item_category,
            "PlannedQuantity": planned_quantity,
            "AvailableQuantity": available_quantity,
            "InLieuTotalQuantity": in_lieu_total_quantity,
            "TargetWasCut": in_lieu_total_quantity > 0,
        }

    ppmp_items = [ppmp_item for ppmp_item in ppmp_items if
                  not (int(ppmp_item["PlannedQuantity"]) <= 0 or int(ppmp_item["AvailableQuantity"]) <= 0)]

    # --- FIX #1: CREATE MAP EARLY FOR ACCURATE TRAINING DATA ---
    category_history_map = {cat["ItemCategory"]: cat["InLieuTotalQuantity"] for cat in category_data.values()}

    training_data = {}
    for ppmp_item in ppmp_items:
        planned = int(ppmp_item["PlannedQuantity"])
        available = int(ppmp_item["AvailableQuantity"])
        if planned <= 0 or available <= 0:
            print("Skipping:", ppmp_item["ItemID"], planned, available)
            continue
        print("Keeping:", ppmp_item["ItemID"])
        try:
            training_data[ppmp_item["ItemID"]] = {
                "PlannedQuantity": planned,
                "AvailableQuantity": available,
                "InLieuTotalQuantity": category_history_map.get(ppmp_item["ItemCategory"], 0),
                # AI now learns from Category!
            }
        except KeyError:
            training_data[ppmp_item["ItemID"]] = {
                "PlannedQuantity": planned,
                "AvailableQuantity": available,
                "InLieuTotalQuantity": 0,
            }

    legit_training_data_list = list(training_data.values())
    category_data = list(category_data.values())
    live_scoring_data = []
    for ppmp_item in ppmp_items:
        # Look up the CATEGORY volume, not the item ID volume
        cat_history_volume = category_history_map.get(ppmp_item["ItemCategory"], 0)

        live_scoring_data.append({
            "PlannedQuantity": int(ppmp_item["PlannedQuantity"]),
            "AvailableQuantity": int(ppmp_item["AvailableQuantity"]),
            "InLieuTotalQuantity": cat_history_volume
        })

    # Run the AI test exactly ONCE on the properly formatted live items
    live_probabilities = test(live_scoring_data)

    # Attach the correct AI score back to the main items
    for i, ppmp_item in enumerate(ppmp_items):
        # live_probabilities[i][1] is the chance (0.0 to 1.0) of being a good cut
        ppmp_item["AI_Score"] = live_probabilities[i][1]
        # Save the category volume for the UI
        ppmp_item["InLieuTotalQuantity"] = category_history_map.get(ppmp_item["ItemCategory"], 0)

    ppmp_items.sort(
        key=lambda x: x["AI_Score"],
        reverse=True
    )

    # --- OPTIMIZED INTEGER KNAPSACK FUNCTION ---
    def optimized_reverse_knapsack(items_to_evaluate, target_cents):
        model = cp_model.CpModel()
        item_vars = []

        # 1. Setup bounded variables (0 up to AvailableQuantity)
        for i, item in enumerate(items_to_evaluate):
            max_qty = int(item["AvailableQuantity"])
            # This natively handles the volume without flattening!
            var = model.NewIntVar(0, max_qty, f'item_{i}')
            item_vars.append(var)

        # 2. Add your custom Threshold Equality constraint (>= Budget)
        # Using Centavo Scaling (x100)
        model.Add(
            sum(item_vars[i] * int(round(float(items_to_evaluate[i]["PricePerUnit"]) * 100)) for i in
                range(len(items_to_evaluate))) >= target_cents
        )

        # 3. Objective: Prioritize items with the highest AI_Score
        # (Multiply by 1000 to convert float percentages to pure integers for the solver)
        model.Minimize(
            sum(
                item_vars[i] * int(
                    round(
                        (1.01 - items_to_evaluate[i]["AI_Score"]) * float(items_to_evaluate[i]["PricePerUnit"]) * 100))
                for i in range(len(items_to_evaluate))
            )
        )

        # 4. Run the solver with a strict fail-safe timeout
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 10.0  # Will never hang your server!
        status = solver.Solve(model)

        # 5. Extract the exact quantities chosen
        chosen = []
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            for i, item in enumerate(items_to_evaluate):
                qty_selected = solver.Value(item_vars[i])
                if qty_selected > 0:
                    result = item.copy()
                    result["QuantityToReduce"] = qty_selected
                    result["ReducedBudgetImpact"] = qty_selected * float(item["PricePerUnit"])
                    chosen.append(result)
        return chosen

    # --- EXECUTE THE NEW SOLVER ---
    print(f"Total Unique Items ready for Knapsack: {len(ppmp_items)}")

    # Multiply by 100 for Centavo Scaling (e.g. 1000 becomes 100000)
    target_budget_scaled = int(round(target_budget * 100))

    # Pass the normal items directly to the new optimized function
    final_results = optimized_reverse_knapsack(ppmp_items, target_budget_scaled)

    print(f"Total Unique Items Selected: {len(final_results)}")
    chosen_data = [
        {
            "itemId": chosen_item["ItemID"],
            "itemName": chosen_item["ItemName"],
            "unitMeasurement": chosen_item["UnitName"],
            "reduceQuantity": chosen_item["QuantityToReduce"],
            "priceCatalog": chosen_item["PricePerUnit"],
        }
        for chosen_item in final_results
    ]
    return Response({"inLieuData": chosen_data})


@api_view(['GET'])
def get_importances(request):
    user = get_user(request)
    if user is None:
        return Response({"error": "User not found"}, status=401)
    feature_names = [
        "PlannedQuantity",
        "AvailableQuantity",
        "InLieuTotalQuantity",
    ]

    model = joblib.load("in_lieu_model.pkl")
    importances = dict(zip(feature_names, model.feature_importances_))
    return Response(importances)