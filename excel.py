import calendar
import datetime
from time import time

from django.http.response import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, Border, Side, Alignment, PatternFill
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.series import SeriesLabel
from openpyxl.chart.text import RichText
from openpyxl.chart.layout import Layout, ManualLayout
from openpyxl.drawing.text import Paragraph, ParagraphProperties, CharacterProperties, RichTextProperties
import pandas as pd
from api.utils import private_supabase, get_dashboard_cards
from api.views import get_ppmp_items
from rest_framework.response import Response



def is_empty_or_zero(value):
    return pd.isna(value) or value == 0

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
    left_col = name_column - 1 if name_column > 0 else 0

    for _, row in df.iterrows():
        description = row[name_column]
        unit = row[unit_column]
        quantity = row[quantity_column]
        price = row[price_per_unit_column]
        left = row[left_col]
        right = row[name_column]

        name = None

        if pd.notna(left):
            name = str(left).strip()
        elif pd.notna(right):
            name = str(right).strip()
        else:
            continue

        if(
            pd.notna(row[name_column])
            and is_empty_or_zero(unit)
            and is_empty_or_zero(quantity)
            and is_empty_or_zero(price)
        ): # check if category
            if "subtotal" in name.lower() or "total" in name.lower():
                continue
            current_category = name
            continue
        elif(
            pd.notna(row[left_col])
            and is_empty_or_zero(unit)
            and is_empty_or_zero(quantity)
            and is_empty_or_zero(price)
        ):
            if "subtotal" in name.lower() or "total" in name.lower():
                continue
            current_category = name
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
                "CatalogPrice": f"{price:.2f}",
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
            "error": "Invalid numeric values found in the Excel file.",
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

def export_formatted_excel(year, options, dean_name):
    fiscal_year = private_supabase.table("FISCAL_YEAR").select("FiscalYearID").eq("Year", year).maybe_single().execute()
    if not fiscal_year:
        return Response({"error": "Fiscal year missing"},status=404)
    fiscal_year = fiscal_year.data["FiscalYearID"]
    title = "CICT-PPMP-" + year
    want_revised = "revised_ppmp" in options
    want_supplemental = "supplemental_ppmp" in options
    want_in_lieus = "in_lieus" in options
    want_purchase_requests = "purchase_requests" in options
    want_dashboard_report = "dashboard_report" in options
    wb = Workbook()
    default_ws = wb.active

    if want_revised: add_revised(wb, year, title, dean_name)
    if want_supplemental: add_supplemental(wb, fiscal_year, title, dean_name)
    if want_in_lieus: add_in_lieus(wb, fiscal_year, year, dean_name)
    if want_purchase_requests: add_purchase_request(wb, fiscal_year, year, dean_name)
    if want_dashboard_report: add_dashboard_report(wb, fiscal_year, year)

    if default_ws.title == "Sheet" and len(wb.worksheets) > 1:
        wb.remove(default_ws)

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{title}.xlsx"'
    wb.save(response)
    return response

def add_revised(wb, year, title, dean_name):
    ws = wb.create_sheet(title)
    ws.sheet_view.showGridLines = False
    default_font = Font(name="Arial", size=10)
    total_count = 0
    grand_total_amount = 0
    start_row = 0
    end_row = 0
    start_column = 1
    end_column = 0
    start_number_column = 0
    end_number_column = 0
    start_decimal_column = 0
    end_decimal_column = 0

    current_row = 2
    current_column = 1
    (
        current_column,
        current_row,
        start_number_column,
        end_number_column,
        start_decimal_column,
        end_decimal_column,
        end_column,
    ) = set_revised_header(ws, current_column, current_row, year)
    ppmp_items = get_ppmp_items(year)

    office_supplies = [ppmp_item for ppmp_item in ppmp_items.data if ppmp_item["PpmpCategory"] == "Office Supply"]
    lab_supplies = [ppmp_item for ppmp_item in ppmp_items.data if
                    ppmp_item["PpmpCategory"] == "Laboratory Supply/Equipment"]

    office_categories = [ppmp_item["ItemCategory"] for ppmp_item in office_supplies]
    office_categories = list(dict.fromkeys(office_categories))
    lab_categories = [ppmp_item["ItemCategory"] for ppmp_item in lab_supplies]
    lab_categories = list(dict.fromkeys(lab_categories))
    office_supplies_dict = {}

    for office_category in office_categories:
        category_items = [
            item
            for item in office_supplies
            if item["ItemCategory"] == office_category
        ]

        office_supplies_dict[office_category] = [
            {
                "Seq.": i,
                "GENERAL DESCRIPTION": item["ItemName"],
                "Unit of Measure": item["UnitName"],
                "January": item["AvailableQuantity"],
                "TOTAL": item["AvailableQuantity"],
                "Price as per Catalogue": item["PricePerUnit"],
                "TOTAL AMOUNT": item["AvailableQuantity"] * item["PricePerUnit"],
            }
            for i, item in enumerate(category_items, start=1)
        ]

    office_supplies = office_supplies_dict

    lab_supplies_dict = {}

    for lab_category in lab_categories:
        category_items = [
            item
            for item in lab_supplies
            if item["ItemCategory"] == lab_category
        ]

        lab_supplies_dict[lab_category] = [
            {
                "Seq.": i,
                "GENERAL DESCRIPTION": item["ItemName"],
                "Unit of Measure": item["UnitName"],
                "January": item["AvailableQuantity"],
                "TOTAL": item["AvailableQuantity"],
                "Price as per Catalogue": item["PricePerUnit"],
                "TOTAL AMOUNT": item["AvailableQuantity"] * item["PricePerUnit"],
            }
            for i, item in enumerate(category_items, start=1)
        ]

    lab_supplies = lab_supplies_dict

    current_row += 2
    current_column = 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = "OFFICE SUPPLIES"
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    set_border_to_cell(ws, current_column, current_row, left=None, right=None, top=None, bottom=None,
                       col_end=current_column + 1)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")

    start_row = current_row
    total_count1, grand_total_amount1 = 0, 0
    total_count2, grand_total_amount2 = 0, 0
    total_count1, grand_total_amount1, current_row = ppmp_item_category(office_supplies, ws, current_row)
    if lab_supplies:
        current_row += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = "LAB SUPPLIES"
        ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
        set_border_to_cell(ws, current_column, current_row, left=None, right=None, top=None, bottom=None,
                           col_end=current_column + 1)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
        total_count2, grand_total_amount2, current_row = ppmp_item_category(lab_supplies, ws, current_row)
    total_count = total_count1 + total_count2
    grand_total_amount = grand_total_amount1 + grand_total_amount2
    current_row += 1
    current_column = 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "GRAND TOTAL:"
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    set_border_to_cell(ws, current_column, current_row, col_end=current_column + 1)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center",
                       underline="single")

    current_column = 16
    ws[f"{num_to_letter(current_column)}{current_row}"] = total_count
    set_border_to_cell(ws, current_column, current_row)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center", )

    current_column += 2
    ws[f"{num_to_letter(current_column)}{current_row}"] = grand_total_amount
    set_border_to_cell(ws, current_column, current_row)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center", )


    gray_fill = PatternFill(
        fill_type="solid",
        start_color="A6A6A6",
        end_color="A6A6A6"
    )

    for cell in ws[current_row]:
        cell.fill = gray_fill

    end_row = current_row

    current_column, current_row = set_revised_signatories(ws, current_column, current_row, dean_name)

    set_number_comma(ws, start_number_column, end_number_column, start_row, end_row)
    set_number_decimal(ws, start_decimal_column, end_decimal_column, start_row, end_row)

    set_revised_dimensions(ws)

    set_border_to_cell(
        ws,
        col_start=start_column,
        row_start=start_row,
        col_end=end_column,
        row_end=end_row
    )

