import toml


class TomlEditor:
  """
  A class to edit TOML files.
  """

  def __init__(self, file_path):
    self.file_path = file_path
    self.data = {}

  def load(self):
    """
    Loads the TOML data from the file.
    """
    try:
      with open(self.file_path, "rb") as f:
        self.data = toml.load(f)
    except FileNotFoundError:
      raise FileNotFoundError(f"TOML file not found: {self.file_path}")

  def add(self, key, value, table=None):
    """
    Adds a new key-value pair.

    Args:
        key (str): The key to add.
        value: The value to associate with the key.
        table (str, optional): The table name for the key within a table. Defaults to None (top-level).
    """
    if table:
      if table not in self.data:
        self.data[table] = {}
      self.data[table][key] = value
    else:
      self.data[key] = value

  def update(self, key, value, table=None):
    """
    Updates the value for an existing key.

    Args:
        key (str): The key to update.
        value: The new value for the key.
        table (str, optional): The table name for the key within a table. Defaults to None (top-level).

    Raises:
        KeyError: If the key is not found.
    """
    if table:
      if table not in self.data:
        raise KeyError(f"Table not found: {table}")
      if key not in self.data[table]:
        raise KeyError(f"Key not found in table {table}: {key}")
      self.data[table][key] = value
    else:
      if key not in self.data:
        raise KeyError(f"Key not found: {key}")
      self.data[key] = value

  def delete(self, key, table=None):
    """
    Deletes a key-value pair.

    Args:
        key (str): The key to delete.
        table (str, optional): The table name for the key within a table. Defaults to None (top-level).

    Raises:
        KeyError: If the key is not found.
    """
    if table:
      if table not in self.data:
        raise KeyError(f"Table not found: {table}")
      if key not in self.data[table]:
        raise KeyError(f"Key not found in table {table}: {key}")
      del self.data[table][key]
    else:
      if key not in self.data:
        raise KeyError(f"Key not found: {key}")
      del self.data[key]

  def save(self):
    """
    Saves the modified data back to the TOML file.
    """
    with open(self.file_path, "w") as f:
      toml.dump(self.data, f)

"""
# Example usage
editor = TomlEditor("config.toml")
editor.load()

# Add a new top-level key-value pair
editor.add("new_key", "new_value")

# Update a key within a table (assuming a table named "server" exists)
editor.update("host", "updated_host", table="server")

# Delete a key within a table (assuming a table named "server" exists)
editor.delete("port", table="server")

editor.save()
"""