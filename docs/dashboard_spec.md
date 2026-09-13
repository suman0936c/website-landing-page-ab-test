# Dashboard Specification

## Decision panel

Show control and treatment conversion, absolute difference, confidence
interval, p-value, and decision: do not ship from this evidence alone.

## Quality and segmentation

- Raw to clean reconciliation
- Country conversion comparison with user counts
- Daily conversion-rate lines by experiment group

Use `outputs/ab_clean.csv` for post-cleaning charts and display the cleaning
reconciliation first. Label country cuts exploratory.
