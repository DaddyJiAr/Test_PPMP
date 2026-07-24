from datetime import datetime

import pandas as pd

from api.utils import private_supabase


def testingPPMP(excel_file, row_start, name_column, unit_column, quantity_column, price_per_unit_column, year, ppmp_category="Office Supply"):
    fiscal_year_str = year
    fiscal_year = private_supabase.table("FISCAL_YEAR").select("*").eq("Year", fiscal_year_str).execute()


    df = pd.read_excel(excel_file, header=None, skiprows=row_start - 1)

    required_columns = [
        name_column,
        unit_column,
        quantity_column,
        price_per_unit_column,
    ]

    missing = [c for c in required_columns if c not in df.columns]

    if missing:
        raise ValueError({
            "message": f"Column(s) {missing} do not exist or are completely empty.",
        })

    df = df.dropna( #filters out empty rows
        subset=[
            name_column,
            unit_column,
            quantity_column,
            price_per_unit_column
        ]
    )

    df = df.iloc[:, [ #only includes necessary columns
        name_column,
        unit_column,
        quantity_column,
        price_per_unit_column
    ]]

    df.columns = [ #rename
        "Description",
        "Unit",
        "Quantity",
        "CatalogPrice"
    ]

    # check for incorrect data types (mga NaN)
    quantity = pd.to_numeric(df["Quantity"], errors="coerce")
    price = pd.to_numeric(df["CatalogPrice"], errors="coerce")

    bad = df[quantity.isna() | price.isna()]

    if not bad.empty:
        errors = []

        for index, row in bad.iterrows():
            errors.append({
                "row": index,
                "quantity": row["Quantity"],
                "price": row["CatalogPrice"],
            })
        raise ValueError({
            "message": "Invalid numeric values found in the Excel file.",
            "rows": errors,
        })

    df["Quantity"] = quantity
    df["CatalogPrice"] = price

    df["TotalAmount"] = df["Quantity"] * df["CatalogPrice"]
    total_amount =  df["TotalAmount"].sum()
    if fiscal_year.data:
        return df, total_amount, True
    else:
        return df, total_amount, False

def upload_excel(df, total_ABC, year, ppmp_category="Office Supply"):
    fiscal_year = private_supabase.table("FISCAL_YEAR").select("*").eq("Year", year).execute()
    fiscal_year_id = 0
    if fiscal_year.data and ppmp_category == "Office Supply":
        fiscal_year_id = fiscal_year.data[0]["FiscalYearID"]
        private_supabase.table("FISCAL_YEAR").delete().eq("FiscalYearID", fiscal_year_id).execute() #cascade delete

        response = private_supabase.table("FISCAL_YEAR").insert({
                "Year": year,
                "TotalABC": total_ABC,
                "Status": "ongoing"
            }).execute()
        fiscal_year_id = response.data[0]["FiscalYearID"]
    else:
        response = private_supabase.table("FISCAL_YEAR").select("FiscalYearID").eq("Year", year).maybe_single().execute()
        if response is None:
            response = private_supabase.table("FISCAL_YEAR").insert({
                "Year": year,
                "TotalABC": total_ABC,
                "Status": "ongoing"
            }).execute()
            fiscal_year_id = response.data[0]["FiscalYearID"]
        else:
            fiscal_year_id = response.data["FiscalYearID"]
    records = []

    for _, row in df.iterrows():
        records.append({
            "ItemName": row["Description"],
            "UnitName": row["Unit"],
            "PlannedQuantity": int(row["Quantity"]),
            "AvailableQuantity": int(row["Quantity"]),
            "PricePerUnit": float(row["CatalogPrice"]),
            "PendingQuantity": 0,
            "FulfilledQuantity": 0,
            "FiscalYearID": fiscal_year_id,
            "PpmpCategory": ppmp_category,
        })
    try:
        private_supabase.table("PPMP_ITEM").insert(records).execute()
    except TypeError as e:
        return e