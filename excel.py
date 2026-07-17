from datetime import datetime

import pandas as pd

from api.services import private_supabase


def testingPPMP(excel_file, row_start, name_column, unit_column, quantity_column, price_per_unit_column, year):
    fiscal_year_str = year
    fiscal_year = (
        private_supabase.table("FISCAL_YEAR")
        .select("*")
        .eq("Year", fiscal_year_str)
        .execute()
    )

    df = pd.read_excel(excel_file, header=None, skiprows=row_start - 1)

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

    df["TotalAmount"] = df["Quantity"] * df["CatalogPrice"]
    total_amount =  df["TotalAmount"].sum()
    if fiscal_year.data:
        return df, total_amount, True
    else:
        return df, total_amount, False

def upload_excel(df, total_ABC, year):
    current_year = datetime.now().year
    fiscal_year = (
        private_supabase.table("FISCAL_YEAR")
        .select("*")
        .eq("Year", year)
        .execute()
    )
    fiscal_year_id = ''
    if fiscal_year.data:
        fiscal_year_id = fiscal_year.data[0]["FiscalYearID"]
        private_supabase.table("FISCAL_YEAR").delete().eq("FiscalYearID", fiscal_year_id).execute() #cascade delete

    response = (
        private_supabase.table("FISCAL_YEAR")
        .insert({
            "Year": year,
            "TotalABC": total_ABC,
            "Status": "ongoing"
        })
        .execute()
    )
    fiscal_year_id = response.data[0]["FiscalYearID"]

    records = []

    for _, row in df.iterrows():
        records.append({
            "ItemName": row["Description"],
            "UnitName": row["Unit"],
            "PlannedQuantity": int(row["Quantity"]),
            "AvailableQuantity": int(row["Quantity"]),
            "PricePerUnit": float(row["CatalogPrice"]),
            "PendingQuantity": 0,
            "ReceivedQuantity": 0,
            "FiscalYearID": fiscal_year_id,
        })
    try:
        private_supabase.table("PPMP_ITEM").insert(records).execute()
    except TypeError as e:
        return e