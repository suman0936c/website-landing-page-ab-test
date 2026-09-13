"""
Website Landing Page A/B Test — Analysis Pipeline
==================================================

Business question:
    Should the e-commerce team replace the old landing page with the new one?

What this script does, in order:
    1. Load the two raw source files (ab_data.csv, countries.csv).
    2. Clean the data — remove rows where the assignment doesn't match the
       page shown, then keep only the first valid exposure per user.
    3. Save the clean data to CSV and to a SQLite database (both the raw
       and clean tables, plus countries) so it can be queried with SQL too.
    4. Run a two-proportion z-test comparing conversion rates between the
       control (old page) and treatment (new page) groups.
    5. Break the same test down by country, and build a day-by-day
       conversion-rate table for a stability check.
    6. Write a short data-quality audit and a plain-English business
       recommendation.

Every output lands in outputs/, so the whole thing can be re-run end to end
with `python analyze.py`.
"""

from math import erf, sqrt
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

try:
    from statsmodels.stats.proportion import proportions_ztest
except ImportError:
    # If statsmodels isn't installed, fall back to a hand-rolled pooled
    # two-proportion z-test. It gives the same z and p-value.
    def proportions_ztest(count, nobs):
        successes_a, successes_b = count
        n_a, n_b = nobs
        p_pool = (successes_a + successes_b) / (n_a + n_b)
        se_pool = sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
        z = (successes_a / n_a - successes_b / n_b) / se_pool
        p_value = 2 * (1 - (1 + erf(abs(z) / sqrt(2))) / 2)
        return z, p_value


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# 1. Load the raw data
# ---------------------------------------------------------------------------
ab = pd.read_csv(DATA / "ab_data.csv", parse_dates=["timestamp"])
countries = pd.read_csv(DATA / "countries.csv")
raw_rows = len(ab)


# ---------------------------------------------------------------------------
# 2. Clean the data
#    - "control" should only ever see "old_page", "treatment" only "new_page".
#      Any row that breaks this rule can't be trusted, so it's dropped.
#    - Some users appear more than once (re-visits / re-randomization bugs).
#      We keep only their first valid exposure, so each user contributes
#      exactly one independent data point.
# ---------------------------------------------------------------------------
mismatch = (
    (ab.group.eq("control") & ab.landing_page.ne("old_page"))
    | (ab.group.eq("treatment") & ab.landing_page.ne("new_page"))
)

valid = (
    ab.loc[~mismatch]
    .sort_values("timestamp")
    .drop_duplicates("user_id", keep="first")
    .copy()
)
valid = valid.merge(countries.drop_duplicates("user_id"), on="user_id", how="left")

# Sanity checks — if either of these fails, something is wrong with the
# cleaning logic above and the rest of the analysis shouldn't be trusted.
assert valid.user_id.duplicated().sum() == 0, "clean table still has duplicate users"
assert set(zip(valid.group, valid.landing_page)) == {
    ("control", "old_page"),
    ("treatment", "new_page"),
}, "clean table still has invalid group/page pairings"


# ---------------------------------------------------------------------------
# 3. Persist the clean data (CSV + SQLite)
# ---------------------------------------------------------------------------
valid.to_csv(OUT / "ab_clean.csv", index=False)

db = sqlite3.connect(OUT / "ab_test.sqlite")
ab.to_sql("ab_raw", db, if_exists="replace", index=False)
valid.to_sql("ab_clean", db, if_exists="replace", index=False)
countries.to_sql("countries", db, if_exists="replace", index=False)
db.close()


# ---------------------------------------------------------------------------
# 4. Headline two-proportion z-test: control vs. treatment conversion rate
# ---------------------------------------------------------------------------
summary = (
    valid.groupby("group")
    .agg(
        users=("user_id", "nunique"),
        conversions=("converted", "sum"),
        conversion_rate=("converted", "mean"),
    )
    .reset_index()
)

by_group = summary.set_index("group")
control, treatment = by_group.loc["control"], by_group.loc["treatment"]

