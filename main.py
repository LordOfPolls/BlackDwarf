"""
Eliminates wildcard imports from a provided target_file.

wildcard imports are depicted as an import with an asterisk, or star, hence the name
"""
import ast
import difflib
import importlib
import importlib.util
import os
import subprocess
import sys
from _ast import Module

from collections import namedtuple
from contextlib import suppress

__all__ = (
    "de_wildcard",
    "process_file",
    "process_imports",
    "search_for_usages",
    "get_dunder_all",
)

from pathlib import Path

Import = namedtuple("Import", ["lineno", "endlineno", "module", "names"])
Replacement = namedtuple("Replacement", ["lineno", "endlineno", "content", "module"])


def de_wildcard(
    target_file: str,
    *,
    path: str = None,
    module_name: str = None,
    infer_imports: bool = True,
    dry_run: bool = False,
    prefix: str = "",
) -> bool:
    """
    Eliminates wildcard imports from a provided target_file.

    Args:
        target_file: The target file to process
        path: The path to the target file
        module_name: The name of the module
        infer_imports: Whether or not to infer imports if __all__ is not found
        dry_run: Whether or not to actually write the changes
        prefix: The prefix to use for printing

    Returns:
        True if changes were made, otherwise False
    """
    full_path = os.path.join(path, target_file) if path else target_file
    import_path = path.replace(os.sep, ".") if path else None

    tree = ast.parse(open(full_path, encoding="utf-8").read())

    imports, wildcard_imports = process_imports(tree)
    replacements = []

    if not wildcard_imports:
        return False

    print(f"{prefix}Processing {import_path}.{target_file}...")

    for wildcard_import in wildcard_imports:
        # recursively process the file and get the imports needed
        _all_ = process_file(
            target=wildcard_import.module,
            import_path=import_path,
            module_name=module_name,
            prefix=prefix,
            infer_imports=infer_imports,
            parent_tree=tree,
        )
        if _all_:
            replacements.append(
                Replacement(
                    lineno=wildcard_import.lineno,
                    endlineno=wildcard_import.endlineno,
                    content=f"from {wildcard_import.module} import {', '.join(_all_)}",
                    module=wildcard_import.module,
                )
            )

    if replacements:
        with open(full_path, "r", encoding="utf-8") as reader:
            lines = reader.readlines()
            buffer = lines.copy()
            for replacement in replacements:
                if f".{replacement.module}" in buffer[replacement.lineno - 1]:
                    # import is relative
                    replacement = Replacement(
                        lineno=replacement.lineno,
                        endlineno=replacement.endlineno,
                        content=replacement.content.replace(
                            f"from {replacement.module}", f"from .{replacement.module}"
                        ),
                        module=replacement.module,
                    )
                buffer[replacement.lineno - 1 : replacement.endlineno] = [
                    replacement.content + "\n"
                ]

            if not dry_run:
                print(f"{prefix}Writing changes to {full_path}...")
                with open(full_path, "w", encoding="utf-8") as writer:
                    writer.writelines(buffer)
                sys.modules.pop(".".join(full_path.split(os.sep)[:-1]), None)
            else:
                for line in difflib.unified_diff(
                    lines, buffer, fromfile=full_path, tofile=full_path
                ):
                    sys.stdout.write(line)
                pass
        return True
    return False


def process_file(
    target: str,
    import_path,
    module_name,
    prefix,
    *,
    infer_imports=True,
    parent_tree: Module | None = None,
):
    """
    Processes a file and returns the imports it yields

    Args:
        target: The target file to process
        import_path: The path to the target file
        module_name: The name of the module
        prefix: The prefix to use for printing
        infer_imports: Whether or not to infer imports if __all__ is not found

    Returns:
        A list of imports
    """
    # basically im abusing importlib to get the file path of the target we need to process
    # this is because the target file is likely an __init__.py file under a package, but we don't actually know for sure

    try:
        child_m = importlib.import_module(f"{import_path}.{target}", module_name)
    except ModuleNotFoundError:
        # if the module is not found, it's probably a library, attempt to find it
        with suppress(ModuleNotFoundError):
            if module := importlib.import_module(target):
                if hasattr(module, "__all__"):
                    targets = module.__all__
                else:
                    targets = [o for o in dir(module) if not o.startswith("__")]
                # search ast for usage
                if parent_tree:
                    if usages := search_for_usages(parent_tree, targets):
                        print(
                            f"{prefix}Found {len(usages)} usages of {target} in {import_path}.{module_name}"
                        )
                        return usages
        raise RuntimeError(f"Could not process {target}!")

    child_tree = ast.parse(open(child_m.__file__, encoding="utf-8").read())
    _all_ = get_dunder_all(child_tree)
    if not _all_:
        if infer_imports:
            imports, wildcard_imports = process_imports(child_tree)
            if wildcard_imports:
                for wildcard_import in wildcard_imports:
                    imports.extend(
                        process_file(
                            target=f"{target}.{wildcard_import.module}",
                            import_path=import_path,
                            module_name=module_name,
                            infer_imports=infer_imports,
                            prefix=prefix + "\t",
                            parent_tree=child_tree,
                        )
                    )
            _all_ = imports

            if _all_:
                print(
                    f"{prefix}\tNo __all__ found in {import_path}.{target}; {len(_all_)} {'imports have' if len(_all_) != 1 else 'import has'} been inferred"
                )

        else:
            print(f"{prefix}\tNo __all__ found in {import_path}.{target}")
    return list(sorted(set(_all_), key=lambda x: x.lower()))


