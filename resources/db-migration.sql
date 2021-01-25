# Drop foreign key constraints
alter table subscriptions drop foreign key subscriptions_ibfk_1;
alter table user_feedback drop foreign key user_feedback_ibfk_1;

# Alter to new UserManager scheme
alter table bot_user change user_id platform_id VARCHAR(100) not null;
alter table bot_user drop primary key;

alter table bot_user
	add platform VARCHAR(10) null;

alter table bot_user
	add user_id int auto_increment primary key;

alter table bot_user
	add constraint bot_user_unique
        unique (platform_id, platform);

# Migrate NULL users to Telegram
UPDATE bot_user SET platform="telegram" WHERE platform IS NULL;

UPDATE subscriptions, (SELECT platform_id, user_id FROM bot_user) as user
SET subscriptions.user_id=user.user_id WHERE subscriptions.user_id=user.platform_id;

UPDATE user_feedback, (SELECT platform_id, user_id FROM bot_user) as user
SET user_feedback.user_id=user.user_id WHERE user_feedback.user_id=user.platform_id;

alter table subscriptions
	add constraint subscriptions_ibfk_1
		foreign key (user_id) references bot_user (user_id);

alter table user_feedback
	add constraint user_feedback_ibfk_1
		foreign key (user_id) references bot_user (user_id);

