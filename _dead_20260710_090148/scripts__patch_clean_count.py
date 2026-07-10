with open('dv_pipeline.py', encoding='utf-8') as f:
    content = f.read()

# Fix ValidationSummary to separate error_ids from warning_ids
old = '''@dataclass
class ValidationSummary:
    ok:           bool
    rows_checked: int
    error_count:  int
    warning_count: int
    issues:       list[dict] = field(default_factory=list)
    bad_row_ids:  list[int]  = field(default_factory=list)

    @property
    def reject_row_ids(self) -> list[int]:
        return self.bad_row_ids

    @property
    def clean_count(self) -> int:
        return self.rows_checked - len(set(self.bad_row_ids))'''

new = '''@dataclass
class ValidationSummary:
    ok:           bool
    rows_checked: int
    error_count:  int
    warning_count: int
    issues:       list[dict] = field(default_factory=list)
    bad_row_ids:  list[int]  = field(default_factory=list)  # ERROR rows only
    warn_row_ids: list[int]  = field(default_factory=list)  # WARNING rows only

    @property
    def reject_row_ids(self) -> list[int]:
        """Only ERROR rows go to rejection file — warnings still promote."""
        return self.bad_row_ids

    @property
    def clean_count(self) -> int:
        """Rows that will promote = total minus error rows."""
        return self.rows_checked - len(set(self.bad_row_ids))'''

if old in content:
    content = content.replace(old, new, 1)
    print("ValidationSummary updated")
else:
    print("Pattern not found")

# Fix return statement to pass warn_row_ids
old2 = '''    return ValidationSummary(
        ok=error_count == 0,
        rows_checked=total,
        error_count=error_count,
        warning_count=warning_count,
        issues=issues,
        bad_row_ids=list(bad_ids),
    )'''

new2 = '''    return ValidationSummary(
        ok=error_count == 0,
        rows_checked=total,
        error_count=error_count,
        warning_count=warning_count,
        issues=issues,
        bad_row_ids=list(bad_ids),
        warn_row_ids=[],
    )'''

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("Return statement updated")

with open('dv_pipeline.py', 'w', encoding='utf-8') as f:
    f.write(content)

import py_compile
try:
    py_compile.compile('dv_pipeline.py', doraise=True)
    print("Syntax OK")
except py_compile.PyCompileError as e:
    print(f"Error: {e}")

# Now check what's adding to bad_ids
print("\nChecking bad_ids additions:")
for line in content.split('\n'):
    if 'bad_ids.add' in line:
        print(f"  {line.strip()}")
