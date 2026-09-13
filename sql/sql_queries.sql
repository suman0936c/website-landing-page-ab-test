-- Validate original assignment/page combinations before any inferential work.
SELECT "group", landing_page, COUNT(*) AS rows
FROM ab_raw GROUP BY 1,2 ORDER BY 1,2;

SELECT user_id, COUNT(*) AS rows_per_user
FROM ab_raw GROUP BY user_id HAVING COUNT(*) > 1;

-- Clean-population QA: exactly two valid pairings and one row per user.
SELECT "group", landing_page, COUNT(*) FROM ab_clean GROUP BY 1,2;
SELECT COUNT(*) - COUNT(DISTINCT user_id) AS duplicate_users FROM ab_clean;

-- Country segmentation is a left join: missing country should remain auditable.
SELECT country, "group", COUNT(*) users, AVG(converted) conversion_rate
FROM ab_clean GROUP BY country, "group";