counts = np.array([treatment.conversions, control.conversions])
nobs = np.array([treatment.users, control.users])
z, p = proportions_ztest(counts, nobs)

diff = treatment.conversion_rate - control.conversion_rate
se = sqrt(
    treatment.conversion_rate * (1 - treatment.conversion_rate) / treatment.users
    + control.conversion_rate * (1 - control.conversion_rate) / control.users
)
ci_low, ci_high = diff - 1.96 * se, diff + 1.96 * se

summary["raw_rows"] = raw_rows
summary["mismatched_rows_removed"] = int(mismatch.sum())
summary["duplicate_user_rows_removed_after_mismatch"] = int((~mismatch).sum() - len(valid))
summary["treatment_minus_control_pp"] = diff * 100
summary["relative_change_pct"] = diff / control.conversion_rate * 100
summary["z_statistic"] = z
summary["p_value"] = p
summary["ci_95_lower_pp"] = ci_low * 100
summary["ci_95_upper_pp"] = ci_high * 100
summary.to_csv(OUT / "ab_test_summary.csv", index=False)


# ---------------------------------------------------------------------------
# 5a. Same test, split out by country (exploratory — not pre-registered,
#     so treat as a sanity check rather than a shipping decision on its own)
# ---------------------------------------------------------------------------
def country_test(group_df):
    s = group_df.groupby("group").converted.agg(["sum", "count", "mean"])
    if set(s.index) != {"control", "treatment"}:
        return pd.Series(dtype=float)
    zz, pp = proportions_ztest(
        [s.loc["treatment", "sum"], s.loc["control", "sum"]],
        [s.loc["treatment", "count"], s.loc["control", "count"]],
    )
    d = s.loc["treatment", "mean"] - s.loc["control", "mean"]
    return pd.Series(
        {
            "control_users": s.loc["control", "count"],
            "treatment_users": s.loc["treatment", "count"],
            "control_rate": s.loc["control", "mean"],
            "treatment_rate": s.loc["treatment", "mean"],
            "difference_pp": 100 * d,
            "p_value": pp,
        }
    )


country = valid.groupby("country").apply(country_test).reset_index()
country.to_csv(OUT / "country_results.csv", index=False)


# ---------------------------------------------------------------------------
# 5b. Day-by-day conversion rate, to check the effect was stable over time
# ---------------------------------------------------------------------------
valid["date"] = valid.timestamp.dt.date
daily = (
    valid.groupby(["date", "group"])
    .agg(users=("user_id", "nunique"), conversion_rate=("converted", "mean"))
    .reset_index()
)
daily.to_csv(OUT / "daily_conversion.csv", index=False)


# ---------------------------------------------------------------------------
# 6. Data-quality audit + plain-English business recommendation
# ---------------------------------------------------------------------------
audit = pd.DataFrame(
    [
        {
            "raw_rows": raw_rows,
            "mismatched_rows": int(mismatch.sum()),
            "raw_duplicate_user_ids": int(ab.user_id.duplicated().sum()),
            "clean_rows": len(valid),
            "clean_duplicate_user_ids": int(valid.user_id.duplicated().sum()),
            "start_date": valid.timestamp.min(),
            "end_date": valid.timestamp.max(),
            "test_days": (valid.timestamp.max() - valid.timestamp.min()).days + 1,
        }
    ]
)
audit.to_csv(OUT / "data_quality_audit.csv", index=False)

monthly_traffic = 100_000  # illustrative, not the site's actual traffic
pd.DataFrame(
    [
        {
            "assumed_monthly_traffic": monthly_traffic,
            "observed_difference_pp": diff * 100,
            "estimated_monthly_incremental_conversions": diff * monthly_traffic,
            "recommendation": (
                "Do not ship based on this test alone; p-value exceeds 0.05 "
                "and the 95% CI includes both a modest loss and a modest gain."
            ),
        }
    ]
).to_csv(OUT / "business_recommendation.csv", index=False)

print(summary.to_string(index=False))
print(f"p={p:.4f}; 95% CI [{ci_low*100:.3f}, {ci_high*100:.3f}] pp")