def add_supplemental(wb, fiscal_year, year, dean_name):
    supplementals = private_supabase.table("SUPPLEMENTAL").select("*").eq("FiscalYearID", fiscal_year).execute()
    if not supplementals.data:
        return None
    supplementals = supplementals.data
    for supplemental in supplementals:
        supplemental_id = supplemental["SupplementalID"]
        supplemental_date = pd.to_datetime(supplemental["created_at"])
        title_date = supplemental_date.strftime('%m-%d-%Y')
        default_title = f"Supplemental of {title_date}"
        ws_title = get_unique_sheet_title(wb, default_title)

        ws = wb.create_sheet(ws_title)
        ws.sheet_view.showGridLines = False

        total_count = 0
        grand_total_amount = 0
        start_row = 0
        end_row = 0
        start_column = 1
        end_column = 0
        start_number_column = 0
        end_number_column = 0
        start_decimal_column = 0
        end_decimal_column = 0

        current_row = 2
        current_column = 1
        (
            current_column,
            current_row,
            start_number_column,
            end_number_column,
            start_decimal_column,
            end_decimal_column,
            end_column,
        ) = set_revised_header(ws, current_column, current_row, year)

        ppmp_items = private_supabase.table("ADDITIONAL_SUPPLEMENTAL_ITEM").select("*").eq("SupplementalID", supplemental_id).execute()
        ppmp_items = ppmp_items.data
        if not ppmp_items:
            office_supplies_dict = {}
            office_supplies_dict["Supplemental ABC"] = [
                {
                    "Seq.": 1,
                    "GENERAL DESCRIPTION": "Supplemental ABC",
                    "Unit of Measure": "Peso",
                    "January": supplemental["SupplementalABC"],
                    "TOTAL": supplemental["SupplementalABC"],
                    "Price as per Catalogue": supplemental["SupplementalABC"],
                    "TOTAL AMOUNT": supplemental["SupplementalABC"],
                }
            ]
        else:
            office_supplies = [ppmp_item for ppmp_item in ppmp_items if ppmp_item["PpmpCategory"] == "Office Supply"]

            office_categories = [ppmp_item["ItemCategory"] for ppmp_item in office_supplies]
            office_categories = list(dict.fromkeys(office_categories))
            office_supplies_dict = {}

            for office_category in office_categories:
                category_items = [
                    item
                    for item in office_supplies
                    if item["ItemCategory"] == office_category
                ]

                office_supplies_dict[office_category] = [
                    {
                        "Seq.": i,
                        "GENERAL DESCRIPTION": item["ItemName"],
                        "Unit of Measure": item["UnitName"],
                        "January": item["Quantity"],
                        "TOTAL": item["Quantity"],
                        "Price as per Catalogue": item["UnitPrice"],
                        "TOTAL AMOUNT": item["Quantity"] * item["UnitPrice"],
                    }
                    for i, item in enumerate(category_items, start=1)
                ]

            office_supplies = office_supplies_dict

        office_supplies = office_supplies_dict
        lab_supplies_dict = {}
        lab_supplies = [ppmp_item for ppmp_item in ppmp_items if
                        ppmp_item["PpmpCategory"] == "Laboratory Supply/Equipment"]
        lab_categories = [ppmp_item["ItemCategory"] for ppmp_item in lab_supplies]
        lab_categories = list(dict.fromkeys(lab_categories))

        for lab_category in lab_categories:
            category_items = [
                item
                for item in lab_supplies
                if item["ItemCategory"] == lab_category
            ]

            lab_supplies_dict[lab_category] = [
                {
                    "Seq.": i,
                    "GENERAL DESCRIPTION": item["ItemName"],
                    "Unit of Measure": item["UnitName"],
                    "January": item["Quantity"],
                    "TOTAL": item["Quantity"],
                    "Price as per Catalogue": item["UnitPrice"],
                    "TOTAL AMOUNT": item["Quantity"] * item["UnitPrice"],
                }
                for i, item in enumerate(category_items, start=1)
            ]

        lab_supplies = lab_supplies_dict

        current_row += 2
        current_column = 1

        ws[f"{num_to_letter(current_column)}{current_row}"] = "OFFICE SUPPLIES"
        ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
        set_border_to_cell(ws, current_column, current_row, left=None, right=None, top=None, bottom=None,
                           col_end=current_column + 1)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")

        start_row = current_row
        total_count1, grand_total_amount1 = 0, 0
        total_count2, grand_total_amount2 = 0, 0
        total_count1, grand_total_amount1, current_row = ppmp_item_category(office_supplies, ws, current_row)
        if lab_supplies:
            current_row += 1
            ws[f"{num_to_letter(current_column)}{current_row}"] = "LAB SUPPLIES"
            ws.merge_cells(
                f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
            set_border_to_cell(ws, current_column, current_row, left=None, right=None, top=None, bottom=None,
                               col_end=current_column + 1)
            set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
            total_count2, grand_total_amount2, current_row = ppmp_item_category(lab_supplies, ws, current_row)
        total_count = total_count1 + total_count2
        grand_total_amount = grand_total_amount1 + grand_total_amount2
        current_row += 1
        current_column = 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = "GRAND TOTAL:"
        ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
        set_border_to_cell(ws, current_column, current_row, col_end=current_column + 1)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center",
                           underline="single")

        current_column = 16
        ws[f"{num_to_letter(current_column)}{current_row}"] = total_count
        set_border_to_cell(ws, current_column, current_row)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center", )

        current_column += 2
        ws[f"{num_to_letter(current_column)}{current_row}"] = grand_total_amount
        set_border_to_cell(ws, current_column, current_row)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center", )

        gray_fill = PatternFill(
            fill_type="solid",
            start_color="A6A6A6",
            end_color="A6A6A6"
        )

        for cell in ws[current_row]:
            cell.fill = gray_fill

        end_row = current_row

        current_column, current_row = set_revised_signatories(ws, current_column, current_row, dean_name)

        set_number_comma(ws, start_number_column, end_number_column, start_row, end_row)
        set_number_decimal(ws, start_decimal_column, end_decimal_column, start_row, end_row)

        set_revised_dimensions(ws)

        set_border_to_cell(
            ws,
            col_start=start_column,
            row_start=start_row,
            col_end=end_column,
            row_end=end_row
        )

