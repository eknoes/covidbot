alter table covid_data
	add last_update DATETIME default NOW() null;

alter table bot_user_sent_reports add report VARCHAR(40);
UPDATE bot_user_sent_reports SET report='cases-germany' WHERE report IS NULL;

alter table bot_user change added created datetime(6) default current_timestamp(6) not null;

DROP VIEW covid_data_calculated;