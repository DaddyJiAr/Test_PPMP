# from dotenv import load_dotenv
# import os
# from supabase import create_client
#
# load_dotenv()
#
# url = os.getenv("SUPABASE_URL")
# key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
#
# supabase = create_client(url, key)
#
# email = input("Enter your email: ")
# password = input("Enter your password: ")
# fullName = input("Enter your full name: ")
# role = input("Enter your role: ")
#
# status = "active" #default?
#
# response = supabase.auth.admin.create_user({
#     "email": email,
#     "password": password,
#     "email_confirm": False
# })
#
# user = response.user
#
# response = supabase.table("USER").insert({
#         "UserID": user.id,
#         "FullName": fullName,
#         "EmailAddress": email,
#         "Password": password,
#         "Role": role,
#         "Status": status,
#     }).execute()
#
# print(response.data)
#
# # from excel import testingPPMP
# #
# # testingPPMP("PPMP.xlsx", 11, 1, 2, 15, 16)
# from api.utils import private_supabase
#
# response = private_supabase.table("PPMP_ITEM").select("*").eq("ItemID", 69).execute()
# print(response.data)

from api.utils import private_supabase
from ml import get_x_y, split, model, test, lahat
import pandas as pd

ppmp_items = private_supabase.table("PPMP_ITEM").select("*").eq("FiscalYearID", 32).execute()
ppmp_items = ppmp_items.data
ppmp_items
ppmp_item_ids = [ppmp_item["ItemID"] for ppmp_item in ppmp_items]
in_lieus = private_supabase.table("IN_LIEU_ITEM").select("*").in_("ItemID", ppmp_item_ids).execute()
in_lieus = in_lieus.data
in_lieu_map = {}
for in_lieu in in_lieus:
    in_lieu_map[in_lieu["ItemID"]] = True

# RULE BASED
scored_items = []
for ppmp_item in ppmp_items:
    score = 0
    if ppmp_item["ItemID"] == "Office Supply":
        score += 3
    if ppmp_item["AvailableQuantity"] > 100:
        score += 2
    if ppmp_item["PricePerUnit"] < 500:
        score += 2
    try:
        if in_lieu_map[ppmp_item["ItemID"]]:
            score += 2
    except KeyError:
        pass
    scored_items.append({
        "item": ppmp_item,
        "score": score
    })

scored_items.sort(
    key=lambda x: x["score"],
    reverse=True
)

rows = []

for result in scored_items:
    row = result["item"].copy()   # Copy the nested item dict
    row["score"] = result["score"]  # Add the score
    rows.append(row)

df = pd.DataFrame(rows)
df.to_excel("rule.xlsx", index=False)

in_lieu_items = {}
target_budget = 10000
for item in scored_items:
    max_reduce = int(item["item"]["PlannedQuantity"] * 0.7)
    amount = 0
    if target_budget < 0:
        break
    amount_to_reduce = 0
    reduce_count = 0
    while reduce_count < max_reduce and target_budget > 0:
        reduce_count += 1
        amount += item["item"]["PricePerUnit"]
        target_budget -= item["item"]["PricePerUnit"]
        if reduce_count > 0:
            in_lieu_items[item["item"]["ItemID"]] = {
                "item": item["item"]["ItemName"],
                "reduce_count": reduce_count,
                "amount_to_reduce": amount,
                "score": item["score"]
            }
        if target_budget <= 0:
            break

for scored_item in scored_items:
    print(scored_item)

# ML
training_rows = []
for ppmp_item in ppmp_items:
    try:
        was_reduced = ppmp_item["ItemID"] in in_lieu_map
    except KeyError:
        was_reduced = False
    training_rows.append({
        "PricePerUnit": ppmp_item["PricePerUnit"],
        "PlannedQuantity": ppmp_item["PlannedQuantity"],
        "AvailableQuantity": ppmp_item["AvailableQuantity"],
        "PpmpCategory": ppmp_item["PpmpCategory"],
        "WasReduced": was_reduced,
    })

# X, Y = get_x_y(training_rows)
# X_train, X_test, Y_train, Y_test = split(X, Y)
# model = model(X_train, Y_train)
# test(X_test, Y_test, model)

probabilities = lahat(training_rows)
for i, item in enumerate(ppmp_items):
    item["AI_Score"] = probabilities[i][1]

ppmp_items.sort(
    key=lambda x: x["AI_Score"],
    reverse=True
)

for ppmp_item in ppmp_items:
    print(ppmp_item)

rows = []
for result in ppmp_items:
    row = result.copy()   # Copy the nested item dict
    rows.append(row)

df = pd.DataFrame(rows)
df.to_excel("ml.xlsx", index=False)
# from excel import testingPPMP
# 
# testingPPMP("PPMP.xlsx", 11, 1, 2, 15, 16)
from smart_suggest.ml_suggestion import MLSuggest
from api.utils import private_supabase

ss = MLSuggest(private_supabase, '2026')
ss.ml_self_train()
