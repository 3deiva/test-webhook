import json
def show_all(json_file):
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    for file_info in data.get("backend_analysis", []):
        print(f"\n📂 File: {file_info['file']}")
        print(f"   Language: {file_info['language']}")

        # Show functions
        if file_info.get("functions"):
            print("   🔹 Functions:")
            for i, func in enumerate(file_info["functions"], 1):
                print(f"      {i}. {func['name']} (lines {func['line']}–{func['end_line']})")
        else:
            print("   🔹 Functions: None")

        # Show routes
        if file_info.get("routes"):
            print("   🌐 Routes:")
            for i, route in enumerate(file_info["routes"], 1):
                print(f"      {i}. [{route['framework']}] {route['methods']} {route['path']}")
        else:
            print("   🌐 Routes: None")


if __name__ == "__main__":
    show_all("complete_repo_analysis.json")  # change if JSON has different name
