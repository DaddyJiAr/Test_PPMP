from datetime import datetime

import pandas as pd

from api.services import private_supabase


def testingPPMP(excel_file, row_start, name_column, unit_column, quantity_column, price_per_unit_column):
    df = pd.read_excel(excel_file, header=None, skiprows=row_start - 1)

    df = df.dropna( #filters out empty rows
        subset=[
            name_column,
            unit_column,
            quantity_column,
            price_per_unit_column
        ]
    )

    # print(df.iloc[0])
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

    print(df.head().to_string())
    return df

def upload_excel(df, total_ABC, year):
    current_year = datetime.now().year
    fiscal_year_str = year
    fiscal_year = (
        private_supabase.table("FISCAL_YEAR")
        .select("*")
        .eq("Year", fiscal_year_str)
        .execute()
    )
    fiscal_year_id = ''
    if fiscal_year.data:
        fiscal_year_id = fiscal_year.data[0]["FiscalYearID"]
    else:
        response = (
            private_supabase.table("FISCAL_YEAR")
            .insert({
                "Year": fiscal_year_str,
                "TotalABC": total_ABC,
                "Status": "ongoing"
            })
            .execute()
        )
        fiscal_year_id = response.data[0]["FiscalYearID"]

    try:
        imported_ppmp_grand_total = 0
        for _, row in df.iterrows():
            imported_ppmp_grand_total += int(row["Quantity"]) * float(row["CatalogPrice"])
            private_supabase.table("PPMP_ITEM").insert({
                "ItemName": row["Description"],
                "UnitName": row["Unit"],
                "PlannedQuantity": int(row["Quantity"]),
                "AvailableQuantity": int(row["Quantity"]),
                "PricePerUnit": float(row["CatalogPrice"]),
                "PendingQuantity": 0,
                "ReceivedQuantity": 0,
                "FiscalYearID": fiscal_year_id,
            }).execute()

        # private_supabase.table("PPMP_ITEM").insert({
        #     "ItemName": "Open Funds",
        #     "UnitName": "fund",
        #     "PlannedQuantity": 1,
        #     "AvailableQuantity": 1,
        #     "PricePerUnit": float(total_ABC) - float(imported_ppmp_grand_total),
        #     "PendingQuantity": 0,
        #     "ReceivedQuantity": 0,
        #     "FiscalYearID": fiscal_year_id,
        # }).execute()
    except TypeError as e:
        return e
