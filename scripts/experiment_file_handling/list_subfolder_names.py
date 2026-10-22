from tcm_utils.file_dialogs import ask_directory

SAVE_LIST = True  # Set to False to just print the list of subfolder names without saving

# Ask the user to open a directory
directory = ask_directory(
    key="list_names_input_directory",
    title="Select a directory to list subfolder names from",
)
if directory is None:
    print("No directory selected. Exiting.")
    exit(1)

# List the names of all subfolders in the selected directory
subfolder_names = [
    entry.name for entry in directory.iterdir() if entry.is_dir()
]

# Print the list of subfolder names
print("Subfolder names:")
for name in subfolder_names:
    print(name)

# If SAVE_LIST is True, save the list of subfolder names to a text file
if SAVE_LIST:
    output_directory = ask_directory(
        key="list_names_output_directory",
        title="Select a directory to save the list of subfolder names to",
    )
    if output_directory is None:
        print("No output directory selected. Exiting.")
        exit(1)

    file_name = directory.name + "_subfolder_names.txt"
    output_file = output_directory / file_name
    with open(output_file, "w") as f:
        for name in subfolder_names:
            f.write(name + "\n")
    print(f"List of subfolder names saved to: {output_file}")
