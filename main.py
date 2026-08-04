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
import joblib

import joblib

from api.utils import private_supabase
from ml import get_x_y, split, model, test, lahat, reverse_knapsack
import pandas as pd

ppmp_items = private_supabase.table("PPMP_ITEM").select("*").execute()
ppmp_items = ppmp_items.data
ppmp_item_ids = [ppmp_item["ItemID"] for ppmp_item in ppmp_items]
item_categories = [ppmp_item["ItemCategory"] for ppmp_item in ppmp_items if ppmp_item["ItemCategory"] not in (None, "", "NULL")]
in_lieus = private_supabase.table("IN_LIEU").select("InLieuID").eq("Status", "approved").execute()
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


#
# # RULE BASED
# scored_items = []
# for ppmp_item in ppmp_items:
#     score = 0
#     if ppmp_item["ItemID"] == "Office Supply":
#         score += 3
#     if ppmp_item["AvailableQuantity"] > 100:
#         score += 2
#     if ppmp_item["PricePerUnit"] < 500:
#         score += 2
#     try:
#         if in_lieu_item_map[ppmp_item["ItemID"]]:
#             score += 2
#     except KeyError:
#         pass
#     scored_items.append({
#         "item": ppmp_item,
#         "score": score
#     })
#
# scored_items.sort(
#     key=lambda x: x["score"],
#     reverse=True
# )
#
# rows = []
#
# for result in scored_items:
#     row = result["item"].copy()   # Copy the nested item dict
#     row["score"] = result["score"]  # Add the score
#     rows.append(row)
#
# df = pd.DataFrame(rows)
# df.to_excel("rule.xlsx", index=False)
#
# in_lieu_items = {}
# target_budget = 10000
# for item in scored_items:
#     max_reduce = int(item["item"]["PlannedQuantity"] * 0.7)
#     amount = 0
#     if target_budget < 0:
#         break
#     amount_to_reduce = 0
#     reduce_count = 0
#     while reduce_count < max_reduce and target_budget > 0:
#         reduce_count += 1
#         amount += item["item"]["PricePerUnit"]
#         target_budget -= item["item"]["PricePerUnit"]
#         if reduce_count > 0:
#             in_lieu_items[item["item"]["ItemID"]] = {
#                 "item": item["item"]["ItemName"],
#                 "reduce_count": reduce_count,
#                 "amount_to_reduce": amount,
#                 "score": item["score"]
#             }
#         if target_budget <= 0:
#             break
#
# for scored_item in scored_items:
#     print(scored_item)
#
# ML
# training_rows = []
# for ppmp_item in ppmp_items:
#     try:
#         was_reduced = ppmp_item["ItemID"] in in_lieu_item_map
#     except KeyError:
#         was_reduced = False
#     training_rows.append({
#         "PricePerUnit": ppmp_item["PricePerUnit"],
#         "PlannedQuantity": ppmp_item["PlannedQuantity"],
#         "AvailableQuantity": ppmp_item["AvailableQuantity"],
#         "PpmpCategory": ppmp_item["PpmpCategory"],
#         "WasReduced": was_reduced,
#     })
#
# X, Y = get_x_y(legit_training_data)
# X_train, X_test, Y_train, Y_test = split(X, Y)
# model = model(X_train, Y_train)
# test(X_test, Y_test, model)

training_data = {}
for ppmp_item in ppmp_items:
    try:
        training_data[ppmp_item["ItemID"]] = {
        "PlannedQuantity": ppmp_item["PlannedQuantity"],
        "AvailableQuantity": ppmp_item["AvailableQuantity"],
        "InLieuTotalQuantity": in_lieu_item_quantity[ppmp_item["ItemID"]],
    }
    except KeyError:
        pass


legit_training_data_list = list(training_data.values())
category_data = list(category_data.values())
# model, probabilities = lahat(legit_training_data)
# joblib.dump(model, "in_lieu_model.pkl")
category_probabilities = test(category_data)
item_probabilities = test(legit_training_data_list)
# print(item_probabilities)

for i, category in enumerate(category_data):
    category["AI_Score"] = category_probabilities[i][1]

for i, item in enumerate(legit_training_data_list):
    item["AI_Score"] = item_probabilities[i][1]
#
legit_training_data_list.sort(
    key=lambda x: x["AI_Score"],
    reverse=True
)


category_score_map = {
    row["ItemCategory"]: row["AI_Score"]
    for row in category_data
}

item_score_map = {}
for item_id, probability in zip(training_data.keys(), item_probabilities):
    item_score_map[item_id] = probability[1]

# for ppmp_item in ppmp_items:
#     try:
#         training_data[ppmp_item["ItemID"]] = {
#
#         "PlannedQuantity": ppmp_item["PlannedQuantity"],
#         "AvailableQuantity": ppmp_item["AvailableQuantity"],
#         "InLieuTotalQuantity": in_lieu_item_quantity[ppmp_item["ItemID"]],
#     }
#     except KeyError:
#         pass


for ppmp_item in ppmp_items:
    ppmp_item["AI_Score"] = (
            item_score_map.get(ppmp_item["ItemID"], 0)
            + category_score_map.get(ppmp_item["ItemCategory"], 0)
    )

    ppmp_item["InLieuTotalQuantity"] = in_lieu_item_quantity.get(
        ppmp_item["ItemID"],
        0
    )

    ppmp_item["BudgetImpact"] = int(
        round(
            ppmp_item["PricePerUnit"] *
            ppmp_item["PlannedQuantity"]
        )
    )

ppmp_items.sort(
    key=lambda x: x["AI_Score"],
    reverse=True
)

print(len(ppmp_items))
chosen = reverse_knapsack(ppmp_items, 100)
print(len(chosen))

rows = []
for result in chosen:
    row = result.copy()   # Copy the nested item dict
    rows.append(row)

df = pd.DataFrame(rows)
df.to_excel("ml.xlsx", index=False)
# from excel import testingPPMP
# 
# testingPPMP("PPMP.xlsx", 11, 1, 2, 15, 16)
# from smart_suggest.ml_suggestion import MLSuggest
# from api.utils import private_supabase
#
# ss = MLSuggest(private_supabase, '2026')
# ss.ml_self_train()