def add_in_lieus(wb, fiscal_year, year, dean_name):
    in_liues = private_supabase.table("IN_LIEU").select("*").eq("FiscalYearID", fiscal_year).execute()
    if not in_liues.data:
        return None
    in_liues = in_liues.data
    for in_liue in in_liues:
        open_funds_utilized = in_liue["OpenFundsUtilized"]
        in_lieu_date = pd.to_datetime(in_liue["created_at"])
        default_title = f"In Lieu as of {calendar.month_name[in_lieu_date.month]} {in_lieu_date.day}"
        ws_title = get_unique_sheet_title(wb, default_title)

        ws = wb.create_sheet(ws_title)
        ws.sheet_view.showGridLines = False

        in_lieu_additions = private_supabase.table("IN_LIEU_ADDITION").select("*").eq("InLieuID", in_liue["InLieuID"]).execute()
        in_lieu_additions = in_lieu_additions.data
        in_lieu_items = private_supabase.table("IN_LIEU_ITEM").select("QuantityReduced, ItemID").eq("InLieuID", in_liue["InLieuID"]).execute()
        ppmp_items = {}
        if in_lieu_items.data:
            in_lieu_items = in_lieu_items.data
            in_lieu_item_ids = [in_lieu_item["ItemID"] for in_lieu_item in in_lieu_items]
            ppmp_items_response = private_supabase.table("PPMP_ITEM").select("ItemID, ItemName, PricePerUnit").in_("ItemID", in_lieu_item_ids).execute()
            ppmp_items = {
                item["ItemID"]: item
                for item in (ppmp_items_response.data or [])
            }
        else:
            in_lieu_items = []
        if not in_lieu_additions:
            return Response({"error": "No In Lieu Found"}, status=404)

        total_count = 0
        grand_total_amount = 0
        start_row = 0
        end_row = 0
        start_column = 1
        end_column = 0
        start_number_column = 0
        end_number_column = 0
        start_decimal_column = 0
        end_decimal_column = 0


        current_row = 1
        current_column = 1

        ws.merge_cells(f"A{1}:R{1}")
        ws[f"A{1}"] = "REVISED PROJECT PROCUREMENT MANAGEMENT PLAN " + year
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center",)

        current_row = 5
        current_column = 2

        (
            current_column,
            current_row,
            start_number_column,
            end_number_column,
            start_decimal_column,
            end_decimal_column,
            end_column,
        ) = set_in_lieu_header(ws, current_column, current_row)

        start_row = current_row + 1
        current_column = 1
        current_row = add_in_lieu_additions(in_lieu_additions, ws, current_row)
        end_row = current_row
        set_number_comma(ws, start_number_column, end_number_column, start_row, end_row)
        set_number_decimal(ws, start_decimal_column, end_decimal_column, start_row, end_row)

        set_border_to_cell(
            ws,
            col_start=start_column,
            row_start=start_row,
            col_end=end_column,
            row_end=end_row
        )

        (
            current_column,
            current_row,
            start_number_column,
            end_number_column,
            start_decimal_column,
            end_decimal_column,
            end_column,
        ) = add_in_lieu_items(in_lieu_items, ppmp_items, open_funds_utilized, ws, current_row)

        end_row = current_row
        set_number_comma(ws, start_number_column, end_number_column, start_row, end_row)
        set_number_decimal(ws, start_decimal_column, end_decimal_column, start_row, end_row)

        set_in_lieu_dimensions(ws)

        set_border_to_cell(
            ws,
            col_start=start_column,
            row_start=start_row,
            col_end=end_column,
            row_end=end_row
        )

        set_in_lieu_signatories(ws, current_column, current_row, dean_name)


def add_purchase_request(wb, fiscal_year, year, dean_name):
    purchase_requests = private_supabase.table("PURCHASE_REQUEST").select("*").eq("FiscalYearID", fiscal_year).execute()
    if not purchase_requests.data:
        return None
    purchase_requests = purchase_requests.data
    for purchase_request in purchase_requests:
        purchase_request_date = pd.to_datetime(purchase_request["created_at"])

        title_date = purchase_request_date.strftime('%m-%d-%Y')
        purchase_request_date = purchase_request_date.strftime('%m/%d/%Y')

        default_title = f"Purchase Request {title_date}"
        ws_title = get_unique_sheet_title(wb, default_title)

        ws = wb.create_sheet(ws_title)
        # ws.sheet_view.showGridLines = False

        ppmp_item = private_supabase.table("PPMP_ITEM").select("*").eq("ItemID", purchase_request["ItemID"]).maybe_single().execute()
        if not ppmp_item.data:
            return None
        ppmp_item = ppmp_item.data
        purchase_request_dict = {
            "Stock/ Property No.": 1,
            "Unit": ppmp_item["UnitName"],
            "Item Description": ppmp_item["ItemName"],
            "Quantity": purchase_request["RequestQuantity"],
            "Unit Cost": ppmp_item["PricePerUnit"],
            "Total Cost": purchase_request["RequestQuantity"] * ppmp_item["PricePerUnit"]
        }


        start_row = 0
        end_row = 0
        start_column = 1
        end_column = 0
        start_number_column = 0
        end_number_column = 0
        start_decimal_column = 0
        end_decimal_column = 0


        current_row = 1
        current_column = 1

        ws.merge_cells(f"A{1}:G{1}")
        ws[f"A{1}"] = "PURCHASE REQUEST"
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 16, True, False, "center", "center",)

        current_row += 2
        (
            current_column,
            current_row,
            start_number_column,
            end_number_column,
            start_decimal_column,
            end_decimal_column,
            end_column,
        ) = set_purchase_request_header(ws, current_column, current_row, purchase_request_date)

        start_row = current_row
        current_row, table_end = add_purchase_requests(purchase_request_dict, ws, current_row)
        end_row = current_row

        set_number_comma(ws, start_number_column, end_number_column, start_row, table_end)
        set_number_decimal(ws, start_decimal_column, end_decimal_column, start_row, table_end)

        set_border_to_cell(
            ws,
            col_start=start_column,
            row_start=start_row,
            col_end=end_column,
            row_end=table_end
        )
        start_signatories_row, end_signatories_row, start_requested_column, end_requested_column, start_approved_column, end_approved_column = set_purchase_request_signatories(
            ws, current_column, current_row, dean_name, year)

        set_purchase_request_dimensions(ws)
        purchase_request_borders(ws, end_column, end_row, start_signatories_row, end_signatories_row, start_requested_column, end_requested_column, start_approved_column, end_approved_column)

