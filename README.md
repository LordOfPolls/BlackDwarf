# BlackDwarf

BlackDwarf is a Python script that eliminates wildcard imports, also known as "star imports", from a provided target file. The script uses the ast module to parse and analyze the target file, and then replaces wildcard imports with specific imports, making the code more readable and maintainable. The script also has options for dry-run mode, prefixing output, and inferring imports.


## Usage

    usage: blackdwarf [-d] [-i] target

    positional arguments:
      target                The directory to be processed

    optional arguments:
      -m, --module          The module to be processed
      -d, --dry-run         Dry run mode - No changes will be applied to disk
      -i, --infer-imports   Disable inference of imports in situations where a file lacks `__all__`