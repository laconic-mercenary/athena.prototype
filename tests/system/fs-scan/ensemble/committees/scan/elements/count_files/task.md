# Element: count_files

Count files under a directory by extension, read-only.

## Assignment template
Count files under [DIRECTORY: absolute path]
matching [EXTENSIONS: list of extensions with the dot, e.g. .py .md .txt].

## Output shape
The raw skill result, unmodified: `directory`, `counts` (list of {extension, count}),
`total_files`, `skipped`. No interpretation.

## Skills
- `count_extensions(directory, extensions)` — read-only recursive tally; does not open file
  contents or follow symlinks.

## Limitations
Read-only. Does not read file contents. Does not follow symlinks. Counts only the extensions given.

## Adequacy criterion
The walk completed and a count is present for every requested extension.
