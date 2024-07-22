import gspread
from oauth2client.service_account import ServiceAccountCredentials


def read_sheet(sheet_name)->str:
    """Reads data from a Google Sheet and prints it to the screen.

    Args:
      sheet_name: The name of the sheet to read.
    """
    # Define the Google Sheet ID (replace with your actual ID)
    spreadsheet_key = "1-TQCeBYF6qzcMwZNtmA1y_6b1A3vpkuk66VHdshPg4Y"

    # Use Service Account for authentication (replace with your credentials file)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials_file = "lin-sum.json"  # Replace with your credentials file path
    creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_file, scope)

    # Open the spreadsheet
    client = gspread.authorize(creds)
    sheet = client.open_by_key(spreadsheet_key).worksheet(sheet_name)

    # Get all values from the sheet
    data = sheet.get_all_values()

    # Print the data
    sectors = {}
    for row in data:
        if row[0]:
            print(row[0])
            sectors[row[0]]={"margin":row[1]}
            current_sector = sectors[row[0]]
        else:
            current_sector[row[2]] = row[3]

    print(sectors)
    return sectors

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python script.py <sheet_name>")
        sys.exit(1)
    sheet_name = sys.argv[1]
    read_sheet(sheet_name)
