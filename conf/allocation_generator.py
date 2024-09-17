from conf.toml_editor import TomlEditor
from conf.read_spread import read_sheet
import os


ALLOCATION_FILE = "allocation.csv"


path = "/home/noam/theta/yakir"
account_name = os.path.basename(path)
read_sheet(account_name)
