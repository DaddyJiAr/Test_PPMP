from time import time

from django.http.response import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, Border, Side, Alignment
import pandas as pd
from api.utils import private_supabase
from api.views import get_ppmp_items


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

    current_category = None
    processed_rows = []

    for _, row in df.iterrows():
        description = row[name_column]
        unit = row[unit_column]
        quantity = row[quantity_column]
        price = row[price_per_unit_column]
        # print(row[name_column-1], description, unit, quantity, price)

        if(
            pd.notna(row[name_column-1])
            and pd.isna(unit)
            and pd.isna(quantity)
            and pd.isna(price)
        ): # check if category
            current_category = str(row[name_column-1]).strip()
            continue
        elif(
            pd.notna(row[name_column])
            and pd.isna(unit)
            and pd.isna(quantity)
            and pd.isna(price)
        ):
            current_category = str(row[name_column]).strip()
            continue
        if (
            pd.notna(description)
            and pd.notna(unit)
            and pd.notna(quantity)
            and pd.notna(price)
        ): # legit
            processed_rows.append({
                "Description": description,
                "Unit": unit,
                "Quantity": quantity,
                "CatalogPrice": price,
                "Category": current_category
            })

    df = pd.DataFrame(processed_rows)

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
            "ItemCategory": row["Category"],
            "PpmpCategory": ppmp_category,
        })
    try:
        private_supabase.table("PPMP_ITEM").insert(records).execute()
    except TypeError as e:
        return e

def export_formatted_excel(year):
    wb = Workbook()
    ws = wb.active
    title = "CICT-PPMP-" + year
    ws.title = title
    default_font = Font(name="Arial", size=10)

    current_row = 2
    current_column = 1
    ws.merge_cells(f"A{current_row}:R{current_row}")
    ws[f"A{current_row}"] = "PROJECT PROCUREMENT MANAGEMENT PLAN (PPMP) " + year
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    ws.column_dimensions[num_to_letter(current_column)].width = 20
    current_row+=1
    ws[f"A{current_row}"] = "END-USER/UNIT: CICT"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, True, "left", "center")
    current_row += 1
    ws[f"A{current_row}"] = "Source of Fund: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, True, "left", "center")

    ws.merge_cells("A5:A7")
    ws.merge_cells("B5:B7")
    ws.merge_cells("C5:C7")
    ws.merge_cells("D5:O5")
    ws.merge_cells("P5:P7")
    ws.merge_cells("Q5:Q7")
    ws.merge_cells("R5:R7")

    current_row = 5
    current_column = 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Seq."
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    set_border_padding_to_cell(ws, current_column, current_row, 5, 20, row_end=current_row+2)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "GENERAL DESCRIPTION"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    set_border_padding_to_cell(ws, current_column, current_row, 45, 20, row_end=current_row+2)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Unit of Measure"
    set_border_padding_to_cell(ws, current_column, current_row, 19, 20, row_end=current_row+2)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Number of Units Needed"
    set_border_padding_to_cell(ws, current_column, current_row, 19, 20, col_end=current_column+11)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column = 16
    ws[f"{num_to_letter(current_column)}{current_row}"] = "TOTAL"
    set_border_padding_to_cell(ws, current_column, current_row, 16, 20, row_end=current_row+2)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Price as per Catalogue"
    set_border_padding_to_cell(ws, current_column, current_row, 18, 20, row_end=current_row+2)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "TOTAL AMOUNT"
    set_border_padding_to_cell(ws, current_column, current_row, 20, 20, row_end=current_row+2)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_row += 1
    current_column = 4
    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    column_width = 8
    for i in range (0, len(months)):
        if i == 8:
            column_width = 13
        if i < 8:
            column_width = 9
        ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column)}{current_row+1}")
        ws[f"{num_to_letter(current_column)}{current_row}"] = months[i]
        set_border_padding_to_cell(ws, current_column, current_row, column_width, 20, row_end=current_row+1)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
        current_column += 1

    # next
    ppmp_items = get_ppmp_items(year)

    office_supplies = [ppmp_item for ppmp_item in ppmp_items.data if ppmp_item["PpmpCategory"] == "Office Supply"]
    lab_supplies = [ppmp_item for ppmp_item in ppmp_items.data if ppmp_item["PpmpCategory"] == "Laboratory Supply/Equipment"]

    office_categories = [ppmp_item["ItemCategory"] for ppmp_item in office_supplies]
    office_categories = list(set(office_categories))
    lab_categories = [ppmp_item["ItemCategory"] for ppmp_item in lab_supplies]
    lab_categories = list(set(lab_categories))

    print("Office Categories:", office_categories)
    print("Lab Categories:", lab_categories)
    # fetch all ppmp items
    # group by PPMP Category
    # group by Item Category
    # assign number, reset per category
    # display subtotal per category
    # sa subtotal price per cat = 0.00
    # get signatories

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{title}.xlsx"'
    wb.save(response)
    return response



def num_to_letter(num):
    return chr(num + 64)

def letter_to_num(letter):
    return ord(letter.upper()) - 64


def set_format_to_cell(ws, column, row, font, size, bold, italic, horizontal, vertical):
    ws[f"{num_to_letter(column)}{row}"].font = Font(bold=bold, italic=italic, name=font, size=size)
    ws[f"{num_to_letter(column)}{row}"].alignment = Alignment(horizontal=horizontal, vertical=vertical)

def set_border_padding_to_cell(ws, col_start, row_start, column_width, row_height,
                                col_end=None, row_end=None,
                                left="thin", right="thin", top="thin", bottom="thin"):
    col_end = col_end or col_start
    row_end = row_end or row_start

    ws.column_dimensions[num_to_letter(col_start)].width = column_width
    ws.row_dimensions[row_start].height = row_height

    for r in range(row_start, row_end + 1):
        for c in range(col_start, col_end + 1):
            border = Border(
                left=Side(style=left) if c == col_start else Side(style="thin"),
                right=Side(style=right) if c == col_end else Side(style="thin"),
                top=Side(style=top) if r == row_start else Side(style="thin"),
                bottom=Side(style=bottom) if r == row_end else Side(style="thin"),
            )
            ws.cell(row=r, column=c).border = border