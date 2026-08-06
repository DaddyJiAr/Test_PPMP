import joblib
import pandas as pd
from ortools.sat.python import cp_model

from api.utils import private_supabase
from ml import get_x_y, split, model, test, lahat, reverse_knapsack

# ==========================================
# --- HARDCODED TEST VARIABLES ---
# ==========================================
year = "2026"
target_budget = 87098.0  # Change this to test different knapsack limits

print(f"--- Starting Standalone ML Test ---")
print(f"Year: {year} | Target Budget: PHP {target_budget}")
# ==========================================

# FETCH FISCAL YEAR & TOTAL ABC
fiscal_year = private_supabase.table("FISCAL_YEAR").select("TotalABC, FiscalYearID").eq("Year", year).single().execute()
if fiscal_year is None or fiscal_year.data is None:
    print("Error: Fiscal year not found.")
    exit()

fiscal_year_id = fiscal_year.data["FiscalYearID"]
total_annual_budget = float(fiscal_year.data.get("TotalABC", 0) or 0)

ppmp_items_response = private_supabase.table("PPMP_ITEM").select("*").eq("FiscalYearID", fiscal_year_id).execute()
ppmp_items = ppmp_items_response.data

# CALCULATE UNALLOCATED OPEN FUNDS
allocated_funds = sum(
    float(item["PlannedQuantity"]) * float(item["PricePerUnit"])
    for item in ppmp_items
)
unallocated_funds_total = total_annual_budget - allocated_funds

ppmp_item_ids = [ppmp_item["ItemID"] for ppmp_item in ppmp_items]
item_categories = [ppmp_item["ItemCategory"] for ppmp_item in ppmp_items if
                   ppmp_item["ItemCategory"] not in (None, "", "NULL")]

# QUERY IN_LIEU HISTORY USING FISCAL YEAR ID
in_lieus = private_supabase.table("IN_LIEU").select("InLieuID, OpenFundsUtilized").eq("Status", "approved").eq(
    "FiscalYearID", fiscal_year_id).execute()
in_lieus = in_lieus.data
in_lieu_ids = [in_lieu["InLieuID"] for in_lieu in in_lieus]

# SUM HISTORICAL OPEN FUNDS UTILIZED
open_funds_history = sum(float(il.get("OpenFundsUtilized", 0) or 0) for il in in_lieus)

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
    for ppmp_item in ppmp_items:
        try:
            if ppmp_item["ItemCategory"] == item_category:
                planned_quantity += ppmp_item["PlannedQuantity"]
                available_quantity += ppmp_item["AvailableQuantity"]
                in_lieu_total_quantity += in_lieu_item_quantity.get(ppmp_item["ItemID"], 0)
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

# --- INJECT OPEN FUNDS MOCK ITEM ---
if unallocated_funds_total > 0:
    ppmp_items.append({
        "ItemID": 0,
        "ItemName": "Unallocated Open Funds",
        "UnitName": "PHP",
        "PricePerUnit": 1.0,  # Price is 1 PHP per 1 PHP
        "PlannedQuantity": int(unallocated_funds_total),
        "AvailableQuantity": int(unallocated_funds_total),
        "FiscalYearID": fiscal_year_id,
        "ItemCategory": None,
        "PpmpCategory": None,
        "InLieuTotalQuantity": open_funds_history
    })

# --- CREATE MAP EARLY FOR ACCURATE TRAINING DATA ---
category_history_map = {cat["ItemCategory"]: cat["InLieuTotalQuantity"] for cat in category_data.values()}

training_data = {}
for ppmp_item in ppmp_items:
    # Skip ItemID 0 for the training dictionary to prevent KeyError
    if ppmp_item["ItemID"] == 0:
        continue

    planned = int(ppmp_item["PlannedQuantity"])
    available = int(ppmp_item["AvailableQuantity"])
    if planned <= 0 or available <= 0:
        continue

    try:
        training_data[ppmp_item["ItemID"]] = {
            "PlannedQuantity": planned,
            "AvailableQuantity": available,
            "InLieuTotalQuantity": category_history_map.get(ppmp_item["ItemCategory"], 0),
        }
    except KeyError:
        training_data[ppmp_item["ItemID"]] = {
            "PlannedQuantity": planned,
            "AvailableQuantity": available,
            "InLieuTotalQuantity": 0,
        }

live_scoring_data = []
for ppmp_item in ppmp_items:
    # --- BYPASS CATEGORY FOR OPEN FUNDS ---
    if ppmp_item["ItemID"] == 0:
        cat_history_volume = ppmp_item["InLieuTotalQuantity"]
    else:
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
    ppmp_item["AI_Score"] = live_probabilities[i][1]

    # Save the volume for the UI, bypassing the zero ID
    if ppmp_item["ItemID"] != 0:
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
        var = model.NewIntVar(0, max_qty, f'item_{i}')
        item_vars.append(var)

    # 2. Add your custom Threshold Equality constraint (>= Budget)
    model.Add(
        sum(item_vars[i] * int(round(float(items_to_evaluate[i]["PricePerUnit"]) * 100)) for i in
            range(len(items_to_evaluate))) >= target_cents
    )

    # 3. Objective: Minimize Penalty
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
    solver.parameters.max_time_in_seconds = 10.0
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


