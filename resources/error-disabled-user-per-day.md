# Disabled users per day

SQL Query:
```sql
SELECT COUNT(platform_id), platform, DATE(reports.d) FROM bot_user LEFT JOIN (SELECT user_id, MAX(sent_report) as d FROM bot_user_sent_reports GROUP BY user_id) as reports  ON reports.user_id = bot_user.user_id WHERE activated=0 GROUP BY platform, DATE(reports.d) ORDER BY DATE(reports.d)
```

| COUNT\(platform\_id\) | platform | DATE\(reports.d\) |
| :--- | :--- | :--- |
| 530 | signal | 2021-08-10 |
| 40 | messenger | 2021-08-10 |
| 3 | signal | 2021-08-11 |
| 1 | signal | 2021-08-12 |
| 2 | signal | 2021-08-15 |
| 1 | signal | 2021-08-16 |
| 1 | signal | 2021-08-17 |
| 3 | signal | 2021-08-19 |
| 2 | signal | 2021-08-20 |
| 1 | messenger | 2021-08-21 |
| 1 | signal | 2021-08-22 |
| 2 | signal | 2021-08-23 |
| 2 | signal | 2021-08-24 |
| 1 | signal | 2021-08-25 |
| 1 | messenger | 2021-08-26 |
| 1 | signal | 2021-08-29 |
| 3 | signal | 2021-08-30 |
| 1 | signal | 2021-08-31 |
| 1 | signal | 2021-09-01 |
| 2 | signal | 2021-09-02 |
| 197 | messenger | 2021-09-02 |
| 2 | signal | 2021-09-04 |
| 2 | signal | 2021-09-07 |
| 2 | signal | 2021-09-08 |
| 1 | signal | 2021-09-09 |
| 1 | signal | 2021-09-12 |
| 1 | signal | 2021-09-14 |
| 1 | signal | 2021-09-17 |
| 1 | signal | 2021-09-18 |
| 1 | signal | 2021-09-19 |
| 1 | signal | 2021-09-20 |
| 2 | signal | 2021-09-21 |
| 1 | signal | 2021-09-22 |
| 2 | signal | 2021-09-23 |
| 1 | signal | 2021-09-24 |
| 1 | messenger | 2021-09-26 |
| 367 | signal | 2021-09-26 |
| 290 | signal | 2021-09-27 |
| 1 | signal | 2021-09-29 |
