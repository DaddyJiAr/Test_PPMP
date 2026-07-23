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
from api.utils import private_supabase

response = private_supabase.table("PPMP_ITEM").select("*").eq("ItemID", 69).execute()
print(response.data)