def add_dashboard_report(wb, fiscal_year, year):
    current_row = 2
    current_column = 2
    title = f"{year} Dashboard Reports"
    ws_title = get_unique_sheet_title(wb, title)

    ws = wb.create_sheet(ws_title)

    ws[f"{num_to_letter(current_column)}{current_row}"] = "DASHBOARD SUMMARY"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 16, True, False, "left", "center", )

    current_row = set_dashboard_summary_header(ws, current_row)
    current_row = add_dashboard_summaries(ws, year, current_row)
    current_row = set_category_allocation_header(ws, current_row)
    current_row = add_category_allocation(ws, fiscal_year, year, current_row)
    set_dashboard_report_dimensions(ws)

def num_to_letter(num):
    return chr(num + 64)

def letter_to_num(letter):
    return ord(letter.upper()) - 64


def set_format_to_cell(ws, column, row, font, size, bold, italic, horizontal, vertical, underline=None, wrap_text=False):
    ws[f"{num_to_letter(column)}{row}"].font = Font(bold=bold, italic=italic, underline=underline, name=font, size=size)
    ws[f"{num_to_letter(column)}{row}"].alignment = Alignment(horizontal=horizontal, vertical=vertical, wrap_text=wrap_text)

def set_border_to_cell(ws, col_start, row_start,
                       col_end=None, row_end=None,
                       left="thin", right="thin", top="thin", bottom="thin"):
    col_end = col_end or col_start
    row_end = row_end or row_start

    for r in range(row_start, row_end + 1):
        for c in range(col_start, col_end + 1):
            border = Border(
                left=Side(style=left) if c == col_start else Side(style="thin"),
                right=Side(style=right) if c == col_end else Side(style="thin"),
                top=Side(style=top) if r == row_start else Side(style="thin"),
                bottom=Side(style=bottom) if r == row_end else Side(style="thin"),
            )
            ws.cell(row=r, column=c).border = border

def set_bottom_border(ws, col_start, row, col_end=None, style="thin"):
    col_end = col_end or col_start

    for c in range(col_start, col_end + 1):
        ws.cell(row=row, column=c).border = Border(
            bottom=Side(style=style)
        )

def hide_cell(ws, current_row):
    ws.row_dimensions[current_row].height = 5

def set_number_comma(ws, start_column, end_column, start_row, end_row):
    for i in range(start_row, end_row + 1):
        for j in range(start_column, end_column + 1):
            ws[f"{num_to_letter(j)}{i}"].number_format = '#,##0'

def set_number_decimal(ws, start_column, end_column, start_row, end_row, decimal_number=2):
    for i in range(start_row, end_row + 1):
        for j in range(start_column, end_column + 1):
            ws[f"{num_to_letter(j)}{i}"].number_format = '#,##0.' + ("0" * decimal_number)

def set_revised_dimensions(ws):
    current_column = 1
    ws.column_dimensions[num_to_letter(current_column)].width = 5
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 45
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 20
    current_column += 1
    for i in range(12):
        if i is 8:
            ws.column_dimensions[num_to_letter(current_column)].width = 13
        elif i > 8:
            ws.column_dimensions[num_to_letter(current_column)].width = 9
        else:
            ws.column_dimensions[num_to_letter(current_column)].width = 8
        current_column += 1

    ws.column_dimensions[num_to_letter(current_column)].width = 16
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 15
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 19
    current_column += 1

    for row in range(1, ws.max_row + 1):
        ws.row_dimensions[row].height = 20
    return

def set_in_lieu_dimensions(ws):
    current_column = 1
    ws.column_dimensions[num_to_letter(current_column)].width = 4
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 33
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 20
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 13
    current_column += 1
    for i in range(12):
        ws.column_dimensions[num_to_letter(current_column)].width = 8
        current_column += 1

    ws.column_dimensions[num_to_letter(current_column)].width = 14
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 24

def set_purchase_request_dimensions(ws):
    current_column = 1
    ws.column_dimensions[num_to_letter(current_column)].width = 10
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 9
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 14
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 29
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 13
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 15
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 21

def set_dashboard_report_dimensions(ws):
    current_column = 2
    ws.column_dimensions[num_to_letter(current_column)].width = 40
    current_column += 1
    ws.column_dimensions[num_to_letter(current_column)].width = 20

def set_revised_header(ws, current_column, current_row, year):
    ws.merge_cells(f"A{current_row}:R{current_row}")
    ws[f"A{current_row}"] = "PROJECT PROCUREMENT MANAGEMENT PLAN (PPMP) " + year
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    ws.column_dimensions[num_to_letter(current_column)].width = 20
    current_row += 1
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
    set_border_to_cell(ws, current_column, current_row, row_end=current_row + 2)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "GENERAL DESCRIPTION"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    set_border_to_cell(ws, current_column, current_row, row_end=current_row + 2)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Unit of Measure"
    set_border_to_cell(ws, current_column, current_row, row_end=current_row + 2)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Number of Units Needed"
    set_border_to_cell(ws, current_column, current_row, col_end=current_column + 11)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column = 16
    ws[f"{num_to_letter(current_column)}{current_row}"] = "TOTAL"
    set_border_to_cell(ws, current_column, current_row, row_end=current_row + 2)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Price as per \nCatalogue"
    set_border_to_cell(ws, current_column, current_row, row_end=current_row + 2)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center",
                       wrap_text=True)
    start_decimal_column = current_column
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "TOTAL AMOUNT"
    set_border_to_cell(ws, current_column, current_row, row_end=current_row + 2)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    end_decimal_column = current_column
    end_number_column = current_column
    end_column = current_column

    current_row += 1
    current_column = 4
    start_number_column = current_column

    months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December"]
    column_width = 8
    for i in range(0, len(months)):
        if i == 8:
            column_width = 13
        if i < 8:
            column_width = 9
        ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column)}{current_row + 1}")
        ws[f"{num_to_letter(current_column)}{current_row}"] = months[i]
        set_border_to_cell(ws, current_column, current_row, row_end=current_row + 1)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
        current_column += 1

    return (
        current_column,
        current_row,
        start_number_column,
        end_number_column,
        start_decimal_column,
        end_decimal_column,
        end_column,
    )

