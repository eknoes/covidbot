alter table covid_data modify date date null default null;
INSERT INTO counties (rs, county_name, type, parent) VALUE (0, "Deutschland", "Staat", NULL);
UPDATE counties SET parent=0 WHERE type="Bundesland";

INSERT INTO covid_data (rs, date, total_cases, total_deaths)
                                SELECT new.parent, new_date, new_cases, new_deaths
                                FROM
                                (SELECT c.parent as parent, date as new_date, SUM(total_cases) as new_cases,
                                 SUM(total_deaths) as new_deaths FROM covid_data_calculated
                                 LEFT JOIN counties c on covid_data_calculated.rs = c.rs
                                 WHERE c.parent IS NOT NULL
                                 GROUP BY c.parent, date)
                                as new
                              ON DUPLICATE KEY UPDATE date=new.new_date, total_cases=new.new_cases, total_deaths=new.new_deaths
INSERT INTO covid_data (rs, date, total_cases, total_deaths)
                                SELECT new.parent, new_date, new_cases, new_deaths
                                FROM
                                (SELECT c.parent as parent, date as new_date, SUM(total_cases) as new_cases,
                                 SUM(total_deaths) as new_deaths FROM covid_data_calculated
                                 LEFT JOIN counties c on covid_data_calculated.rs = c.rs
                                 WHERE c.parent IS NOT NULL
                                 GROUP BY c.parent, date)
                                as new
                              ON DUPLICATE KEY UPDATE date=new.new_date, total_cases=new.new_cases, total_deaths=new.new_deaths