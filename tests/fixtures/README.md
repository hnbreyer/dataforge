# Fixture expectations

`sales.csv` has five records and six columns. The fourth record duplicates the
third. `amount` has one missing value; `customer` has two; `date` includes one
invalid date. Numeric amount total across nonmissing values is exactly 36.90.
Grouped totals before cleaning: Food 6.60 (three rows), Office 30.30 (two rows).

The example clean pipeline retains three records and calculates line totals:
Office 20.20, Office 20.20, Food 9.90. Its report groups these as food 9.90 and
office 40.40. Source bytes and the original five records must remain unchanged.

`sales-rules.json` in examples produces four issues: duplicate ID at record 4,
missing amount at record 5, invalid date at record 5, and a duplicate-row warning
at record 4. The run fails because three issues have error severity.

`people.json` demonstrates Unicode, JSON numeric decimals (preserved as exact
strings 0.10 and 0.20), a late-discovered boolean column, and absent properties
mapped to null. It has two records and four columns. No fixtures contain secrets.

Tests generate malformed inputs in memory and use pytest temporary directories;
no test reads or writes the normal `.dataforge` workspace.