def search_for_usages(m: Module, targets: list[str]) -> list[str]:
    """
    Searches an AST to determine if any of the targets are used

    Args:
        m: The module to search
        targets: The targets to search for

    Returns:
        A list of targets that are used
    """
    used = set()
    for node in ast.walk(m):
        if (name := getattr(node, "name", "")) in targets:
            used.add(name)
        if (name := getattr(node, "id", "")) in targets:
            used.add(name)

    return list(used)


def get_dunder_all(m: Module) -> list[str] | None:
    """
    Gets the __all__ attribute from a given module

    Args:
        m: The module to get the __all__ attribute from

    Returns:
        A list of strings if __all__ is found, otherwise None
    """
    for node in ast.walk(m):
        if isinstance(node, ast.Assign):
            if len(node.targets) == 1:
                if isinstance(node.targets[0], ast.Name):
                    if node.targets[0].id == "__all__":
                        return [n.s for n in node.value.elts]
    return None


def process_imports(m: Module) -> tuple[list[str], list[Import]]:
    """
    Processes the imports in a given module

    Args:
        m: The module to process

    Returns:
        A tuple of two lists. The first list contains all the imports, and the second list contains all the wildcard imports
    """
    imports = []
    wildcard_imports = []
    for node in ast.walk(m):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if node.names[0].name == "*":
                wildcard_imports.append(
                    Import(
                        node.lineno, node.end_lineno, node.module, node.names[0].name
                    )
                )
            else:
                imports.extend([n.name for n in node.names])
    return imports, wildcard_imports


def __main__(
    path: str,
    module: str | None = None,
    dry_run: bool = True,
    infer_imports: bool = True,
    no_format: bool = False,
) -> None:
    if module:
        importlib.import_module(module)

    # find all python files and their relative paths
    found = []
    for root, dirs, files in os.walk(path or "."):
        for file in files:
            if file.endswith(".py"):
                found.append((file, root))
    print(f"Found {len(found)} files to process...")

    # sort by depth, so we process the deepest files first - this helps speed up processing
    found.sort(key=lambda x: x[1].count(os.sep), reverse=True)

    for file, relative_path in found:
        de_wildcard(
            file,
            path=relative_path,
            module_name=module,
            infer_imports=infer_imports,
            dry_run=dry_run,
        )

    print("====================================")
    if no_format:
        print("Processing done, skipping black...")
    else:
        print("Processing done, running black...")
        subprocess.run(["black", path or "."])


def entry_point():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="The path to process")
    parser.add_argument("-m", "--module", help="The module_name to import from.")
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Don't write changes to disk. Instead, print a diff. (default: False)",
        default=False,
    )
    parser.add_argument(
        "-i",
        "--infer-imports",
        action="store_true",
        help="Infer __all__ from imports. (default: True)",
        default=True,
    )
    parser.add_argument(
        "-nf",
        "--no-format",
        action="store_true",
        help="Don't run black after processing. (default: False)",
        default=False,
    )
    args = parser.parse_args()

    print(
        """
______ _            _   ______                     __ 
| ___ \ |          | |  |  _  \                   / _|
| |_/ / | __ _  ___| | _| | | |_      ____ _ _ __| |_ 
| ___ \ |/ _` |/ __| |/ / | | \ \ /\ / / _` | '__|  _|
| |_/ / | (_| | (__|   <| |/ / \ V  V / (_| | |  | |  
\____/|_|\__,_|\___|_|\_\___/   \_/\_/ \__,_|_|  |_|  """
    )  # noqa

    if os.path.isdir(args.path):
        path = Path(args.path)

        os.chdir(path.parent)
        sys.path.append(str(path.parent))
        args.path = path.name

        if not args.module:
            args.module = args.path.replace("\\", ".")

        print("Processing directory", args.path)

    else:
        print("Error: Path is not a directory")
        exit(1)

    __main__(
        path=args.path,
        module=args.module,
        dry_run=args.dry_run,
        infer_imports=args.infer_imports,
        no_format=args.no_format,
    )


if __name__ == "__main__":
    entry_point()