def set_in_lieu_header(ws, current_column, current_row):

    ws[f"{num_to_letter(current_column)}{current_row}"] = "END-USER/UNIT: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "CICT"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center")
    set_bottom_border(ws, current_column, current_row, col_end=current_column + 3)
    current_column -= 1
    current_row += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "SOURCE OF FUND: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = ""
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center")
    set_bottom_border(ws, current_column, current_row, col_end=current_column + 3)



    current_column = 1
    current_row += 2

    ws.merge_cells("A8:A9")
    ws.merge_cells("B8:B9")
    ws.merge_cells("C8:C9")
    ws.merge_cells("D8:P8")
    ws.merge_cells("Q8:Q9")
    ws.merge_cells("R8:R9")

    ws[f"{num_to_letter(current_column)}{current_row}"] = "NO."
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    set_border_to_cell(ws, current_column, current_row, row_end=current_row + 1)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "GENERAL DESCRIPTION"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    set_border_to_cell(ws, current_column, current_row, row_end=current_row + 1)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "UNIT OF MEASUREMENT"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    set_border_to_cell(ws, current_column, current_row, row_end=current_row + 1)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "SCHEDULE/MILESTONES OF ACTIVITIES"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    set_border_to_cell(ws, current_column, current_row,col_end=current_column + 13)
    current_column += 13
    start_decimal_column = current_row
    ws[f"{num_to_letter(current_column)}{current_row}"] = "PRICE \nCATALOGUE"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center", wrap_text=True)
    set_border_to_cell(ws, current_column, current_row, row_end=current_row + 1)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "AMOUNT"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    set_border_to_cell(ws, current_column, current_row, row_end=current_row + 1)
    end_number_column = current_column
    end_decimal_column = current_row
    end_column = current_column

    current_row += 1
    current_column = 4
    start_number_column = current_column

    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "TOTAL"]
    column_width = 8
    for i in range(0, len(months)):
        if i == 8:
            column_width = 13
        if i < 8:
            column_width = 9
        ws[f"{num_to_letter(current_column)}{current_row}"] = months[i]
        set_border_to_cell(ws, current_column, current_row, )
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
        current_column += 1
    return (
        current_column,
        current_row,
        start_number_column,
        end_number_column,
        start_decimal_column,
        end_decimal_column,
        end_column,
    )


def set_purchase_request_header(ws, current_column, current_row, date):
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Entity Name: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center")
    current_column += 2

    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = "BULACAN STATE UNIVERSITY "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center")
    set_bottom_border(ws, current_column, current_row, col_end=current_column + 1)
    current_column += 2

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Fund Cluster: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center")
    current_column += 1
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    set_bottom_border(ws, current_column, current_row, col_end=current_column + 1)

    current_row += 1
    hide_cell(ws, current_row)

    current_column = 1
    current_row += 1

    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Office/ Section: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center")
    current_column += 2

    ws[f"{num_to_letter(current_column)}{current_row}"] = "PR No.: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center")
    current_column += 1
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    set_bottom_border(ws, current_column, current_row, col_end=current_column + 1)
    current_column += 2

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Date: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "right", "center")
    current_column += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = date
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")
    set_bottom_border(ws, current_column, current_row)
    current_column += 1

    current_column = 3
    current_row += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Responsibility Center Code: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", wrap_text=True)
    current_column += 1
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    set_bottom_border(ws, current_column, current_row, col_end=current_column + 1)
    current_row += 1
    hide_cell(ws, current_row)

    current_column = 1
    current_row += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Stock/ \nProperty \nNo. "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center",    wrap_text=True)
    current_column += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Unit"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column += 1

    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Item Description"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column += 2

    start_number_column = current_column
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Quantity"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column += 1


    start_decimal_column = current_column
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Unit Cost"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    current_column += 1

    end_number_column = current_column
    end_decimal_column = current_column
    end_column = current_column
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Total Cost"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")

    return (
        current_column,
        current_row,
        start_number_column,
        end_number_column,
        start_decimal_column,
        end_decimal_column,
        end_column,
    )

def set_dashboard_summary_header(ws, current_row):
    header_fill = PatternFill(
        fill_type="solid",
        fgColor="76232F"
    )
    header_font = Font(
        bold=True,
        color="FFFFFF"
    )

    current_column = 2
    current_row += 2
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Category: "
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, True, False, "left", "center")
    ws[f"{num_to_letter(current_column)}{current_row}"].fill = header_fill
    ws[f"{num_to_letter(current_column)}{current_row}"].font = header_font

    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Total Allocation (PHP)"
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, True, False, "left", "center")
    ws[f"{num_to_letter(current_column)}{current_row}"].fill = header_fill
    ws[f"{num_to_letter(current_column)}{current_row}"].font = header_font

    return current_row

def set_category_allocation_header(ws, current_row):
    header_fill = PatternFill(
        fill_type="solid",
        fgColor="76232F"
    )
    header_font = Font(
        bold=True,
        color="FFFFFF"
    )

    current_column = 2
    current_row += 2
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Category: "
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, True, False, "left", "center")
    ws[f"{num_to_letter(current_column)}{current_row}"].fill = header_fill
    ws[f"{num_to_letter(current_column)}{current_row}"].font = header_font

    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Total Allocation (PHP)"
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, True, False, "left", "center")
    ws[f"{num_to_letter(current_column)}{current_row}"].fill = header_fill
    ws[f"{num_to_letter(current_column)}{current_row}"].font = header_font

    return current_row


def set_revised_signatories(ws, current_column, current_row, dean_name):

    current_row += 2
    current_column = 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "NOTE: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", underline="single")

    current_row += 1
    current_column = 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "1. "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center",)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Provide all necessary information."
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_row += 1
    current_column = 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "2. "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center",)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Several items may not be included in BulSU's consolidated catalogue. Thus, you may need provide your own description and estimated cost."
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_row += 1
    current_column = 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "3. "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center",)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Items that are included in previous years PPMP that were not procured and that are needed in CY2024 may be included in this PPMP."
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_row += 1
    current_column = 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "4. "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center",)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "The drop down list in column B may help guide the preparer of this PPMP to find the items needed by the colleges and offices. Nonetheless, the prepare may manually search in the Catalogue Sheet of this PPMP form."
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_row += 1
    current_column = 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "5. "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center",)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = 'Kindly delete all " #N/A " remarks once done to prevent summazation error.'
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_row += 1
    current_column = 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "6. "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center",)
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "For events, kindly include only the materials which will used."
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )
    current_column = 1


    current_row += 2
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Prepared by:"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_column += 2
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Noted by:"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_column += 5
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Recommending Approval:"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_column += 4
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Approved by:"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    ppmp_signatories = private_supabase.table("DOCUMENT_SIGNATORY").select("*").eq("DocumentType", "APPROVED PPMP").execute()
    if ppmp_signatories is None:
        return None

    ppmp_signatories = ppmp_signatories.data

    current_row += 2
    current_column = 1


    ws[f"{num_to_letter(current_column)}{current_row}"] = dean_name
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center", )

    current_column += 2

    budget_officer = [
        signatory["FullName"] for signatory in ppmp_signatories if signatory["PositionTitle"] == "Budget Officer"
    ]
    if budget_officer:
        budget_officer = budget_officer[0]
    else:
        budget_officer = None
    ws[f"{num_to_letter(current_column)}{current_row}"] = budget_officer
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center", )


    current_column += 5

    chancellor = [
        signatory["FullName"] for signatory in ppmp_signatories if signatory["PositionTitle"] == "Chancellor, Main Campus"
    ]
    if chancellor:
        chancellor = chancellor[0]
    else:
        chancellor = None
    ws[f"{num_to_letter(current_column)}{current_row}"] = chancellor
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center", )

    current_column += 4

    pres = [
        signatory["FullName"] for signatory in ppmp_signatories if signatory["PositionTitle"] == "University President"
    ]
    if pres:
        pres = pres[0]
    else:
        pres = None
    ws[f"{num_to_letter(current_column)}{current_row}"] = pres
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center", )

    current_column = 1
    current_row += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "End-user"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_column += 2
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Budget Officer"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_column += 5
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Chancellor, Main Campus"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_column += 4
    ws[f"{num_to_letter(current_column)}{current_row}"] = "University President"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    return current_column, current_row