# Multiply by 100 for Centavo Scaling
target_budget_scaled = int(round(target_budget * 100))

print(f"Total Unique Items ready for Knapsack: {len(ppmp_items)}")
print("Running solver...")

# Pass the normal items directly to the new optimized function
final_results = optimized_reverse_knapsack(ppmp_items, target_budget_scaled)

print(f"Total Unique Items Selected: {len(final_results)}")

# --- CONSTRUCT CONSOLE / EXCEL OUTPUT ---
chosen_data = []
for chosen_item in final_results:
    chosen_data.append({
        "ItemID": chosen_item["ItemID"],
        "ItemName": chosen_item["ItemName"],
        "UnitName": chosen_item["UnitName"],
        "AI_Score": chosen_item["AI_Score"],
        "QuantityToReduce": chosen_item["QuantityToReduce"],
        "PricePerUnit": chosen_item["PricePerUnit"],
        "ReducedBudgetImpact": chosen_item["ReducedBudgetImpact"]
    })

# Export to Excel to view exactly what the knapsack selected
if chosen_data:
    df = pd.DataFrame(chosen_data)
    df.to_excel("ml.xlsx", index=False)
    print("Successfully processed and exported results to ml.xlsx!")
else:
    print("No items selected. (Check if Target Budget is too high or Available Quantities are too low).")







#ml retrain using actual items
# import pandas as pd
# from api.utils import private_supabase
# from ml import model, save_model
#
# print("--- 1. FETCHING STRICTLY APPROVED DATA ---")
#
# # Fetch all items
# ppmp_items_response = private_supabase.table("PPMP_ITEM").select("ItemID, PlannedQuantity, AvailableQuantity").execute()
# ppmp_items = ppmp_items_response.data
#
# # Fetch strictly approved In Lieu records
# in_lieus = private_supabase.table("IN_LIEU").select("InLieuID").eq("Status", "approved").execute()
# in_lieu_ids = [in_lieu["InLieuID"] for in_lieu in in_lieus.data]
#
# print("--- 2. AGGREGATING IN LIEU TOTALS ---")
# in_lieu_item_quantity = {}
#
# if in_lieu_ids:
#     in_lieu_items = private_supabase.table("IN_LIEU_ITEM").select("ItemID, QuantityReduced").in_("InLieuID",
#                                                                                                  in_lieu_ids).execute()
#
#     for item in in_lieu_items.data:
#         # Force the ItemID to be a string to guarantee perfect duplicate matching
#         item_id = str(item["ItemID"])
#
#         # Force the quantity to be an integer for safe math
#         raw_qty = item.get("QuantityReduced")
#         qty = int(raw_qty) if raw_qty is not None else 0
#
#         # Sum the quantities if the item was cut multiple times
#         in_lieu_item_quantity[item_id] = in_lieu_item_quantity.get(item_id, 0) + qty
#
# print("--- 3. BUILDING THE RAW DATASET ---")
#
# X_train_raw = []
# Y_train = []
# validation_rows = []  # Keeping this so you can still check the Excel export
#
# for item in ppmp_items:
#     item_id = str(item.get("ItemID"))
#     planned = int(item.get("PlannedQuantity", 0))
#     available = int(item.get("AvailableQuantity", 0))
#
#     # Get the correctly summed total (or 0 if none)
#     in_lieu_qty = in_lieu_item_quantity.get(item_id, 0)
#
#     # Y Variable: 1 if cut, 0 if not
#     target_was_cut = 1 if in_lieu_qty > 0 else 0
#
#     # Only include valid baselines
#     if planned > 0:
#         # X Variable strictly math array
#         X_train_raw.append([planned, available, in_lieu_qty])
#
#         # Y Variable the answer key
#         Y_train.append(target_was_cut)
#
#         # Save for your human-readable Excel check
#         validation_rows.append({
#             "ItemID": item_id,
#             "PlannedQuantity": planned,
#             "AvailableQuantity": available,
#             "InLieuTotalQuantity": in_lieu_qty,
#             "TargetWasCut": target_was_cut
#         })
#
# print("--- 4. BINDING LIVE VARIABLE NAMES ---")
# # Convert the nameless Python list into a Pandas DataFrame with strict column headers
# X_train_named = pd.DataFrame(
#     X_train_raw,
#     columns=["PlannedQuantity", "AvailableQuantity", "InLieuTotalQuantity"]
# )
#
# print("--- 5. TRAINING AND SAVING THE AI ---")
# # Pass the NAMED dataframe into your backend dev's model function
# trained_ai = model(X_train_named, Y_train)
#
# # Save the updated brain directly to your project
# save_model(trained_ai)
# print("SUCCESS! The named, mathematically accurate model has been saved to 'in_lieu_model.pkl'.")
#
# print("--- 6. EXPORTING EXCEL VALIDATION ---")
# df_val = pd.DataFrame(validation_rows)
#
# # Sort so the items with actual In Lieu history appear at the top
# df_val = df_val.sort_values(by="InLieuTotalQuantity", ascending=False)
#
# df_val.to_excel(excel_filename, index=False)
#
# print(f"Exported {len(df_val)} rows to '{excel_filename}' for your manual review.")