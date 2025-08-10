import ast
import sys

def get_version_from_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read(), filename=file_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == 'plugin_version':
                    if isinstance(node.value, ast.Constant):
                        return node.value.value
                    elif isinstance(node.value, (ast.Str, ast.Num)):
                        return node.value.s

    return None

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python get_version.py <path_to_python_file>", file=sys.stderr)
        sys.exit(1)

    file_path = sys.argv[1]
    version = get_version_from_file(file_path)

    if version:
        print(version)
    else:
        print(f"Error: Could not find 'plugin_version' in {file_path}", file=sys.stderr)
        sys.exit(1)
