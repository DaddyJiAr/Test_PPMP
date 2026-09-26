from rest_framework.exceptions import APIException
from rest_framework.response import Response
from dotenv import load_dotenv
import os
import tempfile
import joblib
from supabase import create_client

load_dotenv()
url = os.getenv("SUPABASE_URL")

public_supabase = create_client(url, os.getenv("SUPABASE_ANON_KEY"))
private_supabase = create_client(url, os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

def create_supabase():
    return create_client(url, os.getenv("SUPABASE_SERVICE_ROLE_KEY"))

def get_user(request):
    try:
        token = get_token(request)
        user = private_supabase.auth.get_user(token).user
        if user is None:
            return None
        response = private_supabase.table("USER").select("*").eq("UserID", user.id).single().execute()
        return response.data
    except Exception:
        return None

def get_auth_user(request):
    try:
        token = get_token(request)
        user = private_supabase.auth.get_user(token).user
        return user
    except Exception:
        return None

def get_token(request):
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    token = auth.replace("Bearer ", "")
    return token

def get_role_token(token):
    user = get_user(token)
    if user is None:
        return None
    else:
        return user[0]["Role"]

def check_user(request):
    token = get_token(request)
    user = get_user(token)
    if user is None:
        return False
    else:
        return True

def check_admin(request):
    token = get_token(request)
    user = get_user(token)
    if user is None:
        return False
    else:
        return user["Role"] == "Admin"

def check_fields(required_fields, request):
    missing_fields = [
        field for field in required_fields
        if not request.data.get(field)
    ]
    if missing_fields:
        return missing_fields
    else:
        return None

def get_ppmp_items(year):
    fiscal_year = private_supabase.table("FISCAL_YEAR").select("*").eq("Year", year).single().execute()
    return private_supabase.table("PPMP_ITEM").select("*").eq("FiscalYearID", fiscal_year.data["FiscalYearID"]).execute()

def get_dashboard_cards(year):
    fiscal_year = private_supabase.table("FISCAL_YEAR").select("TotalABC", "FiscalYearID").eq("Year",
                                                                                              year).maybe_single().execute()
    if fiscal_year is None:
        raise APIException("No fiscal year found")
    total_annual_budget = fiscal_year.data["TotalABC"]
    ppmp_items = private_supabase.table("PPMP_ITEM").select(
        "ItemID, PlannedQuantity, PendingQuantity, FulfilledQuantity, AvailableQuantity, PricePerUnit").eq(
        'FiscalYearID', fiscal_year.data["FiscalYearID"]).execute()
    item_ids = list({
        item["ItemID"]
        for item in ppmp_items.data
        if item["ItemID"] is not None
    })
    purchase_requests = private_supabase.table("PURCHASE_REQUEST").select("ItemID, RequestQuantity, Status").in_(
        "ItemID", item_ids).execute()
    in_lieus = private_supabase.table("IN_LIEU").select("Status").eq('FiscalYearID',
                                                                     fiscal_year.data["FiscalYearID"]).execute()
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
    return (total_annual_budget, committed_funds, available_lieu_pool_funds, open_funds, requested_funds,
     arrived_funds, pending_in_lieu_count)

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

def load_ai_model():
    data = private_supabase.storage.from_(
        "in_lieu_model"
    ).download("in_lieu_model.pkl")

    model_path = os.path.join(
        tempfile.gettempdir(),
        "in_lieu_model.pkl"
    )

    with open(model_path, "wb") as f:
        f.write(data)

    return joblib.load(model_path)