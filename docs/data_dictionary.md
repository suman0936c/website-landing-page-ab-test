# Data Dictionary

| Field | Definition |
|---|---|
| user_id | experiment participant identifier |
| timestamp | logged experimental exposure timestamp |
| group | control or treatment assignment |
| landing_page | old_page or new_page shown |
| converted | binary conversion outcome |
| country | UK, US, or CA from the supplied country mapping |

The clean table has one first valid exposure per user. The original source
files remain unchanged in `data/`.