def set_in_lieu_signatories(ws, current_column, current_row, dean_name):
    current_row += 2
    current_column = 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Submitted by: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center",)

    current_column += 11
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Noted by: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    ppmp_signatories = private_supabase.table("DOCUMENT_SIGNATORY").select("*").eq("DocumentType", "REVISED PPMP").execute()
    if ppmp_signatories is None:
        return None

    ppmp_signatories = ppmp_signatories.data

    current_row += 4
    current_column = 2
    ws[f"{num_to_letter(current_column)}{current_row}"] = dean_name
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center", )

    current_column += 2

    head_asset = [
        signatory["FullName"] for signatory in ppmp_signatories if signatory["PositionTitle"] == "Head, Asset Management Unit"
    ]
    if head_asset:
        head_asset = head_asset[0]
    else:
        head_asset = None
    ws[f"{num_to_letter(current_column)}{current_row}"] = head_asset
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center", )

    current_column += 4

    head_procurement = [
        signatory["FullName"] for signatory in ppmp_signatories if signatory["PositionTitle"] == "Head, Procurement Unit"
    ]
    if head_procurement:
        head_procurement = head_procurement[0]
    else:
        head_procurement = None
    ws[f"{num_to_letter(current_column)}{current_row}"] = head_procurement
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center", )

    current_column += 4

    budget_officer = [
        signatory["FullName"] for signatory in ppmp_signatories if signatory["PositionTitle"] == "Budget Officer"
    ]
    if budget_officer:
        budget_officer = budget_officer[0]
    else:
        budget_officer = None
    ws[f"{num_to_letter(current_column)}{current_row}"] = budget_officer
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center", )

    current_row += 1
    current_column = 2

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Dean, CICT"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_column += 2

    head_asset = [
        signatory["PositionTitle"] for signatory in ppmp_signatories if
        signatory["PositionTitle"] == "Head, Asset Management Unit"
    ]
    if head_asset:
        head_asset = head_asset[0]
    else:
        head_asset = None
    ws[f"{num_to_letter(current_column)}{current_row}"] = head_asset
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_column += 4

    head_procurement = [
        signatory["PositionTitle"] for signatory in ppmp_signatories if
        signatory["PositionTitle"] == "Head, Procurement Unit"
    ]
    if head_procurement:
        head_procurement = head_procurement[0]
    else:
        head_procurement = None
    ws[f"{num_to_letter(current_column)}{current_row}"] = head_procurement
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    current_column += 4

    budget_officer = [
        signatory["PositionTitle"] for signatory in ppmp_signatories if signatory["PositionTitle"] == "Budget Officer"
    ]
    if budget_officer:
        budget_officer = budget_officer[0]
    else:
        budget_officer = None
    ws[f"{num_to_letter(current_column)}{current_row}"] = budget_officer
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

def set_purchase_request_signatories(ws, current_column, current_row, dean_name, year):
    ppmp_signatory = private_supabase.table("DOCUMENT_SIGNATORY").select("*").eq("DocumentType", "PURCHASE REQUEST").maybe_single().execute()
    if ppmp_signatory is None:
        return None

    ppmp_signatory = ppmp_signatory.data
    current_row += 1
    hide_cell(ws, current_row)
    start_signatories_row = current_row

    current_row += 1
    current_column = 1
    start_requested_column = current_column
    end_requested_column = current_column + 3
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 3)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Requested by: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center", )

    current_column += 4
    start_approved_column = current_column
    end_approved_column = current_column + 2
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 2)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Approved by: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center", )

    current_row += 1
    current_column = 1
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Signature: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center", )
    current_column += 2
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    set_bottom_border(ws, current_column, current_row, col_end=current_column + 1)

    current_row += 1
    current_column = 1
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Printed by: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center", )
    current_column += 2

    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = dean_name
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center", )
    current_column += 2

    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 2)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = ppmp_signatory["FullName"]
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center", )

    current_row += 1
    current_column = 1
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Designation: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center", )
    current_column += 2

    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Dean, CICT"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, True, "center", "center", )
    current_column += 2

    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 2)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = ppmp_signatory["PositionTitle"]
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center", )
    current_row += 1
    hide_cell(ws, current_row)
    end_signatories_row = current_row

    current_row += 2
    current_column = 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "To be accomplished by the Procurement Office:"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, True, "left", "center", )

    current_row += 2
    current_column = 1
    includeds = [f"☐ {year} Annual Procurement Plan", f"☐ {year} Supplemental PPMP", f"☐ {year} Revised PPMP"]
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Included in the:"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

    for i in range(len(includeds)):
        current_column = 3
        ws[f"{num_to_letter(current_column)}{current_row}"] = includeds[i]
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

        current_column += 2
        ws[f"{num_to_letter(current_column)}{current_row}"] = "Item No.:_____"
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

        current_column += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = "Page No.:_____"
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", )

        current_column += 1
        if i == 0:
            ws[f"{num_to_letter(current_column)}{current_row}"] = "PROCUREMENT OFFICER"
            set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center", )

        current_row += 1

    return start_signatories_row, end_signatories_row, start_requested_column, end_requested_column, start_approved_column, end_approved_column


