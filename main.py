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
import pandas as pd
from ortools.sat.python import cp_model  # Added for the optimized knapsack solver

from api.utils import private_supabase
from ml import get_x_y, split, model, test, lahat, reverse_knapsack

ppmp_items = private_supabase.table("PPMP_ITEM").select("*").eq("FiscalYearID", 32).execute()
ppmp_items = ppmp_items.data
ppmp_item_ids = [ppmp_item["ItemID"] for ppmp_item in ppmp_items]
item_categories = [ppmp_item["ItemCategory"] for ppmp_item in ppmp_items if
                   ppmp_item["ItemCategory"] not in (None, "", "NULL")]
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
category_data_list = list(category_data.values())

# model, probabilities = lahat(legit_training_data)
# joblib.dump(model, "in_lieu_model.pkl")

# print(item_probabilities)

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

# --- FIX #3: BUILD LIVE SCORING DATA PROPERLY ---
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
                round((1.01 - items_to_evaluate[i]["AI_Score"]) * float(items_to_evaluate[i]["PricePerUnit"]) * 100))
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
target_budget_scaled = int(59009 * 100)

# Pass the normal items directly to the new optimized function
final_results = optimized_reverse_knapsack(ppmp_items, target_budget_scaled)

print(f"Total Unique Items Selected: {len(final_results)}")

# --- EXPORT DIRECTLY TO EXCEL ---
# No gluing needed because the optimized solver outputs single rows natively
rows = []
for result in final_results:
    row = result.copy()
    rows.append(row)

df = pd.DataFrame(rows)
df.to_excel("ml.xlsx", index=False)
print("Successfully processed and exported to ml.xlsx in milliseconds!")

# from excel import testingPPMP
#
# testingPPMP("PPMP.xlsx", 11, 1, 2, 15, 16)
# from smart_suggest.ml_suggestion import MLSuggest
# from api.utils import private_supabase
#
# ss = MLSuggest(private_supabase, '2026')
# ss.ml_self_train()