def ppmp_item_category(ppmp_category, ws, current_row):
    total_count = 0
    grand_total_amount = 0
    for item_category, items in ppmp_category.items():
        current_row += 1
        current_column = 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = item_category
        ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
        set_border_to_cell(ws, current_column, current_row, col_end=current_column + 1)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, True, "center", "center")
        category_total_count = 0
        category_grand_total_amount = 0
        for ppmp_item in items:
            current_row += 1
            current_column = 1
            ws[f"{num_to_letter(current_column)}{current_row}"] = ppmp_item["Seq."]
            set_border_to_cell(ws, current_column, current_row)
            set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")

            current_column += 1
            ws[f"{num_to_letter(current_column)}{current_row}"] = ppmp_item["GENERAL DESCRIPTION"]
            set_border_to_cell(ws, current_column, current_row)
            set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", wrap_text=True)

            current_column += 1
            ws[f"{num_to_letter(current_column)}{current_row}"] = ppmp_item["Unit of Measure"]
            set_border_to_cell(ws, current_column, current_row)
            set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")

            current_column += 1
            ws[f"{num_to_letter(current_column)}{current_row}"] = ppmp_item["January"]
            set_border_to_cell(ws, current_column, current_row)
            set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")

            current_column += 1
            for i in range(11):
                ws[f"{num_to_letter(current_column)}{current_row}"] = ""
                set_border_to_cell(ws, current_column, current_row)
                set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")
                current_column += 1

            ws[f"{num_to_letter(current_column)}{current_row}"] = ppmp_item["TOTAL"]
            set_border_to_cell(ws, current_column, current_row)
            set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")
            category_total_count += ppmp_item["TOTAL"]
            total_count += ppmp_item["TOTAL"]

            current_column += 1
            ws[f"{num_to_letter(current_column)}{current_row}"] = ppmp_item["Price as per Catalogue"]
            set_border_to_cell(ws, current_column, current_row)
            set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "right", "center", wrap_text=True)

            current_column += 1
            ws[f"{num_to_letter(current_column)}{current_row}"] = ppmp_item["TOTAL AMOUNT"]
            set_border_to_cell(ws, current_column, current_row)
            set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "right", "center")
            category_grand_total_amount += ppmp_item["TOTAL AMOUNT"]
            grand_total_amount += ppmp_item["TOTAL AMOUNT"]

        current_row += 1
        current_column = 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = "Subtotal:"
        ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
        set_border_to_cell(ws, current_column, current_row, col_end=current_column + 1)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, True, "center", "center",)

        current_column += 3
        ws[f"{num_to_letter(current_column)}{current_row}"] = category_total_count
        set_border_to_cell(ws, current_column, current_row)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center", )

        current_column = 16
        ws[f"{num_to_letter(current_column)}{current_row}"] = category_total_count
        set_border_to_cell(ws, current_column, current_row)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center", )

        current_column += 2
        ws[f"{num_to_letter(current_column)}{current_row}"] = category_grand_total_amount
        set_border_to_cell(ws, current_column, current_row)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center", )

    return total_count, grand_total_amount, current_row

def add_in_lieu_additions(additions, ws, current_row):
    additions_list = []
    total_count = 0
    grand_total_amount = 0
    current_column = 1
    for i, addition in enumerate(additions):
        total_count += addition["Quantity"]
        grand_total_amount += addition["Quantity"] * addition["UnitPrice"]
        additions_list.append({
            "NO.": i + 1,
            "GENERAL DESCRIPTION": addition["ItemName"],
            "UNIT OF MEASUREMENT": addition["UnitName"],
            "JAN": addition["Quantity"],
            "TOTAL": addition["Quantity"],
            "PRICE CATALOGUE": addition["UnitPrice"],
            "AMOUNT": addition["Quantity"] * addition["UnitPrice"],
        })


    for addition in additions_list:
        current_row += 1
        current_column = 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = addition["NO."]
        set_border_to_cell(ws, current_column, current_row)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")

        current_column += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = addition["GENERAL DESCRIPTION"]
        set_border_to_cell(ws, current_column, current_row)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", wrap_text=True)

        current_column += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = addition["UNIT OF MEASUREMENT"]
        set_border_to_cell(ws, current_column, current_row)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")

        current_column += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = addition["JAN"]
        set_border_to_cell(ws, current_column, current_row)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")

        current_column += 13
        ws[f"{num_to_letter(current_column)}{current_row}"] = addition["PRICE CATALOGUE"]
        set_border_to_cell(ws, current_column, current_row)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "right", "center")

        current_column += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = addition["AMOUNT"]
        set_border_to_cell(ws, current_column, current_row)
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "right", "center")

    current_row += 1
    current_column = 1
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 1)}{current_row}")
    ws[f"{num_to_letter(current_column)}{current_row}"] = "TOTAL AMOUNT"
    set_border_to_cell(ws, current_column, current_row, col_end=current_column + 1)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "right", "center")

    current_column += 15
    ws[f"{num_to_letter(current_column)}{current_row}"] = total_count
    set_border_to_cell(ws, current_column, current_row)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")

    current_column += 2
    ws[f"{num_to_letter(current_column)}{current_row}"] = grand_total_amount
    set_border_to_cell(ws, current_column, current_row)
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "center", "center")
    gray_fill = PatternFill(
        fill_type="solid",
        start_color="D8D8D8",
        end_color="D8D8D8"
    )
    for cell in ws[current_row]:
        cell.fill = gray_fill
    return current_row


def add_in_lieu_items(in_lieu_items, ppmp_items, open_funds_utilized, ws, current_row):
    grand_total = 0

    in_lieu_item_list = []

    for in_lieu_item in in_lieu_items:
        ppmp_item = ppmp_items.get(in_lieu_item["ItemID"])

        if ppmp_item is None:
            continue

        in_lieu_item_list.append({
            "ItemName": ppmp_item["ItemName"],
            "PricePerUnit": ppmp_item["PricePerUnit"],
            "QuantityReduced": in_lieu_item["QuantityReduced"],
        })

    current_row += 1
    current_column = 2
    ws[f"{num_to_letter(current_column)}{current_row}"] = "in lieu of"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")

    current_row += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Item"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center")

    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Price as per catalogue"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center")
    start_decimal_column = current_column

    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Total"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "left", "center")
    end_number_column = current_column
    end_decimal_column = current_column
    end_column = current_column

    current_column = 1
    start_number_column = current_column

    for in_lieu_item in in_lieu_item_list:
        current_row += 1
        current_column = 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = in_lieu_item["QuantityReduced"]
        set_format_to_cell(ws, current_column, current_row, "Tahoma", 10, False, False, "left", "center")

        current_column += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = in_lieu_item["ItemName"]
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center", wrap_text=True)

        current_column += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = in_lieu_item["PricePerUnit"]
        set_format_to_cell(ws, current_column, current_row, "Tahoma", 10, False, False, "right", "center")

        current_column += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = float(in_lieu_item["QuantityReduced"]) * float(in_lieu_item["PricePerUnit"])
        set_format_to_cell(ws, current_column, current_row, "Tahoma", 10, False, False, "right", "center")
        grand_total += float(in_lieu_item["QuantityReduced"]) * float(in_lieu_item["PricePerUnit"])

    if not in_lieu_items or not ppmp_items:
        current_row += 1
        current_column = 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = 1
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center")

        current_column += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = "Open Funds"
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center")

        current_column += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = open_funds_utilized
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "right", "center")

        current_column += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = open_funds_utilized
        set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "right", "center")
        grand_total += open_funds_utilized

    current_row += 1
    current_column = 3
    ws[f"{num_to_letter(current_column)}{current_row}"] = "TOTAL:"
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "right", "center")

    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = grand_total
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "right", "center")

    return (
        current_column,
        current_row,
        start_number_column,
        end_number_column,
        start_decimal_column,
        end_decimal_column,
        end_column,
    )

def add_purchase_requests(purchase_request, ws, current_row):

    current_row += 1
    current_column = 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = purchase_request["Stock/ Property No."]
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")
    current_column += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = purchase_request["Unit"]
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")
    current_column += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = purchase_request["Item Description"]
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")
    current_column += 2

    ws[f"{num_to_letter(current_column)}{current_row}"] = purchase_request["Quantity"]
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "center", "center")
    current_column += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = purchase_request["Unit Cost"]
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "right", "center")
    current_column += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = purchase_request["Total Cost"]
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "right", "center")
    current_column += 1

    current_row += 1
    current_column = 7

    ws[f"{num_to_letter(current_column)}{current_row}"] = purchase_request["Total Cost"]
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, True, False, "right", "center")
    table_end_row = current_row

    current_row += 1
    current_column = 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Purpose: "
    set_format_to_cell(ws, current_column, current_row, "Arial Narrow", 10, False, False, "left", "center")
    current_column += 1
    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 5)}{current_row}")
    set_bottom_border(ws, current_column, current_row, col_end=current_column + 5)

    current_row += 1
    current_column = 2

    ws.merge_cells(f"{num_to_letter(current_column)}{current_row}:{num_to_letter(current_column + 5)}{current_row}")
    set_bottom_border(ws, current_column, current_row, col_end=current_column + 5)
    current_column = 1
    current_row += 1
    hide_cell(ws, current_row)

    return current_row, table_end_row

def add_dashboard_summaries(ws, year, current_row):
    (total_annual_budget, committed_funds, available_lieu_pool_funds, open_funds, requested_funds,
     arrived_funds, pending_in_lieu_count) = get_dashboard_cards(year)
    current_column = 2
    current_row += 1

    start_row = current_row
    ws[f"{num_to_letter(current_column)}{current_row}"] = "Total Annual Budget"
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "left", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = total_annual_budget
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "right", "center")
    current_column = 2
    current_row += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Committed Funds"
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "left", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = committed_funds
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "right", "center")
    current_column = 2
    current_row += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Available Lieu Pool"
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "left", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = available_lieu_pool_funds
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "right", "center")
    current_column = 2
    current_row += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Open Funds"
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "left", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = open_funds
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "right", "center")
    current_column = 2
    current_row += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Purchase Request"
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "left", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = requested_funds
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "right", "center")
    current_column = 2
    current_row += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Fulfilled Items"
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "left", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = arrived_funds
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "right", "center")
    current_column = 2
    current_row += 1

    ws[f"{num_to_letter(current_column)}{current_row}"] = "Pending In Lieu Approval"
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "left", "center")
    current_column += 1
    ws[f"{num_to_letter(current_column)}{current_row}"] = pending_in_lieu_count
    set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "right", "center")

    set_number_comma(ws, current_column, current_column, start_row, current_row)
    set_number_decimal(ws, current_column, current_column, start_row, current_row)

    return current_row

def add_category_allocation(ws, fiscal_year, year, current_row):
    allocations = private_supabase.table("PPMP_ITEM").select("ItemCategory", "PlannedQuantity", "PricePerUnit").eq("FiscalYearID", fiscal_year).execute()
    allocations = allocations.data

    allocations_sum = {}

    for allocation in allocations:
        category = allocation["ItemCategory"]
        quantity = allocation["PlannedQuantity"]
        price = allocation["PricePerUnit"]
        amount = quantity * price

        allocations_sum[category] = allocations_sum.get(category, 0) + amount

    sorted_allocations = sorted(allocations_sum.items(), key=lambda item: item[1], reverse=True)

    start_row = current_row
    for category, value in sorted_allocations:
        current_column = 2
        current_row += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = category
        set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "left", "center")
        current_column += 1
        ws[f"{num_to_letter(current_column)}{current_row}"] = value
        set_format_to_cell(ws, current_column, current_row, "Calibri", 11, False, False, "right", "center")


    set_number_comma(ws, current_column, current_column, start_row, current_row)
    set_number_decimal(ws, current_column, current_column, start_row, current_row)

    bar_chart = BarChart()

    bar_chart.type = "col"
    bar_chart.grouping = "clustered"
    bar_chart.style = 2

    bar_chart.title = f"{year} Budget Allocation by Category"
    bar_chart.y_axis.title = "Total Amount (PHP)"
    bar_chart.x_axis.title = "Category"

    bar_chart.x_axis.delete = False
    bar_chart.y_axis.delete = False

    bar_chart.y_axis.numFmt = '#,##0.00'
    bar_chart.y_axis.majorGridlines = bar_chart.y_axis.majorGridlines

    bar_chart.x_axis.txPr = RichText(
        bodyPr=RichTextProperties(rot=-2700000, vert="horz"),
        p=[Paragraph(pPr=ParagraphProperties(defRPr=CharacterProperties()), endParaRPr=CharacterProperties())],
    )

    data = Reference(ws, min_col=3, min_row=start_row + 1, max_row=current_row)
    categories = Reference(ws, min_col=2, min_row=start_row + 1, max_row=current_row)

    bar_chart.add_data(data, titles_from_data=False)
    bar_chart.set_categories(categories)

    bar_chart.series[0].tx = SeriesLabel(v="Total Allocation (PHP)")
    bar_chart.legend.position = "r"  # use `bar_chart.legend = None` to hide it
    bar_chart.legend = None
    bar_chart.title.overlay = False
    bar_chart.layout = Layout(
        manualLayout=ManualLayout(
            layoutTarget="inner",
            xMode="edge", yMode="edge",
            x=0.14,
            y=0.10,
            w=0.80,
            h=0.80
        )
    )

    bar_chart.gapWidth = 40
    bar_chart.varyColors = False

    bar_chart.height = 12
    bar_chart.width = 16

    ws.add_chart(bar_chart, f"E{start_row}")

    return current_row



def get_unique_sheet_title(wb, title):
    if title not in wb.sheetnames:
        return title

    count = 1
    while f"{title} ({count})" in wb.sheetnames:
        count += 1

    return f"{title} ({count})"

def purchase_request_borders(ws, end_column, end_row, start_signatories_row, end_signatories_row, start_requested_column, end_requested_column, start_approved_column, end_approved_column):
    add_outer_border(ws, f"A5:B7", style="medium")
    add_outer_border(ws, f"C5:E7", style="medium")
    add_outer_border(ws, f"F5:G7", style="medium")
    add_outer_border(ws, f"{num_to_letter(start_requested_column)}{start_signatories_row}:{num_to_letter(end_requested_column)}{end_signatories_row}", style="medium")
    add_outer_border(ws, f"{num_to_letter(start_approved_column)}{start_signatories_row}:{num_to_letter(end_approved_column)}{end_signatories_row}", style="medium")
    add_outer_border(ws, f"A1:{num_to_letter(end_column)}{end_row}", style="medium")


def add_outer_border(ws, cell_range, style="thin", color="000000"):
    print("Border range:", cell_range)

    side = Side(style=style, color=color)

    rows = ws[cell_range]

    print("Rows:", rows)


    min_row = rows[0][0].row
    max_row = rows[-1][0].row
    min_col = rows[0][0].column
    max_col = rows[0][-1].column

    for row in rows:
        for cell in row:
            cell.border = Border(
                left=side if cell.column == min_col else cell.border.left,
                right=side if cell.column == max_col else cell.border.right,
                top=side if cell.row == min_row else cell.border.top,
                bottom=side if cell.row == max_row else cell.border.bottom,
            )
